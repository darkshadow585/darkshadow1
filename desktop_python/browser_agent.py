"""
Upgrade #3 (Fixed): Next-Gen Microsoft Edge CDP + Playwright Accessibility/DOM Browser Agent.
=============================================================================================
Fixes applied:
  - Fixed scroll_page JS SyntaxError (`() => { window.scrollBy(...); return window.scrollY; }`)!
  - Removed ALL shell=True subprocess launches (zero command injection, safe with '&' URLs!).
  - Reads CDP_URL dynamically via config.get_cdp_url() AFTER .env is loaded.
  - Honest seek_video(): returns ok=False when all tiers fail (no more lying!) and removed
    dangerous blind '0' keystroke to random foreground apps.
  - Verifies element text against Hard Shields in click_element for both element_id and text_query.
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

from config import get_cdp_url
from windows_tools import check_hard_shields, find_edge_executable, open_in_edge, validate_http_url

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

CDP_URL = get_cdp_url()

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


def _is_cdp_reachable(cdp_url: str | None = None) -> bool:
    target = (cdp_url or get_cdp_url()).rstrip("/")
    try:
        parsed = urllib.parse.urlparse(target)
        host = parsed.hostname or "127.0.0.1"
        if host in ("localhost", "::1"):
            host = "127.0.0.1"
        port = parsed.port or 9222
        with socket.create_connection((host, port), timeout=0.15):
            pass
    except Exception:
        return False

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/version", headers={"Host": "localhost"})
        with urllib.request.urlopen(req, timeout=0.6) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_edge_cdp(cdp_url: str | None = None) -> bool:
    """Return True if Microsoft Edge CDP is reachable; otherwise launch Edge with debugging port."""
    url = (cdp_url or get_cdp_url()).rstrip("/")
    if _is_cdp_reachable(url):
        return True
    try:
        port = url.rsplit(":", 1)[-1]
        user_data = os.getenv(
            "DARKSHADOW_EDGE_PROFILE",
            os.path.expandvars(r"%LOCALAPPDATA%\DarkShadowEdgeProfile"),
        )
        edge_exe = find_edge_executable()
        args = [
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data}",
            "--no-first-run",
        ]
        if edge_exe:
            subprocess.Popen([edge_exe, *args], shell=False)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", "msedge", *args], shell=False)

        for _ in range(3):
            time.sleep(0.35)
            if _is_cdp_reachable(url):
                return True
    except Exception:
        pass
    return False


class _PlaywrightEdgeWorker:
    """Dedicated background thread managing a single persistent, CDP-enabled Microsoft Edge browser."""

    def __init__(self, cdp_url: str) -> None:
        self.cdp_url = cdp_url
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = False

    def _start_worker(self) -> None:
        with self._lock:
            if self._running and self._thread and self._thread.is_alive():
                return
            self._running = True
            self._ready.clear()
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="edge-cdp-worker")
            self._thread.start()
            self._ready.wait(timeout=10.0)

    def _worker_loop(self) -> None:
        if not HAS_PLAYWRIGHT:
            self._ready.set()
            return

        playwright = None
        context = None
        try:
            playwright = sync_playwright().start()
            if _is_cdp_reachable(self.cdp_url):
                browser = playwright.chromium.connect_over_cdp(self.cdp_url, timeout=4000)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
            else:
                profile = os.getenv(
                    "DARKSHADOW_EDGE_PROFILE",
                    os.path.expandvars(r"%LOCALAPPDATA%\DarkShadowEdgeProfile"),
                )
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=profile,
                    channel="msedge",
                    headless=False,
                    no_viewport=True,
                    args=["--remote-debugging-port=9222", "--remote-allow-origins=*"],
                )
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
                if context is None or (hasattr(context, "is_closed") and context.is_closed()):
                    profile = os.getenv(
                        "DARKSHADOW_EDGE_PROFILE",
                        os.path.expandvars(r"%LOCALAPPDATA%\DarkShadowEdgeProfile"),
                    )
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=profile,
                        channel="msedge",
                        headless=False,
                        no_viewport=True,
                        args=["--remote-debugging-port=9222", "--remote-allow-origins=*"],
                    )

                pages = [p for p in context.pages if not p.is_closed()]
                page = None
                if prefer_domain:
                    clean_dom = prefer_domain.lower().replace("www.", "")
                    page = next((pg for pg in pages if clean_dom in (pg.url or "").lower()), None)
                if page is None:
                    # STRICT TAB REUSE: Reuse the active page (pages[0]) to never spawn unwanted tabs!
                    page = pages[0] if pages else context.new_page()

                page.bring_to_front()
                res = fn(page, context)
                fut.set_result(res)
            except Exception as e:
                fut.set_exception(e)
            finally:
                self._q.task_done()

        try:
            if context:
                context.close()
            if playwright:
                playwright.stop()
        except Exception:
            pass

    def run(self, fn: Callable[[Any, Any], Any], prefer_domain: str = "", timeout: float = 12.0) -> tuple[Any, str | None]:
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

    @property
    def cdp_url(self) -> str:
        return (self._explicit_cdp or get_cdp_url()).rstrip("/")

    def _get_worker(self) -> _PlaywrightEdgeWorker:
        if self._worker is None:
            self._worker = _PlaywrightEdgeWorker(self.cdp_url)
        return self._worker

    def _run_on_active_page(self, fn, prefer_domain: str = ""):
        return self._get_worker().run(fn, prefer_domain=prefer_domain)

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

        import urllib.parse
        parsed_netloc = urllib.parse.urlparse(target).netloc

        def _op(page, _ctx):
            page.goto(target, timeout=8000, wait_until="domcontentloaded")
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
        """Fixed: Wrapped JS return inside an arrow function so Playwright evaluates cleanly!"""
        delta = abs(int(pixels)) if direction.lower() != "up" else -abs(int(pixels))
        data, err = self._run_on_active_page(
            lambda page, _ctx: page.evaluate(f"() => {{ window.scrollBy(0, {delta}); return window.scrollY; }}")
        )
        if err:
            return {"ok": False, "error_code": "SCROLL_FAILED", "message": err}
        return {"ok": True, "verified_state": "scrolled", "scroll_y": data, "message": f"Page {direction} scroll kar diya."}

    def play_media_in_edge(self, query: str, platform: str = "youtube", start_at_seconds: float = 0.0) -> dict[str, Any]:
        """Play music/video in Microsoft Edge using CDP or safe shell=False open_in_edge."""
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

        if _is_cdp_reachable(self.cdp_url) and HAS_PLAYWRIGHT:
            try:
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(self.cdp_url, timeout=2500)
                    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                    yt_page = next((pg for pg in ctx.pages if "youtube.com" in pg.url), None)
                    if yt_page:
                        yt_page.goto(target_url, timeout=8000, wait_until="domcontentloaded")
                        yt_page.bring_to_front()
                    else:
                        p_new = ctx.new_page()
                        p_new.goto(target_url, timeout=8000, wait_until="domcontentloaded")
                        p_new.bring_to_front()
                    return {
                        "ok": True,
                        "verified_state": "youtube_playing",
                        "url": target_url,
                        "video_title": video_title,
                        "message": f"Microsoft Edge CDP ke zariye '{video_title}' play kar diya hai, Captain.",
                    }
            except Exception as cdp_err:
                print(f"[CDP YouTube Playback Fallback] {cdp_err}")

        res = open_in_edge(target_url)
        return {
            "ok": bool(res.get("ok")),
            "verified_state": "youtube_playing" if res.get("ok") else "launch_failed",
            "url": target_url,
            "video_title": video_title,
            "message": f"Microsoft Edge mein '{video_title}' play kar diya hai, Captain." if res.get("ok") else res.get("message", "Launch failed."),
        }

    def seek_video(self, seconds: float) -> dict[str, Any]:
        """Seek active YouTube / HTML5 video honestly (never claims ok=True if nothing worked)."""
        sec = max(0.0, float(seconds))
        mins = int(sec // 60)
        rem_sec = int(sec % 60)
        time_fmt = f"{mins} min {rem_sec} sec" if mins > 0 else f"{int(sec)} seconds"

        # Tier 1: Direct Playwright CDP HTML5 <video> seek
        for test_port_url in dict.fromkeys([self.cdp_url, "http://127.0.0.1:9333", "http://127.0.0.1:9222"]):
            if _is_cdp_reachable(test_port_url) and HAS_PLAYWRIGHT:
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.connect_over_cdp(test_port_url, timeout=2500)
                        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                        target_page = next(
                            (pg for pg in ctx.pages if "youtube.com" in pg.url or "watch" in pg.url),
                            ctx.pages[-1] if ctx.pages else None,
                        )
                        if target_page:
                            res = target_page.evaluate(
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
                            if res and res.get("found"):
                                return {
                                    "ok": True,
                                    "verified_state": "video_seeked_cdp",
                                    "seek_seconds": sec,
                                    "message": f"Gaane ko {time_fmt} par seek kar diya hai, Captain.",
                                }
                except Exception as exc:
                    print(f"[CDP Seek Fallback] {exc}")

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
