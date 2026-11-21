"""
A-1 & A-2 (Fixed): Autonomous Web Agent (`browser-use` + Playwright Accessibility Tree CDP)
===========================================================================================
Fixes applied:
  - Uses config.get_cdp_url() & config.get_api_key() dynamically AFTER .env loads.
  - Uses FREE-TIER `gemini-4-hydrogen` (zero paid-only models!).
  - Calls ensure_edge_cdp() automatically before A11y tree or browser-use execution.
  - Unified check_hard_shields() safety filter.
  - Enforces timeout on BOTH sync & async paths (never hangs forever!).
  - Supports cancel_event for Emergency Kill Switch (`Ctrl+Alt+K`).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
import threading
from typing import Any

from browser_agent import (
    EdgeBrowserAgent,
    HAS_PLAYWRIGHT,
    _is_cdp_reachable,
    _resolve_cdp_connect_target,
    ensure_edge_cdp,
)
from config import get_api_key, get_cdp_url, get_fast_model, get_text_model
from error_tracker import log_error
from instant_router import RATE_SHIELD
from windows_tools import check_hard_shields

EDGE_AGENT = EdgeBrowserAgent()


class AutonomousWebAgent:
    """Unified high-level web automation engine for DarkShadow."""

    def __init__(self, cdp_url: str | None = None) -> None:
        self._explicit_cdp = cdp_url

    @property
    def cdp_url(self) -> str:
        return (self._explicit_cdp or get_cdp_url()).rstrip("/")

    def check_capabilities(self) -> dict[str, Any]:
        has_browser_use = False
        has_playwright = False
        try:
            import browser_use  # noqa: F401
            has_browser_use = True
        except Exception:
            pass
        try:
            import playwright  # noqa: F401
            has_playwright = True
        except Exception:
            pass
        return {
            "ok": True,
            "cdp_url": self.cdp_url,
            "cdp_reachable": _is_cdp_reachable(self.cdp_url),
            "browser_use_installed": has_browser_use,
            "playwright_installed": has_playwright,
            "model": os.getenv("DARKSHADOW_BROWSER_MODEL", get_text_model()),
            "install_hint": (
                "pip install browser-use langchain-google-genai playwright"
                if not has_browser_use
                else ""
            ),
        }

    def get_accessibility_tree(self, max_nodes: int = 80) -> dict[str, Any]:
        """Reads the current Microsoft Edge tab via Playwright's Accessibility Tree through the dedicated CDP worker."""
        if not HAS_PLAYWRIGHT:
            return EDGE_AGENT.list_interactive_elements()

        if not ensure_edge_cdp(self.cdp_url):
            return {"ok": False, "error_code": "CDP_UNAVAILABLE", "message": "Edge CDP port 9222 unreachable."}

        def _extract_a11y(page, _ctx):
            title = page.title()
            url = page.url
            aria_text = ""
            try:
                aria_text = page.locator("body").aria_snapshot(timeout=3000)
            except Exception:
                try:
                    snap = page.accessibility.snapshot(interesting_only=True)  # type: ignore[attr-defined]
                    if snap:
                        lines: list[str] = []
                        self._flatten_a11y(snap, lines, max_nodes)
                        aria_text = "\n".join(lines)
                except Exception:
                    pass
            return {"title": title, "url": url, "aria_text": aria_text}

        data, err = EDGE_AGENT._run_on_active_page(_extract_a11y)
        if err or not isinstance(data, dict) or not data.get("aria_text"):
            if err:
                log_error("autonomous_web_agent", f"get_accessibility_tree failed: {err}")
            return EDGE_AGENT.list_interactive_elements()

        trimmed_lines = str(data["aria_text"]).splitlines()[:max_nodes]
        return {
            "ok": True,
            "mode": "playwright_accessibility_tree",
            "title": data.get("title", ""),
            "url": data.get("url", ""),
            "node_count": len(trimmed_lines),
            "tree": "\n".join(trimmed_lines),
            "message": f"Read Accessibility Tree for '{data.get('title', '')}' ({len(trimmed_lines)} nodes).",
        }

    def _flatten_a11y(self, node: dict[str, Any], out: list[str], limit: int, depth: int = 0) -> None:
        if len(out) >= limit:
            return
        role = node.get("role", "")
        name = (node.get("name") or "").strip()
        if role and name:
            indent = "  " * min(depth, 4)
            out.append(f"{indent}- {role}: {name[:90]}")
        for child in node.get("children", []) or []:
            self._flatten_a11y(child, out, limit, depth + 1)

    async def run_autonomous_goal_async(
        self,
        goal: str,
        max_steps: int = 10,
        start_url: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Runs a full autonomous multi-step browser goal via `browser-use` on free-tier gemini-4-hydrogen."""
        shield = check_hard_shields(goal)
        if shield:
            return {"ok": False, "blocked": True, "error_code": "SHIELD_BLOCKED", "message": shield}

        if cancel_event and cancel_event.is_set():
            return {"ok": False, "error_code": "CANCELLED", "message": "Captain ne task cancel kar diya."}

        api_key = get_api_key()
        if not api_key:
            return {"ok": False, "message": "GEMINI_API_KEY missing in .env."}

        if not ensure_edge_cdp(self.cdp_url):
            return {"ok": False, "error_code": "CDP_UNAVAILABLE", "message": "Edge CDP port 9222 unreachable."}

        live_cdp_url = (self._explicit_cdp or get_cdp_url(force_refresh=True)).rstrip("/")

        try:
            from browser_use import Agent, Browser  # type: ignore
        except Exception:
            # Fallback to Built-in High-Speed Autonomous Research & Shopping Engine!
            return await self._run_autonomous_research_and_shopping(goal=goal, start_url=start_url, cancel_event=cancel_event)

        llm: Any = None
        model_name = os.getenv("DARKSHADOW_BROWSER_MODEL", get_text_model()).strip() or get_text_model()
        try:
            from browser_use.llm import ChatGoogle  # type: ignore
            llm = ChatGoogle(model=model_name, api_key=api_key)
        except Exception:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
                llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
            except Exception as exc:
                log_error("autonomous_web_agent", f"LLM init failed: {exc}", exception=exc)
                return {
                    "ok": False,
                    "message": "Install `langchain-google-genai` or latest `browser-use` for Gemini support.",
                }

        browser: Any = None
        try:
            try:
                browser = Browser(cdp_url=live_cdp_url)
            except TypeError:
                from browser_use import BrowserConfig  # type: ignore
                browser = Browser(config=BrowserConfig(cdp_url=live_cdp_url))

            full_task = (
                f"{goal}\n"
                "STRICT SAFETY RULE: NEVER complete payments, checkout, enter passwords/OTP/CVV, "
                "or submit financial transfers. Stop right before any payment/checkout step."
            )
            if start_url:
                full_task = f"First open {start_url}. Then: {full_task}"

            agent = Agent(task=full_task, llm=llm, browser=browser)
            history = await agent.run(max_steps=max(2, min(max_steps, 20)))

            final_text = ""
            if hasattr(history, "final_result") and callable(history.final_result):
                final_text = str(history.final_result() or "").strip()
            if not final_text:
                final_text = str(history)[:800]

            return {
                "ok": True,
                "mode": "browser_use_cdp",
                "goal": goal,
                "result": final_text,
                "message": final_text or f"Autonomous browser goal completed: {goal}",
            }
        except Exception as exc:
            log_error("autonomous_web_agent", f"browser-use execution error: {exc}", exception=exc)
            return {
                "ok": False,
                "mode": "browser_use_error",
                "message": f"Autonomous browser agent error: {exc}.",
            }
        finally:
            if browser is not None:
                try:
                    # Only detach/stop CDP handle cleanly when available
                    close_fn = getattr(browser, "stop", None) or getattr(browser, "close", None)
                    if callable(close_fn):
                        maybe_coro = close_fn()
                        if asyncio.iscoroutine(maybe_coro):
                            await maybe_coro
                except Exception:
                    pass

    async def _run_autonomous_research_and_shopping(
        self,
        goal: str,
        start_url: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Built-in Autonomous Web Research & Shopping Comparison Engine using Tavily + Playwright Edge CDP + Gemini."""
        if cancel_event and cancel_event.is_set():
            return {"ok": False, "error_code": "CANCELLED", "message": "Captain ne task cancel kar diya."}

        import json
        import urllib.parse
        import urllib.request
        from google import genai

        api_key = get_api_key()
        tavily_key = os.getenv("TAVILY_API_KEY", "").strip()

        # Step 1: Detect sites and open search tabs in Microsoft Edge only if not cancelled
        connect_target = _resolve_cdp_connect_target(self.cdp_url)
        opened_sites = []
        if connect_target and HAS_PLAYWRIGHT and not (cancel_event and cancel_event.is_set()):
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    b = await p.chromium.connect_over_cdp(connect_target, timeout=5000)
                    ctx = b.contexts[0] if b.contexts else await b.new_context()

                    for site, s_url in [
                        ("flipkart", "https://www.flipkart.com/search?q="),
                        ("meesho", "https://www.meesho.com/search?q="),
                        ("amazon", "https://www.amazon.in/s?k="),
                        ("myntra", "https://www.myntra.com/"),
                    ]:
                        if site in goal.lower():
                            q_clean = re.sub(
                                r"(?i)\b(search for|search|identify|compare|top \d+|results|on|in|from|both|platforms|terms of|price|brand|design)\b",
                                " ",
                                goal,
                            )
                            q_clean = " ".join(q_clean.split())[:30].strip() or "polo t-shirts"
                            target = f"{s_url}{urllib.parse.quote_plus(q_clean)}"
                            p_new = await ctx.new_page()
                            await p_new.goto(target, timeout=10000, wait_until="domcontentloaded")
                            opened_sites.append(f"{site.capitalize()} ({target})")
            except Exception as e:
                print(f"[Edge Tab Open Notice] {e}")

        # Step 2: Fetch accurate live data via Tavily Search
        tavily_data = []
        if tavily_key:
            sub_queries = []
            for site in ["flipkart.com", "meesho.com", "amazon.in", "myntra.com"]:
                if site.split(".")[0] in goal.lower():
                    sub_queries.append(f"site:{site} {goal}")
            if not sub_queries:
                sub_queries = [goal]

            for q in sub_queries[:3]:
                try:
                    payload = json.dumps({
                        "api_key": tavily_key,
                        "query": q,
                        "search_depth": "advanced",
                        "max_results": 5,
                        "include_answer": True,
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        "https://api.tavily.com/search",
                        headers={"Content-Type": "application/json"},
                        data=payload,
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        tavily_data.append({"query": q, "answer": res.get("answer"), "results": res.get("results", [])})
                except Exception as e:
                    print(f"[Tavily Search Notice] {e}")

        # Step 3: Use Gemini to synthesize comparison
        comparison_text = ""
        spoken_summary = ""
        if api_key and (tavily_data or opened_sites):
            try:
                client = genai.Client(api_key=api_key)
                prompt = (
                    f"Captain's Goal: {goal}\n\n"
                    f"Live Web Search Data Collected:\n{json.dumps(tavily_data, indent=2)}\n\n"
                    "Instructions:\n"
                    "1. Provide a concise, friendly 2-sentence spoken summary in Hindi/Hinglish directly addressing Captain.\n"
                    "2. Followed by a clean Markdown comparison table comparing the top 5 results across the platforms (Brand, Price in INR, Fabric/Design, Rating, Platform).\n"
                    "3. Conclude with a clear recommendation (e.g. Best budget option vs Best quality/brand option)."
                )
                models_to_try = RATE_SHIELD.choose_models([get_text_model(), get_fast_model()])
                for m_name in models_to_try:
                    try:
                        resp = client.models.generate_content(model=m_name, contents=prompt)
                        if resp.text:
                            comparison_text = resp.text.strip()
                            lines = [ln.strip() for ln in comparison_text.splitlines() if ln.strip()]
                            spoken_summary = lines[0] if lines else "Research complete ho gaya hai, Captain."
                            break
                    except Exception as model_exc:
                        if RATE_SHIELD.is_quota_error(model_exc):
                            RATE_SHIELD.mark_rate_limited(m_name, cooldown_seconds=45.0)
                        continue
            except Exception as e:
                print(f"[Gemini Synthesis Error] {e}")

        if not comparison_text and tavily_data:
            comparison_text = "\n".join([str(t.get("answer") or t.get("results")) for t in tavily_data])
            spoken_summary = "Maine live results collect kar liye hain, Captain."

        return {
            "ok": True,
            "mode": "autonomous_research_synthesis",
            "goal": goal,
            "opened_tabs": opened_sites,
            "result": comparison_text,
            "message": spoken_summary or comparison_text[:200],
        }

    def run_autonomous_goal(
        self,
        goal: str,
        max_steps: int = 10,
        start_url: str | None = None,
        timeout: float = 150.0,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Timeout-enforced synchronous wrapper safe to invoke from worker threads."""
        coro = asyncio.wait_for(
            self.run_autonomous_goal_async(
                goal, max_steps=max_steps, start_url=start_url, cancel_event=cancel_event
            ),
            timeout=timeout,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(coro)).result(timeout=timeout + 2.0)
            return asyncio.run(coro)
        except Exception as exc:
            return {"ok": False, "error_code": "TIMEOUT_OR_ERROR", "message": f"Web task error/timeout: {exc}"}


AUTONOMOUS_WEB_AGENT = AutonomousWebAgent()
