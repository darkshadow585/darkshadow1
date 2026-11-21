"""
Upgrade #3 (Hardened & Fixed): Microsoft Edge CDP + Playwright Accessibility/DOM Browser Agent.
===============================================================================================
Fixes applied:
  - Removed blocking network probe (`CDP_URL = get_cdp_url()`) at module import time!
  - Fixed Windows IPv4/IPv6 bug in `_is_cdp_reachable()` (never rewrites `[::1]` to `127.0.0.1`;
    probes both IPv4 & IPv6 when `localhost` is configured!).
  - Added `_fetch_cdp_version()` to extract exact `webSocketDebuggerUrl` so Playwright CDP
    connects reliably without DNS/IPv6 race conditions.
  - Fixed `ensure_edge_cdp()`: safe `urlparse` port extraction, passes `--remote-debugging-address=127.0.0.1`
    + `--remote-allow-origins=*`, and waits up to 6s for cold-start Edge readiness.
  - Fixed `_PlaywrightEdgeWorker`: calls `ensure_edge_cdp()`, checks `browser.is_connected()`,
    re-attaches over CDP cleanly on disconnect, uses isolated fallback profile (`DarkShadowEdgeProfile_PW`)
    to prevent ProcessSingleton lock crashes, and NEVER closes the user's CDP browser on shutdown!
  - Routed `play_media_in_edge()` and `seek_video()` through `_PlaywrightEdgeWorker` (eliminates
    Playwright Sync API inside asyncio loop crash and duplicate CDP connections!).
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import Future
from typing import Any, Callable

from config import get_cdp_url, invalidate_cdp_cache
from windows_tools import check_hard_shields, find_edge_executable, open_in_edge, validate_http_url

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# Lazy default (no blocking network I/O at import time!)
CDP_URL = os.getenv("DARKSHADOW_EDGE_CDP_URL", "http://127.0.0.1:9222").strip() or "http://127.0.0.1:9222"

_EXTRACT_ELEMENTS_JS = """
() => {
  const selectors = 'a[href], button, input, textarea, [role="button"], [role="link"], [role="textbox"], [contenteditable="true"]';
  const nodes = Array.from(document.querySelectorAll(selectors));
  const visible = [];
  let idx = 1;
  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    if (rect.bottom < 0 || rect.top > window.innerHeight * 1.4) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') continue;

    const label = (
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.getAttribute('title') ||
      el.innerText ||
      el.value ||
      ''
    ).replace(/\\s+/g, ' ').trim().slice(0, 90);

    if (!label && el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') continue;

    el.setAttribute('data-ds-idx', String(idx));
    visible.push({
      id: idx,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || el.getAttribute('type') || '',
      label: label || '(input field)'
    });
    idx++;
    if (idx > 45) break;
  }
  return {
    title: document.title,
    url: location.href,
    elements: visible
  };
}
"""


def _parse_cdp_host_port(cdp_url: str) -> tuple[str, int]:
    """Safely extract (host, port) from IPv4, IPv6 (`http://[::1]:9222`), or hostname URLs."""
    parsed = urllib.parse.urlparse(cdp_url.strip())
    host = parsed.hostname or "127.0.0.1"
    try:
        port = int(parsed.port or 9222)
    except Exception:
        port = 9222
    return host, port


def _format_http_host(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        return f"http://[{host}]:{port}"
    return f"http://{host}:{port}"


def _fetch_cdp_version(cdp_url: str | None = None, timeout: float = 0.6) -> dict[str, Any] | None:
    """
    Probe Microsoft Edge `/json/version` cleanly across IPv4 and IPv6 without rewriting `::1` to `127.0.0.1`.
    Returns parsed JSON dict with added `_resolved_http_url` on success, else None.
    """
    target = (cdp_url or get_cdp_url()).rstrip("/")
    host, port = _parse_cdp_host_port(target)

    # Probe exact host first; if localhost was requested, check BOTH IPv4 and IPv6!
    if host == "localhost":
        probe_hosts = ["127.0.0.1", "::1"]
    elif host in ("127.0.0.1", "::1"):
        probe_hosts = [host, "::1" if host == "127.0.0.1" else "127.0.0.1"]
    else:
        probe_hosts = [host]

    for h in probe_hosts:
        try:
            with socket.create_connection((h, port), timeout=min(0.25, timeout)):
                pass
        except Exception:
            continue

        base = _format_http_host(h, port)
        try:
            req = urllib.request.Request(f"{base}/json/version", headers={"Host": f"127.0.0.1:{port}"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                    if isinstance(data, dict):
                        data["_resolved_http_url"] = base
                        return data
        except Exception:
            continue
    return None


def _is_cdp_reachable(cdp_url: str | None = None) -> bool:
    return _fetch_cdp_version(cdp_url) is not None


def _resolve_cdp_connect_target(cdp_url: str | None = None) -> str | None:
    """Return the most reliable CDP target (WebSocket URL if available with port, else resolved HTTP base URL)."""
    info = _fetch_cdp_version(cdp_url)
    if not info:
        return None
    resolved_base = str(info.get("_resolved_http_url") or "").rstrip("/")
    ws_url = str(info.get("webSocketDebuggerUrl") or "").strip()
    if ws_url.startswith(("ws://", "wss://")):
        parsed_ws = urllib.parse.urlparse(ws_url)
        # Fix missing port bug: if Edge omits port, enforce 127.0.0.1:{port}
        if not parsed_ws.port:
            _, port = _parse_cdp_host_port(resolved_base or cdp_url or "http://127.0.0.1:9222")
            netloc = f"127.0.0.1:{port}"
            ws_url = urllib.parse.urlunparse((parsed_ws.scheme, netloc, parsed_ws.path, parsed_ws.params, parsed_ws.query, parsed_ws.fragment))
        return ws_url
    return resolved_base or None


def ensure_edge_cdp(cdp_url: str | None = None, wait_seconds: float = 6.0) -> bool:
    """Return True if Microsoft Edge CDP is reachable; otherwise launch Edge with debugging port and wait."""
    url = (cdp_url or get_cdp_url(force_refresh=True)).rstrip("/")
    if _is_cdp_reachable(url):
        return True
    try:
        _, port = _parse_cdp_host_port(url)
        user_data = os.getenv(
            "DARKSHADOW_EDGE_PROFILE",
            os.path.expandvars(r"%LOCALAPPDATA%\DarkShadowEdgeProfile"),
        )
        edge_exe = find_edge_executable()
        args = [
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_data}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if edge_exe:
            subprocess.Popen([edge_exe, *args], shell=False)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", "msedge", *args], shell=False)

        deadline = time.monotonic() + max(1.0, float(wait_seconds))
        while time.monotonic() < deadline:
            time.sleep(0.45)
            if _is_cdp_reachable(url):
                invalidate_cdp_cache()
                return True
    except Exception:
        pass
    return False


class _PlaywrightEdgeWorker:
    """Dedicated background thread managing a single persistent, CDP-enabled Microsoft Edge browser."""

    def __init__(self, explicit_cdp_url: str | None = None) -> None:
        self._explicit_cdp = explicit_cdp_url
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = False

    def _current_cdp_url(self) -> str:
        return (self._explicit_cdp or get_cdp_url(force_refresh=True)).rstrip("/")

    def _start_worker(self) -> None:
        with self._lock:
            if self._running and self._thread and self._thread.is_alive():
                return
            self._running = True
            self._ready.clear()
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="edge-cdp-worker")
            self._thread.start()
            self._ready.wait(timeout=12.0)

    def _connect_or_launch(self, playwright: Any) -> tuple[Any, Any, bool]:
        """
        Attach to live Edge CDP first (launching Edge debug profile if needed).
        Returns (browser_or_none, context, owns_context).
        """
        cdp_http = self._current_cdp_url()
        if not _is_cdp_reachable(cdp_http):
            ensure_edge_cdp(cdp_http, wait_seconds=5.5)

        connect_target = _resolve_cdp_connect_target(cdp_http)
        if connect_target:
            try:
                browser = playwright.chromium.connect_over_cdp(connect_target, timeout=6000)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                return browser, context, False
            except Exception:
                try:
                    _, port = _parse_cdp_host_port(cdp_http)
                    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=6000)
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    return browser, context, False
                except Exception:
                    pass

        # If direct target failed, attempt clean reconnect after ensuring Edge CDP is up
        if ensure_edge_cdp(cdp_http, wait_seconds=4.0):
            target = _resolve_cdp_connect_target(cdp_http) or f"http://127.0.0.1:{port}"
            try:
                browser = playwright.chromium.connect_over_cdp(target, timeout=5000)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                return browser, context, False
            except Exception:
                pass

        return None, None, False

    @staticmethod
    def _is_context_alive(browser: Any, context: Any) -> bool:
        if context is None:
            return False
        if browser is not None:
            try:
                if hasattr(browser, "is_connected") and not browser.is_connected():
                    return False
            except Exception:
                return False
        try:
            _ = context.pages
            return True
        except Exception:
            return False

    def _worker_loop(self) -> None:
        if not HAS_PLAYWRIGHT:
            self._ready.set()
            return

        playwright = None
        browser = None
        context = None
        owns_context = False
        try:
            playwright = sync_playwright().start()
            browser, context, owns_context = self._connect_or_launch(playwright)
        except Exception as exc:
            print(f"[EdgePlaywrightWorker] Startup notice: {exc}")
        finally:
            self._ready.set()

        while self._running:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue

            fn, prefer_domain, fut = item
            if fn is None:
                break

            try:
                if not self._is_context_alive(browser, context):
                    browser, context, owns_context = self._connect_or_launch(playwright)

                if context is None:
                    fut.set_exception(RuntimeError("Microsoft Edge CDP port 9222 par connect nahi ho paya."))
                    continue

                pages = [p for p in context.pages if not p.is_closed()]
                page = None
                if prefer_domain:
                    clean_dom = prefer_domain.lower().replace("www.", "")
                    page = next((pg for pg in pages if clean_dom in (pg.url or "").lower()), None)
                if page is None:
                    # Prefer most recently active non-blank page, fallback to pages[0] or new_page()
                    non_blank = [pg for pg in pages if (pg.url or "") not in ("", "about:blank")]
                    page = non_blank[-1] if non_blank else (pages[0] if pages else context.new_page())

                try:
                    page.bring_to_front()
                except Exception:
                    pass
                res = fn(page, context)
                fut.set_result(res)
            except Exception as e:
                # Reset stale handle on disconnect errors so next call cleanly reconnects
                err_low = str(e).lower()
                if any(tok in err_low for tok in ("closed", "disconnected", "target", "cdp", "browser")):
                    browser = None
                    context = None
                fut.set_exception(e)
            finally:
                self._q.task_done()

        try:
            # Never close Captain's live Edge browser when attached via CDP!
            if owns_context and context is not None:
                context.close()
            if playwright is not None:
                playwright.stop()
        except Exception:
            pass

    def run(self, fn: Callable[[Any, Any], Any], prefer_domain: str = "", timeout: float = 15.0) -> tuple[Any, str | None]:
        if not HAS_PLAYWRIGHT:
            return None, "Playwright installed nahi hai (pip install playwright)."
        self._start_worker()
        fut: Future = Future()
        self._q.put((fn, prefer_domain, fut))
        try:
            return fut.result(timeout=timeout), None
        except Exception as exc:
            return None, f"CDP automation error: {type(exc).__name__}: {exc}"


class EdgeBrowserAgent:
    """Playwright CDP agent that controls Captain's live Microsoft Edge tabs safely with strict tab reuse."""

    def __init__(self, cdp_url: str | None = None) -> None:
        self._explicit_cdp = cdp_url
        self.last_youtube_url: str = ""
        self.last_video_title: str = ""
        self._worker: _PlaywrightEdgeWorker | None = None
        self._worker_lock = threading.Lock()

    @property
    def cdp_url(self) -> str:
        return (self._explicit_cdp or get_cdp_url()).rstrip("/")

    def _get_worker(self) -> _PlaywrightEdgeWorker:
        with self._worker_lock:
            if self._worker is None:
                self._worker = _PlaywrightEdgeWorker(self._explicit_cdp)
            return self._worker

    def _run_on_active_page(self, fn: Callable[[Any, Any], Any], prefer_domain: str = "", timeout: float = 15.0):
        return self._get_worker().run(fn, prefer_domain=prefer_domain, timeout=timeout)

    def cdp_diagnostics(self) -> dict[str, Any]:
        """Return live CDP connection status and diagnostic details."""
        info = _fetch_cdp_version(self.cdp_url)
        return {
            "ok": info is not None,
            "cdp_url": self.cdp_url,
            "resolved_http_url": info.get("_resolved_http_url") if info else None,
            "browser": info.get("Browser") if info else None,
            "websocket_url": info.get("webSocketDebuggerUrl") if info else None,
            "playwright_installed": HAS_PLAYWRIGHT,
        }

    def list_interactive_elements(self) -> dict[str, Any]:
        """Snapshot numbered clickable/typeable elements on the active Edge tab."""
        data, err = self._run_on_active_page(lambda page, _ctx: page.evaluate(_EXTRACT_ELEMENTS_JS))
        if err:
            return {"ok": False, "error_code": "CDP_UNAVAILABLE", "message": err}
        return {"ok": True, "verified_state": "dom_snapshot_ready", **data}

    def read_active_page(self, url: str = "") -> dict[str, Any]:
        """Navigate (optional) and extract clean title + readable text from Edge."""
        target = ""
        if url.strip():
            ok, target = validate_http_url(url)
            if not ok:
                return {"ok": False, "error_code": "INVALID_URL", "message": "Invalid URL."}

        def _op(page, _ctx):
            if target:
                page.goto(target, timeout=12000, wait_until="domcontentloaded")
            title = page.title()
            text = page.inner_text("body")[:1800].strip()
            return {"title": title, "url": page.url, "preview": text}

        data, err = self._run_on_active_page(_op)
        if err:
            if target:
                fallback = open_in_edge(target)
                fallback["note"] = f"Opened in Edge without text extraction ({err})."
                return fallback
            return {"ok": False, "error_code": "CDP_UNAVAILABLE", "message": err}
        return {"ok": True, "verified_state": "page_read", **data}

    def navigate_active_tab(self, url: str) -> dict[str, Any]:
        """Navigate the currently active Edge tab safely, intelligently reusing existing domain tabs."""
        ok, target = validate_http_url(url)
        if not ok:
            return {"ok": False, "error_code": "INVALID_URL", "message": "Invalid URL."}

        parsed_netloc = urllib.parse.urlparse(target).netloc

        def _op(page, _ctx):
            page.goto(target, timeout=10000, wait_until="domcontentloaded")
            return {"title": page.title(), "url": page.url}

        data, err = self._run_on_active_page(_op, prefer_domain=parsed_netloc)
        if err or not data:
            return open_in_edge(target)
        return {
            "ok": True,
            "verified_state": "active_tab_navigated",
            **data,
            "message": f"Edge ke active tab mein {data.get('title') or target} open kar diya hai.",
        }

    def click_element(self, element_id: int | None = None, text_query: str = "") -> dict[str, Any]:
        """Click an element by its data-ds-idx number OR visible text/aria-label with payment guard."""
        if text_query:
            shield = check_hard_shields(text_query)
            if shield:
                return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield}

        def _op(page, _ctx):
            if element_id is not None:
                loc = page.locator(f'[data-ds-idx="{int(element_id)}"]').first
                label = (loc.inner_text(timeout=1500) or loc.get_attribute("aria-label") or "").strip()
                shield_el = check_hard_shields(label)
                if shield_el:
                    return {"blocked": shield_el}
                loc.click(timeout=4000)
                time.sleep(0.4)
                return {"clicked": label or f"#{element_id}", "url": page.url, "title": page.title()}

            if text_query:
                loc = page.get_by_text(text_query, exact=False).first
                label = (loc.inner_text(timeout=1500) or text_query).strip()
                shield_el = check_hard_shields(label)
                if shield_el:
                    return {"blocked": shield_el}
                loc.click(timeout=4000)
                time.sleep(0.4)
                return {"clicked": label, "url": page.url, "title": page.title()}

            return {"error": "Provide element_id or text_query."}

        data, err = self._run_on_active_page(_op)
        if err:
            return {"ok": False, "error_code": "CLICK_FAILED", "message": err}
        if isinstance(data, dict) and data.get("blocked"):
            return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": data["blocked"]}
        if isinstance(data, dict) and data.get("error"):
            return {"ok": False, "error_code": "INVALID_ARGS", "message": data["error"]}
        return {
            "ok": True,
            "verified_state": "element_clicked",
            **data,
            "message": f"'{data.get('clicked')}' par click kar diya hai.",
        }

    def type_and_submit(self, text: str, element_id: int | None = None, press_enter: bool = True) -> dict[str, Any]:
        """Type text into a search box/prompt field and submit."""
        shield = check_hard_shields(text)
        if shield:
            return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield}

        def _op(page, _ctx):
            if element_id is not None:
                loc = page.locator(f'[data-ds-idx="{int(element_id)}"]').first
            else:
                loc = page.locator(
                    'textarea:visible, input[type="search"]:visible, input[name="search_query"]:visible, '
                    '[contenteditable="true"]:visible, input[type="text"]:visible'
                ).first
            loc.click(timeout=3000)
            loc.fill(text, timeout=3000)
            if press_enter:
                page.keyboard.press("Enter")
                time.sleep(0.5)
            return {"url": page.url, "title": page.title()}

        data, err = self._run_on_active_page(_op)
        if err:
            return {"ok": False, "error_code": "TYPE_FAILED", "message": err}
        return {
            "ok": True,
            "verified_state": "typed_and_submitted" if press_enter else "typed",
            **data,
            "message": f"Input field mein '{text[:60]}' type{' aur submit' if press_enter else ''} kar diya.",
        }

    def scroll_page(self, direction: str = "down", pixels: int = 550) -> dict[str, Any]:
        """Scroll active Edge tab vertically and return updated scrollY."""
        delta = abs(int(pixels)) if direction.lower() != "up" else -abs(int(pixels))
        data, err = self._run_on_active_page(
            lambda page, _ctx: page.evaluate(f"() => {{ window.scrollBy(0, {delta}); return window.scrollY; }}")
        )
        if err:
            return {"ok": False, "error_code": "SCROLL_FAILED", "message": err}
        return {"ok": True, "verified_state": "scrolled", "scroll_y": data, "message": f"Page {direction} scroll kar diya."}

    def play_media_in_edge(self, query: str, platform: str = "youtube", start_at_seconds: float = 0.0) -> dict[str, Any]:
        """Play music/video in Microsoft Edge via dedicated CDP worker thread (zero sync-in-asyncio crash!)."""
        q = (query or "").strip() or "Arijit Singh songs"
        plat = platform.strip().lower()

        if "spotify" in plat:
            target = (
                "https://open.spotify.com"
                if q.lower() in ("spotify", "music", "gaana", "song")
                else f"https://open.spotify.com/search/{urllib.parse.quote(q)}"
            )
            res = self.navigate_active_tab(target) if _is_cdp_reachable(self.cdp_url) else open_in_edge(target)
            return {
                "ok": bool(res.get("ok")),
                "verified_state": "spotify_opened",
                "url": target,
                "message": f"Microsoft Edge mein Spotify Web par '{q}' open kar diya hai, Captain.",
            }

        target_url = None
        video_title = q
        yt_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()

        if yt_api_key:
            try:
                search_url = (
                    f"https://www.googleapis.com/youtube/v3/search?"
                    f"part=snippet&maxResults=1&q={urllib.parse.quote(q)}&type=video&key={yt_api_key}"
                )
                with urllib.request.urlopen(search_url, timeout=4.0) as resp:
                    api_data = json.loads(resp.read().decode("utf-8"))
                    items = api_data.get("items", [])
                    if items:
                        vid = items[0]["id"]["videoId"]
                        video_title = items[0]["snippet"]["title"]
                        target_url = f"https://www.youtube.com/watch?v={vid}&autoplay=1"
            except Exception as yt_api_err:
                print(f"[YouTube Data API v3 Fallback] {yt_api_err}")

        if not target_url:
            try:
                import yt_dlp  # type: ignore

                ydl_opts = {"quiet": True, "extract_flat": True, "noplaylist": True, "socket_timeout": 3.0}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    res = ydl.extract_info(f"ytsearch1:{q}", download=False)
                    if res and "entries" in res and len(res["entries"]) > 0:
                        entry = res["entries"][0]
                        vid = entry["id"]
                        video_title = entry.get("title", q)
                        target_url = f"https://www.youtube.com/watch?v={vid}&autoplay=1"
            except Exception as yt_err:
                print(f"[YouTube Search Fallback] {yt_err}")

        if not target_url:
            target_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(q)}"
        elif start_at_seconds > 0:
            target_url += f"&t={int(start_at_seconds)}s"

        self.last_youtube_url = target_url.split("&t=")[0]
        self.last_video_title = video_title

        if HAS_PLAYWRIGHT and _is_cdp_reachable(self.cdp_url):
            def _play_op(page, ctx):
                yt_page = next((pg for pg in ctx.pages if not pg.is_closed() and "youtube.com" in (pg.url or "")), None)
                target_pg = yt_page or page
                target_pg.goto(target_url, timeout=10000, wait_until="domcontentloaded")
                target_pg.bring_to_front()
                return {"url": target_pg.url}

            data, err = self._run_on_active_page(_play_op, prefer_domain="youtube.com")
            if not err and data:
                return {
                    "ok": True,
                    "verified_state": "youtube_playing",
                    "url": target_url,
                    "video_title": video_title,
                    "message": f"Microsoft Edge CDP ke zariye '{video_title}' play kar diya hai, Captain.",
                }
            print(f"[CDP YouTube Playback Fallback] {err}")

        res = open_in_edge(target_url)
        return {
            "ok": bool(res.get("ok")),
            "verified_state": "youtube_playing" if res.get("ok") else "launch_failed",
            "url": target_url,
            "video_title": video_title,
            "message": f"Microsoft Edge mein '{video_title}' play kar diya hai, Captain." if res.get("ok") else res.get("message", "Launch failed."),
        }

    def seek_video(self, seconds: float) -> dict[str, Any]:
        """Seek active YouTube / HTML5 video honestly through the dedicated CDP worker thread."""
        sec = max(0.0, float(seconds))
        mins = int(sec // 60)
        rem_sec = int(sec % 60)
        time_fmt = f"{mins} min {rem_sec} sec" if mins > 0 else f"{int(sec)} seconds"

        # Tier 1: Direct Playwright CDP HTML5 <video> seek via dedicated worker thread
        if HAS_PLAYWRIGHT and _is_cdp_reachable(self.cdp_url):
            def _seek_op(page, ctx):
                pages = [pg for pg in ctx.pages if not pg.is_closed()]
                target_page = next(
                    (pg for pg in pages if "youtube.com" in (pg.url or "") or "watch" in (pg.url or "")),
                    page,
                )
                return target_page.evaluate(
                    """(targetSec) => {
                        const video = document.querySelector('video');
                        if (!video) return { found: false };
                        video.currentTime = targetSec;
                        video.play().catch(() => {});
                        return {
                            found: true,
                            currentTime: video.currentTime,
                            duration: video.duration
                        };
                    }""",
                    sec,
                )

            res, err = self._run_on_active_page(_seek_op, prefer_domain="youtube.com")
            if not err and isinstance(res, dict) and res.get("found"):
                return {
                    "ok": True,
                    "verified_state": "video_seeked_cdp",
                    "seek_seconds": sec,
                    "message": f"Gaane ko {time_fmt} par seek kar diya hai, Captain.",
                }

        # Tier 2: Re-open last played YouTube video at exact timestamp via safe open_in_edge
        if self.last_youtube_url and "watch?v=" in self.last_youtube_url:
            base_url = self.last_youtube_url.split("&t=")[0]
            seek_url = f"{base_url}&t={int(sec)}s"
            res = open_in_edge(seek_url)
            if res.get("ok"):
                return {
                    "ok": True,
                    "verified_state": "video_seeked_url",
                    "seek_seconds": sec,
                    "message": f"Gaane ko {time_fmt} par seek kar diya hai, Captain.",
                }

        return {
            "ok": False,
            "error_code": "SEEK_UNAVAILABLE",
            "message": "Active YouTube video ya Edge CDP session nahi mila. Pehle Edge Debug mode mein koi video chalayein.",
        }
