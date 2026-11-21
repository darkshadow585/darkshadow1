"""
Upgrade #2 & #5 (Fixed): Consolidated 12-Tool FastMCP Registry, Safety Middleware & Background Job Manager.
===========================================================================================================
Fixes & Upgrades applied:
  1. Eliminated 22-tool bloat & conflicting duplicates -> 12 crisp, non-overlapping tools!
  2. Strict BOOLEAN, INTEGER, NUMBER, and case-insensitive ENUM coercion (fixes `bool("false") == True` bypass!).
  3. Read-only tools (search_web, get_weather) use read_only=True shield so informational queries aren't falsely blocked.
  4. Unified Memory: `memory_action` now syncs directly with `LIVING_MEMORY` (ONE shared memory.db + Mem0 + Core RAM!).
  5. Background Async Job Manager: Long-running tasks (`autonomous_planner`, `autonomous_web_task`) can run in background
     without hitting Live API timeouts, with proactive completion notifications & Emergency Kill Switch!
  6. Added `morning_briefing` routine (Weather + System Health + Upcoming Reminders), `live_vision` (1 FPS stream toggle),
     and `recent_actions` audit inspection.
  7. Fixed `_fetch_weather` `None[:300]` crash and `set_volume` case-sensitivity bug.
  8. 100% Free-Tier Gemini models (`gemini-4-hydrogen` + `gemini-3.1-flash-lite`)!
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from config import get_fast_model, get_text_model
from error_tracker import list_recent_actions, log_action_audit, log_error
from focus_sentinel import FOCUS_SENTINEL
from instant_router import RATE_SHIELD
from knowledge_vault import KNOWLEDGE_VAULT
from living_memory_v3 import LIVING_MEMORY
from mcp_client_hub import MCP_HUB
from security_guard import SECURITY_GUARD

# Lazy loaded engines to ensure near-instant (<1s) startup time
_AUTONOMOUS_WEB_AGENT = None
_PLAYBOOK_ENGINE = None
_REASONING_ENGINE = None
_PLANNER_ENGINE = None
_VISUAL_CLICKER = None

def _get_web_agent():
    global _AUTONOMOUS_WEB_AGENT
    if _AUTONOMOUS_WEB_AGENT is None:
        from autonomous_web_agent import AUTONOMOUS_WEB_AGENT
        _AUTONOMOUS_WEB_AGENT = AUTONOMOUS_WEB_AGENT
    return _AUTONOMOUS_WEB_AGENT

def _get_playbook_engine():
    global _PLAYBOOK_ENGINE
    if _PLAYBOOK_ENGINE is None:
        from playbook_engine import PLAYBOOK_ENGINE
        _PLAYBOOK_ENGINE = PLAYBOOK_ENGINE
    return _PLAYBOOK_ENGINE

def _get_reasoning_engine():
    global _REASONING_ENGINE
    if _REASONING_ENGINE is None:
        from reasoning_engine import REASONING_ENGINE
        _REASONING_ENGINE = REASONING_ENGINE
    return _REASONING_ENGINE

def _get_planner_engine():
    global _PLANNER_ENGINE
    if _PLANNER_ENGINE is None:
        try:
            from reasoning_engine_v2 import REASONING_ENGINE_V2
            _PLANNER_ENGINE = REASONING_ENGINE_V2
        except Exception:
            _PLANNER_ENGINE = _get_reasoning_engine()
    return _PLANNER_ENGINE

def _get_visual_clicker():
    global _VISUAL_CLICKER
    if _VISUAL_CLICKER is None:
        from visual_clicker import VISUAL_CLICKER
        _VISUAL_CLICKER = VISUAL_CLICKER
    return _VISUAL_CLICKER
from windows_tools import (
    capture_monitor_jpeg_bytes,
    check_hard_shields,
    close_application,
    control_active_window,
    control_media_key,
    get_active_window_title,
    get_system_health,
    manage_clipboard,
    open_allowlisted_app,
    search_local_files,
    send_whatsapp_message,
    set_monitor_brightness,
    set_system_volume,
    type_unicode_text,
)
from windows_uia_agent import WINDOWS_UIA_AGENT

try:
    from google.genai import types
    HAS_GENAI = True
except Exception:
    HAS_GENAI = False

READ_ONLY_TOOLS = {"web_search_and_weather", "knowledge_vault"}


def _coerce_bool(val: Any) -> bool:
    """Strictly parse booleans so string 'false' NEVER bypasses 2-step security confirmations!"""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("true", "1", "yes", "y", "haan", "ha"):
            return True
        if low in ("false", "0", "no", "n", "nahi", ""):
            return False
    return False


def _redact_sensitive_args(args: dict[str, Any]) -> dict[str, Any]:
    return {
        k: ("***" if any(s in k.lower() for s in ("passphrase", "secret", "password", "token", "api_key")) else v)
        for k, v in (args or {}).items()
    }


class FastMCP:
    """Standardized MCP & Gemini Tool Registry with Schema Validation."""

    def __init__(self) -> None:
        self.registry: dict[str, dict[str, Any]] = {}

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
    ) -> Callable:
        def decorator(func: Callable) -> Callable:
            self.registry[name] = {
                "name": name,
                "description": description,
                "parameters": parameters or {"type": "OBJECT", "properties": {}},
                "handler": func,
            }
            return func

        return decorator

    def get_gemini_declarations(self, non_blocking: bool = True) -> list[Any]:
        if not HAS_GENAI:
            return []

        decls = []
        for name, meta in self.registry.items():
            props = {}
            raw_props = meta["parameters"].get("properties", {})
            required = meta["parameters"].get("required", [])

            for p_name, p_meta in raw_props.items():
                p_type_str = str(p_meta.get("type", "STRING")).upper()
                p_type = getattr(types.Type, p_type_str, types.Type.STRING)
                schema_kwargs: dict[str, Any] = {
                    "type": p_type,
                    "description": p_meta.get("description", p_name),
                }
                if "enum" in p_meta and p_meta["enum"]:
                    schema_kwargs["enum"] = list(p_meta["enum"])
                props[p_name] = types.Schema(**schema_kwargs)

            schema = types.Schema(
                type=types.Type.OBJECT,
                properties=props,
                required=required if required else None,
            )

            decl_kwargs: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "parameters": schema,
            }
            if non_blocking and hasattr(types, "Behavior"):
                decl_kwargs["behavior"] = types.Behavior.NON_BLOCKING

            decls.append(types.FunctionDeclaration(**decl_kwargs))
        return decls

    def get_mcp_manifest(self) -> dict[str, Any]:
        return {
            "protocolVersion": "2024-11-05",
            "tools": [
                {
                    "name": name,
                    "description": meta["description"],
                    "inputSchema": meta["parameters"],
                }
                for name, meta in self.registry.items()
            ],
        }


class MCPToolRegistry:
    """Unified 12-Tool DarkShadow Executor with Safety Middleware, Audit Log & Background Jobs."""

    def __init__(
        self,
        genai_client: Any = None,
        memory_engine: Any = None,
        on_standby_change: Callable[[bool, str], None] | None = None,
        on_close_app: Callable[[], None] | None = None,
        on_persona_change: Callable[[str], None] | None = None,
        on_live_vision_change: Callable[[bool, int], None] | None = None,
        on_job_complete: Callable[[str], None] | None = None,
    ) -> None:
        self._client = genai_client
        self._memory = memory_engine
        if memory_engine is not None:
            LIVING_MEMORY.attach_semantic_engine(memory_engine)
        self._on_standby_change = on_standby_change
        self._on_close_app = on_close_app
        self._on_persona_change = on_persona_change
        self._on_live_vision_change = on_live_vision_change
        self._on_job_complete = on_job_complete

        self._browser = None
        self.fast_mcp = FastMCP()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()
        self._cancel_event = threading.Event()

        self._register_all_tools()

    @property
    def browser(self):
        if self._browser is None:
            from browser_agent import EdgeBrowserAgent
            self._browser = EdgeBrowserAgent()
        return self._browser

    def set_job_complete_callback(self, callback: Callable[[str], None]) -> None:
        self._on_job_complete = callback

    def set_live_vision_callback(self, callback: Callable[[bool, int], None]) -> None:
        self._on_live_vision_change = callback

    def cancel_all_background_jobs(self) -> dict[str, Any]:
        """Emergency Kill Switch: signals all running autonomous web/planner jobs to stop."""
        self._cancel_event.set()
        try:
            _get_planner_engine().cancel_active()
        except Exception:
            pass
        try:
            _get_reasoning_engine().cancel_active()
        except Exception:
            pass
        with self._jobs_lock:
            running = [jid for jid, info in self._jobs.items() if info.get("status") == "running"]
            for jid in running:
                self._jobs[jid]["status"] = "cancelled"
        return {
            "ok": True,
            "verified_state": "jobs_cancelled",
            "cancelled_count": len(running),
            "message": f"Emergency stop active — {len(running)} background task(s) rok diye gaye, Captain.",
        }

    def _spawn_background_job(self, label: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        self._cancel_event.clear()
        job_id = f"job-{uuid.uuid4().hex[:6]}"
        with self._jobs_lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "label": label,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "result": None,
            }

        def _runner() -> None:
            try:
                res = fn()
                status = "needs_approval" if res.get("needs_approval") else ("completed" if res.get("ok") else "failed")
            except Exception as exc:
                res = {"ok": False, "message": f"Background job error: {exc}"}
                status = "failed"
            with self._jobs_lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = status
                    self._jobs[job_id]["result"] = res
            try:
                from windows_tools import send_windows_toast
                send_windows_toast(
                    f"DarkShadow: {label[:25]}",
                    str(res.get("message", "Task complete!"))[:120],
                )
            except Exception:
                pass

            try:
                from living_memory_v3 import LIVING_MEMORY
                if res.get("result"):
                    LIVING_MEMORY.remember(f"Completed '{label}': {str(res.get('result'))[:600]}")
                elif res.get("message"):
                    LIVING_MEMORY.remember(f"Completed '{label}': {str(res.get('message'))[:400]}")
            except Exception:
                pass

            print(f"\n[Background Task Finished] {label} ({status}): {res.get('message', '')[:200]}")

            if self._on_job_complete:
                msg = str(res.get("message", ""))[:320]
                tid = res.get("thread_id", "")
                extra = f" (Approval thread_id: {tid})" if res.get("needs_approval") and tid else ""
                self._on_job_complete(f"Background task '{label}' ({status}): {msg}{extra}")

        threading.Thread(target=_runner, daemon=True, name=f"ds-{job_id}").start()
        return {
            "ok": True,
            "verified_state": "job_started_in_background",
            "job_id": job_id,
            "message": f"Captain, '{label}' background mein start kar diya hai (ID: {job_id}). Complete hote hi main bata doonga!",
        }

    def _register_all_tools(self) -> None:
        m = self.fast_mcp

        # 1. Application & Window Control (Consolidated — ZERO duplicate open_app/close_app!)
        @m.tool(
            name="app_and_window",
            description=(
                "Open or close allowlisted Windows 11 apps/settings (edge, vscode, whatsapp, notepad, calc, "
                "terminal, bluetooth, settings, wifi, active, darkshadow) OR control active window "
                "(minimize, maximize, restore, show_desktop, lock_pc — lock_pc requires confirmed=true)."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["open", "close", "minimize", "maximize", "restore", "show_desktop", "lock_pc"],
                        "description": "App or window action",
                    },
                    "app_name": {
                        "type": "STRING",
                        "description": "App name for open/close (e.g. edge, vscode, whatsapp, notepad, calc, active, darkshadow)",
                    },
                    "confirmed": {
                        "type": "BOOLEAN",
                        "description": "Must be true ONLY after Captain explicitly confirms lock_pc",
                    },
                },
                "required": ["action"],
            },
        )
        def tool_app_and_window(action: str, app_name: str = "", confirmed: bool = False) -> dict[str, Any]:
            if action == "open":
                return open_allowlisted_app(app_name)
            if action == "close":
                return close_application(app_name or "active", self._on_close_app)
            if action == "lock_pc" and not confirmed:
                return {
                    "ok": False,
                    "needs_confirmation": True,
                    "message": "Captain, kya aap sure hain ki main Windows workstation lock kar doon? Confirm kijiye.",
                }
            return control_active_window(action)

        # 2. Unified Media, Seek, Volume & Brightness Control (Consolidated — ZERO duplicates!)
        @m.tool(
            name="media_and_device",
            description=(
                "Play songs/videos in Edge (YouTube or Spotify Web), seek video timestamp, control playback "
                "(pause, play, resume, play_pause, next, prev, stop, now_playing), adjust Windows volume "
                "(set_volume, volume_up, volume_down, mute, unmute), or set monitor brightness (set_brightness)."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": [
                            "play_music", "seek", "pause", "play", "resume", "play_pause",
                            "next", "prev", "stop", "now_playing",
                            "set_volume", "volume_up", "volume_down", "mute", "unmute",
                            "set_brightness",
                        ],
                        "description": "Media, audio, or brightness action",
                    },
                    "query": {"type": "STRING", "description": "Song, artist, or video query for play_music"},
                    "platform": {
                        "type": "STRING",
                        "enum": ["youtube", "spotify_web"],
                        "description": "Target platform inside Microsoft Edge",
                    },
                    "seconds": {"type": "NUMBER", "description": "Timestamp in seconds for seek or start_at"},
                    "level": {"type": "INTEGER", "description": "Volume or brightness percentage (0-100), or volume step"},
                },
                "required": ["action"],
            },
        )
        def tool_media_and_device(
            action: str,
            query: str = "",
            platform: str = "youtube",
            seconds: float = 0.0,
            level: int | None = None,
        ) -> dict[str, Any]:
            if action == "play_music":
                target_q = (query or "").strip() or "Arijit Singh songs"
                return self.browser.play_media_in_edge(target_q, platform=platform, start_at_seconds=float(seconds or 0.0))
            if action == "seek":
                return self.browser.seek_video(float(seconds or 0.0))
            if action in ("pause", "play", "resume", "play_pause", "next", "prev", "stop", "now_playing"):
                return control_media_key(action)
            if action == "set_volume":
                if level is None:
                    return {"ok": False, "error_code": "INVALID_ARGS", "message": "Volume level (0-100) batayein."}
                return set_system_volume(level=level)
            if action == "volume_up":
                return set_system_volume(direction="up", amount=level if (level is not None and level > 0) else 10)
            if action == "volume_down":
                return set_system_volume(direction="down", amount=level if (level is not None and level > 0) else 10)
            if action == "mute":
                return set_system_volume(direction="mute", mute=True)
            if action == "unmute":
                return set_system_volume(direction="unmute", mute=False)
            if action == "set_brightness":
                if level is None:
                    return {"ok": False, "error_code": "INVALID_ARGS", "message": "Brightness level (0-100) batayein."}
                return set_monitor_brightness(level)
            return {"ok": False, "error_code": "INVALID_ACTION", "message": f"Unknown action '{action}'."}

        # 3. Live Internet Search & Real-Time Weather (Read-Only)
        @m.tool(
            name="web_search_and_weather",
            description="Search the live internet (Tavily AI Search) for news/facts OR fetch real-time live weather for Prayagraj or any city.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["search_web", "get_weather"],
                        "description": "search_web or get_weather",
                    },
                    "query": {"type": "STRING", "description": "Search query or city name (default city: Prayagraj)"},
                },
                "required": ["action"],
            },
        )
        def tool_web_search_and_weather(action: str, query: str = "") -> dict[str, Any]:
            if action == "get_weather":
                return self._fetch_weather(query.strip() or "Prayagraj")
            if not query.strip():
                return {"ok": False, "error_code": "INVALID_ARGS", "message": "Search query required."}
            return self._tavily_search(query.strip())

        # 4. Microsoft Edge Browser Automation (CDP DOM + Accessibility Tree)
        @m.tool(
            name="browser_interact",
            description=(
                "Control Captain's live Microsoft Edge browser directly (reuses existing tabs). "
                "Supports open_url, search_google, read_page, list_elements, a11y_tree, click, type_and_submit, and scroll."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": [
                            "open_url", "search_google", "read_page", "list_elements",
                            "a11y_tree", "click", "type_and_submit", "scroll",
                        ],
                        "description": "Browser automation action",
                    },
                    "query_or_url": {
                        "type": "STRING",
                        "description": "URL, Google search query, text to type, or visible button/link text to click",
                    },
                    "element_id": {"type": "INTEGER", "description": "Numeric element ID from list_elements"},
                    "direction": {"type": "STRING", "enum": ["down", "up"], "description": "Scroll direction"},
                },
                "required": ["action"],
            },
        )
        def tool_browser_interact(
            action: str,
            query_or_url: str = "",
            element_id: int | None = None,
            direction: str = "down",
        ) -> dict[str, Any]:
            if action == "search_google":
                if not query_or_url.strip():
                    return {"ok": False, "error_code": "INVALID_ARGS", "message": "Search query required."}
                url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query_or_url.strip())}"
                return self.browser.navigate_active_tab(url)
            if action == "open_url":
                if not query_or_url.strip():
                    return {"ok": False, "error_code": "INVALID_ARGS", "message": "URL required."}
                target = query_or_url.strip()
                if target.lower().startswith(("instagram:", "instagram://")):
                    return open_allowlisted_app("instagram")
                if target.lower().startswith(("whatsapp:", "whatsapp://")):
                    return open_allowlisted_app("whatsapp")
                if target.lower().startswith(("spotify:", "spotify://")):
                    return open_allowlisted_app("spotify")
                return self.browser.navigate_active_tab(target)
            if action == "read_page":
                return self.browser.read_active_page(query_or_url.strip())
            if action == "list_elements":
                return self.browser.list_interactive_elements()
            if action == "a11y_tree":
                return _get_web_agent().get_accessibility_tree()
            if action == "click":
                return self.browser.click_element(element_id=element_id, text_query=query_or_url.strip())
            if action == "type_and_submit":
                if not query_or_url.strip():
                    return {"ok": False, "error_code": "INVALID_ARGS", "message": "Text to type is required."}
                return self.browser.type_and_submit(text=query_or_url.strip(), element_id=element_id, press_enter=True)
            if action == "scroll":
                return self.browser.scroll_page(direction=direction)
            return {"ok": False, "error_code": "INVALID_ACTION", "message": f"Unsupported browser action '{action}'."}

        # 5. WhatsApp Messaging with 2-Step Confirmation Gate
        @m.tool(
            name="whatsapp_send",
            description=(
                "Draft a WhatsApp message to a contact name or phone number. "
                "IMPORTANT: Call first with confirmed=false to preview and ask Captain for confirmation, "
                "then call with confirmed=true ONLY after Captain approves."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "recipient": {"type": "STRING", "description": "Contact name or phone number"},
                    "message": {"type": "STRING", "description": "Message text to send"},
                    "confirmed": {"type": "BOOLEAN", "description": "True ONLY after Captain confirms"},
                },
                "required": ["recipient", "message"],
            },
        )
        def tool_whatsapp_send(recipient: str, message: str, confirmed: bool = False) -> dict[str, Any]:
            if not confirmed:
                return {
                    "ok": False,
                    "needs_confirmation": True,
                    "preview": {"recipient": recipient, "message": message},
                    "message": f"Captain se confirm kijiye: Kya '{recipient}' ko '{message}' WhatsApp par bhej doon?",
                }
            return send_whatsapp_message(recipient, message)

        # 6. Screen Vision + Set-of-Marks Visual Clicking (On-Demand Snapshot, 1 FPS Watch, Omni-App Click)
        @m.tool(
            name="screen_vision",
            description=(
                "Inspect Captain's monitor screen (action='snapshot'), click ANY visible button/icon across "
                "Electron/web/native apps using Set-of-Marks visual tags (action='visual_click'), OR toggle "
                "real-time 1 FPS Live Screen Watch mode (action='start_watch' / 'stop_watch'). Never accesses webcam."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["snapshot", "visual_click", "start_watch", "stop_watch"],
                        "description": "snapshot, visual_click (Set-of-Marks click), start_watch, or stop_watch",
                    },
                    "question": {"type": "STRING", "description": "Question about screen (snapshot) OR target button/icon description (visual_click)"},
                    "window_title": {"type": "STRING", "description": "Optional target window title for visual_click"},
                    "double_click": {"type": "BOOLEAN", "description": "True to double-click during visual_click"},
                    "dry_run": {"type": "BOOLEAN", "description": "True to only locate coordinates without clicking"},
                    "duration_seconds": {"type": "INTEGER", "description": "Auto-stop timer for start_watch (15-120s, default 60)"},
                },
                "required": ["action"],
            },
        )
        def tool_screen_vision(
            action: str,
            question: str = "",
            window_title: str = "",
            double_click: bool = False,
            dry_run: bool = False,
            duration_seconds: int = 60,
        ) -> dict[str, Any]:
            if action == "visual_click":
                return _get_visual_clicker().visual_click(
                    target_description=question,
                    window_title=window_title.strip() or None,
                    double_click=double_click,
                    dry_run=dry_run,
                )
            if action == "start_watch":
                dur = max(15, min(120, int(duration_seconds or 60)))
                if self._on_live_vision_change:
                    self._on_live_vision_change(True, dur)
                    return {
                        "ok": True,
                        "verified_state": "live_vision_started",
                        "duration_seconds": dur,
                        "message": f"Captain, main ab agle {dur} seconds tak aapki monitor screen live dekh raha hoon.",
                    }
                return {"ok": False, "message": "Live screen stream callback configured nahi hai."}
            if action == "stop_watch":
                if self._on_live_vision_change:
                    self._on_live_vision_change(False, 0)
                return {"ok": True, "verified_state": "live_vision_stopped", "message": "Live screen watch band kar diya hai."}

            jpeg = capture_monitor_jpeg_bytes()
            if not jpeg or self._client is None:
                return {"ok": False, "error_code": "VISION_UNAVAILABLE", "message": "Screen capture ya Gemini client unavailable hai."}
            active_win = get_active_window_title()
            models_to_try = RATE_SHIELD.choose_models([get_text_model(), get_fast_model()])
            last_err = None
            for model_name in models_to_try:
                try:
                    resp = self._client.models.generate_content(
                        model=model_name,
                        contents=[
                            types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                            (
                                f"Active window: '{active_win}'. Captain asks about his desktop screen: "
                                f"{question or 'Describe what is currently on the screen concisely.'} "
                                "Answer accurately in natural Hindi/Hinglish (1-3 sentences)."
                            ),
                        ],
                    )
                    answer = (resp.text or "").strip()
                    if answer:
                        return {
                            "ok": True,
                            "verified_state": "screen_analyzed",
                            "active_window": active_win,
                            "model_used": model_name,
                            "analysis": answer,
                        }
                except Exception as exc:
                    last_err = exc
                    if RATE_SHIELD.is_quota_error(exc):
                        RATE_SHIELD.mark_rate_limited(model_name, cooldown_seconds=45.0)
                    continue
            return {"ok": False, "error_code": "VISION_API_ERROR", "message": f"Screen vision busy: {type(last_err).__name__}"}

        # 7. Local File Search & Clipboard/Typing
        @m.tool(
            name="files_and_clipboard",
            description="Search Downloads/Documents/Desktop for files, read/set clipboard, or type Unicode Hindi/English text.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["search_files", "get_clipboard", "set_clipboard", "type_text"],
                        "description": "File or clipboard/typing action",
                    },
                    "text": {"type": "STRING", "description": "Filename query, clipboard text, or text to type"},
                    "folder": {
                        "type": "STRING",
                        "enum": ["downloads", "documents", "desktop"],
                        "description": "Optional folder for search_files",
                    },
                },
                "required": ["action"],
            },
        )
        def tool_files_and_clipboard(action: str, text: str = "", folder: str = "") -> dict[str, Any]:
            if action == "search_files":
                return search_local_files(text, folder)
            if action == "get_clipboard":
                return manage_clipboard("get")
            if action == "set_clipboard":
                return manage_clipboard("set", text)
            if action == "type_text":
                return type_unicode_text(text)
            return {"ok": False, "error_code": "INVALID_ACTION", "message": f"Unsupported action '{action}'."}

        # 8. Unified Living Memory, Core RAM Blocks & Reminders (ZERO split-brain!)
        @m.tool(
            name="memory_control",
            description=(
                "Unified Memory Hub: save/recall long-term preferences & notes (synced across SQLite + Mem0), "
                "schedule reminders, OR read/update always-on Core RAM blocks (captain_profile, preferences, active_projects)."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["save", "recall", "remind", "read_blocks", "append_block", "replace_block", "status"],
                        "description": "Memory operation",
                    },
                    "content": {"type": "STRING", "description": "Fact, query, reminder message, or block update"},
                    "kind": {"type": "STRING", "enum": ["preference", "note"], "description": "Category for save"},
                    "block": {"type": "STRING", "description": "Core RAM block name for append_block/replace_block"},
                    "old_text": {"type": "STRING", "description": "Substring to replace in replace_block"},
                    "minutes_from_now": {"type": "INTEGER", "description": "Delay in minutes for remind"},
                },
                "required": ["action"],
            },
        )
        def tool_memory_control(
            action: str,
            content: str = "",
            kind: str = "preference",
            block: str = "preferences",
            old_text: str = "",
            minutes_from_now: int = 10,
        ) -> dict[str, Any]:
            if action == "status":
                return LIVING_MEMORY.status()
            if action == "read_blocks":
                return {"ok": True, "blocks": LIVING_MEMORY.get_core_blocks()}
            if action == "append_block":
                return LIVING_MEMORY.core_memory_append(block, content)
            if action == "replace_block":
                return LIVING_MEMORY.core_memory_replace(block, old_text, content)
            if action == "save":
                return LIVING_MEMORY.remember(content, category=kind)
            if action == "recall":
                return LIVING_MEMORY.recall(content, limit=5)
            if action == "remind":
                mins = max(1, int(minutes_from_now or 10))
                due = datetime.now(timezone.utc) + timedelta(minutes=mins)
                ok, msg = LIVING_MEMORY.semantic.add_reminder(content, due)
                return {"ok": ok, "verified_state": "reminder_scheduled" if ok else "reminder_rejected", "message": msg}
            return {"ok": False, "error_code": "INVALID_ACTION", "message": f"Unknown memory action '{action}'."}

        # 9. System Info, Standby, Dynamic Personas, Routines, Action Audit & Passphrase Security Guard
        @m.tool(
            name="system_control",
            description=(
                "Read time/date, PC CPU/RAM/Battery health, recent action audit log, toggle sleep/standby, "
                "switch persona (default, bhojpuri, witty, beedu), run routines (morning_briefing, study, focus, chill), "
                "OR manage Voice/Passphrase Security Guard (set_passphrase, unlock_guard, lock_guard, disable_guard, guard_status)."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": [
                            "time", "health", "standby", "wake", "set_persona", "run_routine", "recent_actions",
                            "set_passphrase", "unlock_guard", "lock_guard", "disable_guard", "guard_status",
                        ],
                        "description": "System, mode, or security guard action",
                    },
                    "persona": {
                        "type": "STRING",
                        "enum": ["default", "bhojpuri", "witty", "beedu"],
                        "description": "Target persona when action is set_persona",
                    },
                    "routine": {
                        "type": "STRING",
                        "enum": ["morning_briefing", "study", "focus", "chill"],
                        "description": "Pre-built routine macro",
                    },
                    "passphrase": {"type": "STRING", "description": "Passphrase for unlock_guard, set_passphrase, or disable_guard"},
                    "current_passphrase": {"type": "STRING", "description": "Existing passphrase when changing passphrase"},
                },
                "required": ["action"],
            },
        )
        def tool_system_control(
            action: str,
            persona: str = "default",
            routine: str = "study",
            passphrase: str = "",
            current_passphrase: str = "",
        ) -> dict[str, Any]:
            if action == "guard_status":
                return SECURITY_GUARD.status()
            if action == "set_passphrase":
                return SECURITY_GUARD.set_passphrase(passphrase, current_passphrase=current_passphrase)
            if action == "unlock_guard":
                return SECURITY_GUARD.unlock(passphrase)
            if action == "lock_guard":
                return SECURITY_GUARD.lock_now()
            if action == "disable_guard":
                return SECURITY_GUARD.disable(passphrase or current_passphrase)
            if action == "time":
                now = datetime.now()
                return {
                    "ok": True,
                    "verified_state": "time_read",
                    "time": now.strftime("%I:%M %p"),
                    "date": now.strftime("%A, %d %B %Y"),
                    "message": f"Abhi {now.strftime('%I:%M %p')} baje hain, {now.strftime('%A, %d %B %Y')}.",
                }
            if action == "health":
                return get_system_health()
            if action == "recent_actions":
                acts = list_recent_actions(limit=10)
                return {"ok": True, "count": len(acts), "actions": acts}
            if action == "standby":
                if self._on_standby_change:
                    self._on_standby_change(True, "Captain requested standby")
                return {
                    "ok": True,
                    "verified_state": "standby_enabled",
                    "message": "DarkShadow standby mode mein chala gaya. 'Hey DarkShadow' bolkar wapas jaga sakte hain.",
                }
            if action == "wake":
                if self._on_standby_change:
                    self._on_standby_change(False, "Captain woke DarkShadow")
                return {"ok": True, "verified_state": "awake", "message": "DarkShadow active aur listening hai."}
            if action == "set_persona":
                if self._on_persona_change:
                    self._on_persona_change(persona)
                return {
                    "ok": True,
                    "verified_state": "persona_switched",
                    "persona": persona,
                    "message": f"Persona '{persona}' mode activate kar diya hai, Captain.",
                }
            if action == "run_routine":
                if routine == "morning_briefing":
                    now = datetime.now()
                    weather = self._fetch_weather("Prayagraj")
                    health = get_system_health()
                    reminders = LIVING_MEMORY.semantic.list_upcoming_reminders(limit=5)
                    rem_list = [f"{r.message} ({r.due_at[:16]})" for r in reminders]
                    return {
                        "ok": True,
                        "verified_state": "morning_briefing_ready",
                        "time": now.strftime("%I:%M %p, %A %d %B"),
                        "weather": weather.get("message", "Weather unavailable"),
                        "system_health": health,
                        "upcoming_reminders": rem_list,
                        "message": (
                            f"Good morning Captain! Abhi {now.strftime('%I:%M %p')} baje hain. "
                            f"{weather.get('message', '')} "
                            f"Pending reminders: {len(rem_list)}."
                        ),
                    }
                steps = []
                if routine == "study":
                    steps.append(open_allowlisted_app("vscode"))
                    steps.append(set_monitor_brightness(65))
                    steps.append(self.browser.play_media_in_edge("Lofi Chill Beats for coding", platform="youtube"))
                elif routine == "focus":
                    steps.append(set_system_volume(direction="mute", mute=True))
                    steps.append(set_monitor_brightness(60))
                    steps.append(FOCUS_SENTINEL.start_focus(minutes=25, label="Focus Routine"))
                elif routine == "chill":
                    steps.append(set_monitor_brightness(50))
                    steps.append(self.browser.play_media_in_edge("Arijit Singh best songs", platform="spotify_web"))
                return {
                    "ok": True,
                    "verified_state": f"routine_{routine}_executed",
                    "steps_completed": len([s for s in steps if s.get("ok")]),
                    "details": steps,
                }
            return {"ok": False, "error_code": "INVALID_ACTION", "message": f"Unknown system action '{action}'."}

        # 10. Native Windows 11 UI Automation (UIA Accessibility Tree)
        @m.tool(
            name="windows_ui_automation",
            description="Control native Windows 11 desktop apps via the UIA Accessibility Tree (list_windows, focus, inspect, click, type, status).",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["list_windows", "focus", "inspect", "click", "type", "status"],
                        "description": "Windows UIA action",
                    },
                    "window_title": {"type": "STRING", "description": "Partial or full Windows app title"},
                    "index": {"type": "INTEGER", "description": "Element index from inspect"},
                    "element_name": {"type": "STRING", "description": "Accessible button/input name"},
                    "text": {"type": "STRING", "description": "Text to type"},
                    "press_enter": {"type": "BOOLEAN", "description": "Press Enter after typing"},
                },
                "required": ["action"],
            },
        )
        def tool_windows_ui_automation(
            action: str,
            window_title: str = "",
            index: int | None = None,
            element_name: str = "",
            text: str = "",
            press_enter: bool = False,
        ) -> dict[str, Any]:
            wt = window_title.strip() or None
            if action == "status":
                return WINDOWS_UIA_AGENT.backend_info()
            if action == "list_windows":
                return WINDOWS_UIA_AGENT.list_open_windows()
            if action == "focus":
                return WINDOWS_UIA_AGENT.focus_window(window_title)
            if action == "inspect":
                return WINDOWS_UIA_AGENT.inspect_window(window_title=wt)
            if action == "click":
                return WINDOWS_UIA_AGENT.click_element(index=index, name=element_name or None, window_title=wt)
            if action == "type":
                return WINDOWS_UIA_AGENT.type_into_element(
                    text=text, index=index, name=element_name or None, press_enter=press_enter, window_title=wt
                )
            return {"ok": False, "message": f"Unknown UIA action '{action}'."}

        # 11. Autonomous Multi-Step Agent (LangGraph ReAct + browser-use + Async Background Jobs + Kill Switch)
        @m.tool(
            name="autonomous_agent",
            description=(
                "Run complex multi-step desktop or web goals asynchronously in the background without blocking voice! "
                "Supports run_planner (LangGraph ReAct), run_web_agent (browser-use in Edge), resume_approve/resume_cancel, "
                "job_status, cancel_all (Emergency Stop), and status."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": [
                            "run_planner", "run_web_agent", "resume_approve",
                            "resume_cancel", "job_status", "cancel_all", "status",
                        ],
                        "description": "Autonomous agent action",
                    },
                    "goal": {"type": "STRING", "description": "Complex multi-step goal description"},
                    "start_url": {"type": "STRING", "description": "Optional starting URL for run_web_agent"},
                    "thread_id": {"type": "STRING", "description": "Thread ID for resume_approve/resume_cancel"},
                    "job_id": {"type": "STRING", "description": "Optional job_id for job_status"},
                    "run_in_background": {"type": "BOOLEAN", "description": "Default true so voice stays instant!"},
                },
                "required": ["action"],
            },
        )
        def tool_autonomous_agent(
            action: str,
            goal: str = "",
            start_url: str = "",
            thread_id: str = "",
            job_id: str = "",
            run_in_background: bool = True,
        ) -> dict[str, Any]:
            if action == "status":
                return {
                    "ok": True,
                    "reasoning": _get_reasoning_engine().status(),
                    "web_agent": _get_web_agent().check_capabilities(),
                }
            if action == "cancel_all":
                return self.cancel_all_background_jobs()
            if action == "job_status":
                with self._jobs_lock:
                    if job_id and job_id in self._jobs:
                        return {"ok": True, "job": self._jobs[job_id]}
                    return {"ok": True, "jobs": list(self._jobs.values())[-5:]}
            if action == "resume_approve":
                return _get_reasoning_engine().resume_approval(thread_id, approved=True)
            if action == "resume_cancel":
                return _get_reasoning_engine().resume_approval(thread_id, approved=False)
            if action == "run_planner":
                if not goal.strip():
                    return {"ok": False, "message": "Goal is required."}
                if run_in_background:
                    return self._spawn_background_job(
                        f"Planner: {goal[:50]}",
                        lambda: _get_planner_engine().run_goal(goal.strip(), thread_id=thread_id or None),
                    )
                return _get_planner_engine().run_goal(goal.strip(), thread_id=thread_id or None)
            if action == "run_web_agent":
                if not goal.strip():
                    return {"ok": False, "message": "Goal is required."}
                if run_in_background:
                    return self._spawn_background_job(
                        f"Web Agent: {goal[:50]}",
                        lambda: _get_web_agent().run_autonomous_goal(
                            goal=goal.strip(),
                            start_url=start_url.strip() or None,
                            cancel_event=self._cancel_event,
                        ),
                    )
                return _get_web_agent().run_autonomous_goal(
                    goal=goal.strip(), start_url=start_url.strip() or None, cancel_event=self._cancel_event
                )
            return {"ok": False, "message": f"Unknown autonomous action '{action}'."}

        # 12. Universal External MCP Client Hub (Persistent Pooled Sessions!)
        @m.tool(
            name="mcp_hub_action",
            description="Connect to persistent external MCP servers in mcp_servers.json (playwright, windows, filesystem) to list servers, discover tools, or call remote tools.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["list_servers", "discover_tools", "call_tool"],
                        "description": "MCP hub action",
                    },
                    "server_name": {"type": "STRING", "description": "Server key from mcp_servers.json"},
                    "tool_name": {"type": "STRING", "description": "Exact remote MCP tool name"},
                    "arguments_json": {"type": "STRING", "description": "JSON string of tool arguments"},
                },
                "required": ["action"],
            },
        )
        def tool_mcp_hub_action(
            action: str,
            server_name: str = "playwright",
            tool_name: str = "",
            arguments_json: str = "{}",
        ) -> dict[str, Any]:
            if action == "list_servers":
                return MCP_HUB.list_configured_servers()
            if action == "discover_tools":
                return MCP_HUB.discover_tools(server_name)
            if action == "call_tool":
                try:
                    parsed = json.loads(arguments_json) if arguments_json.strip() else {}
                    if not isinstance(parsed, dict):
                        parsed = {}
                except Exception:
                    parsed = {}
                return MCP_HUB.call_tool(server_name, tool_name, parsed)
            return {"ok": False, "message": f"Unknown MCP hub action '{action}'."}

        # 12.5 External SaaS App Integrations via Composio (Gmail, GitHub, Google Calendar, Slack, Notion)
        @m.tool(
            name="composio_action",
            description="Execute external SaaS actions via Composio (Gmail, GitHub, Google Calendar, Slack, Notion). Requires confirmed=True for mutating actions (send, create, delete).",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action_slug": {"type": "STRING", "description": "e.g. GMAIL_FETCH_EMAILS, GMAIL_SEND_EMAIL, GITHUB_CREATE_AN_ISSUE"},
                    "arguments_json": {"type": "STRING", "description": "JSON string of action parameters"},
                    "confirmed": {"type": "BOOLEAN", "description": "Set true only after Captain confirms write action"},
                },
                "required": ["action_slug"],
            },
        )
        def tool_composio_action(action_slug: str, arguments_json: str = "{}", confirmed: bool = False) -> dict[str, Any]:
            import json
            try:
                args = json.loads(arguments_json) if arguments_json.strip() else {}
            except Exception:
                args = {}
            from composio_bridge import COMPOSIO_BRIDGE
            return COMPOSIO_BRIDGE.execute_action(action_slug=action_slug, arguments=args, confirmed=confirmed)

        # 13. Personal Knowledge Vault (Local Private SQLite FTS5 RAG over PDFs, Notes & Code — Zero Heavy ML!)
        @m.tool(
            name="knowledge_vault",
            description=(
                "Search or sync Captain's private local Knowledge Vault (PDFs, Markdown notes, code files, docs) "
                "using instant SQLite FTS5 search with zero RAM bloat."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": ["search", "sync", "status"],
                        "description": "search vault, sync/reindex folder, or check status",
                    },
                    "query": {"type": "STRING", "description": "Search query for action='search'"},
                    "folder": {"type": "STRING", "description": "Optional custom folder path for action='sync'"},
                    "limit": {"type": "INTEGER", "description": "Max snippets to return (default 5)"},
                },
                "required": ["action"],
            },
        )
        def tool_knowledge_vault(action: str, query: str = "", folder: str = "", limit: int = 5) -> dict[str, Any]:
            if action == "status":
                return KNOWLEDGE_VAULT.status()
            if action == "sync":
                return KNOWLEDGE_VAULT.sync_index(folder=folder.strip() or None)
            if action == "search":
                return KNOWLEDGE_VAULT.search(query=query, limit=limit)
            return {"ok": False, "message": f"Unknown vault action '{action}'."}

        # 14. Self-Learning Playbooks (1-Second 0-LLM Replay) + Smart Focus/Pomodoro & Eye-Care Sentinel
        @m.tool(
            name="playbook_and_focus",
            description=(
                "Run, list, save, or delete 1-second 0-LLM multi-step Playbooks/Macros (including saving the last "
                "successful autonomous ReAct plan!), OR control Pomodoro Focus Mode & 20-20-20 Eye-Care Sentinel."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "enum": [
                            "playbook_run", "playbook_list", "playbook_save", "playbook_save_last_plan", "playbook_delete",
                            "focus_start", "focus_stop", "focus_status", "eye_care_on", "eye_care_off",
                        ],
                        "description": "Playbook macro or Focus/Habit Sentinel action",
                    },
                    "name": {"type": "STRING", "description": "Playbook name or Focus session label"},
                    "steps_json": {"type": "STRING", "description": "JSON list of {tool, args} steps for playbook_save"},
                    "description": {"type": "STRING", "description": "Optional playbook description"},
                    "minutes": {"type": "INTEGER", "description": "Duration in minutes for focus_start (default 25)"},
                },
                "required": ["action"],
            },
        )
        def tool_playbook_and_focus(
            action: str,
            name: str = "",
            steps_json: str = "[]",
            description: str = "",
            minutes: int = 25,
        ) -> dict[str, Any]:
            if action == "playbook_list":
                return _get_playbook_engine().list_playbooks()
            if action == "playbook_run":
                return _get_playbook_engine().run_playbook(name, self.execute_tool, cancel_event=self._cancel_event)
            if action == "playbook_delete":
                return _get_playbook_engine().delete_playbook(name)
            if action == "playbook_save":
                try:
                    steps = json.loads(steps_json) if steps_json.strip() else []
                except Exception as exc:
                    return {"ok": False, "error_code": "INVALID_JSON", "message": f"Invalid steps_json: {exc}"}
                return _get_playbook_engine().save_playbook(name=name, steps=steps, description=description)
            if action == "playbook_save_last_plan":
                goal, trace = _get_reasoning_engine().get_last_successful_trace()
                return _get_playbook_engine().save_from_react_trace(name=name or "learned_workflow", trace=trace, goal=goal)
            if action == "focus_start":
                return FOCUS_SENTINEL.start_focus(minutes=minutes, label=name or "Deep Work")
            if action == "focus_stop":
                return FOCUS_SENTINEL.stop_focus()
            if action == "focus_status":
                return FOCUS_SENTINEL.status()
            if action == "eye_care_on":
                return FOCUS_SENTINEL.set_eye_care(True)
            if action == "eye_care_off":
                return FOCUS_SENTINEL.set_eye_care(False)
            return {"ok": False, "message": f"Unknown playbook/focus action '{action}'."}

    def _tavily_search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            return {"ok": False, "error_code": "NO_API_KEY", "message": "Tavily API key (.env) mein set nahi hai."}
        try:
            payload = json.dumps({
                "api_key": api_key,
                "query": query,
                "search_depth": os.getenv("DARKSHADOW_TAVILY_SEARCH_DEPTH", "basic"),
                "max_results": int(max_results),
                "include_answer": True,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                headers={"Content-Type": "application/json"},
                data=payload,
            )
            with urllib.request.urlopen(req, timeout=7.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ans = str(data.get("answer") or "")
                results = data.get("results") or []
                lines = []
                if ans:
                    lines.append(f"Answer: {ans}")
                for r in results[:4]:
                    t = r.get("title", "")
                    c = r.get("content", "")
                    u = r.get("url", "")
                    lines.append(f"[{t}] {c} ({u})")
                summary = "\n".join(lines)
                return {
                    "ok": True,
                    "verified_state": "tavily_search_success",
                    "answer": ans,
                    "summary": summary,
                    "message": ans or (results[0].get("content", "") if results else "Results mil gaye hain."),
                }
        except Exception as exc:
            return {"ok": False, "error_code": "TAVILY_FAILED", "message": f"Tavily search error: {exc}"}

    def _fetch_weather(self, city: str = "Prayagraj") -> dict[str, Any]:
        clean_city = (city or "Prayagraj").strip()
        try:
            url = f"https://wttr.in/{urllib.parse.quote(clean_city)}?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=4.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                current = data["current_condition"][0]
                temp_c = current.get("temp_C", "--")
                feels_like = current.get("FeelsLikeC", temp_c)
                humidity = current.get("humidity", "--")
                desc = current.get("weatherDesc", [{}])[0].get("value", "Clear")
                wind = current.get("windspeedKmph", "--")
                msg = f"{clean_city} mein abhi taapmaan {temp_c}°C hai ({desc}), feels like {feels_like}°C, humidity {humidity}%, hawa {wind} km/h."
                return {
                    "ok": True,
                    "verified_state": "weather_fetched",
                    "city": clean_city,
                    "temp_c": temp_c,
                    "feels_like_c": feels_like,
                    "condition": desc,
                    "humidity": humidity,
                    "wind_kmph": wind,
                    "message": msg,
                }
        except Exception:
            pass

        tav = self._tavily_search(f"current live weather in {clean_city} today temperature forecast")
        if tav.get("ok"):
            fallback_txt = (tav.get("answer") or tav.get("summary") or "")[:300]
            return {
                "ok": True,
                "verified_state": "weather_fetched_tavily",
                "city": clean_city,
                "message": fallback_txt or f"{clean_city} ka weather mil gaya.",
            }

        return {"ok": False, "error_code": "WEATHER_UNAVAILABLE", "message": f"{clean_city} ka live weather fetch nahi ho saka."}

    def get_live_tools_declarations(self, non_blocking: bool = True) -> list[Any]:
        if not HAS_GENAI:
            return []
        decls = self.fast_mcp.get_gemini_declarations(non_blocking=non_blocking)
        return [types.Tool(function_declarations=decls)]

    def execute_tool(self, name: str, args: dict[str, Any] | None, source: str = "voice") -> dict[str, Any]:
        """Centralized Middleware: Safety Shield -> Strict Schema/Bool Coercion -> Execution -> Audit Log."""
        meta = self.fast_mcp.registry.get(name)
        if not meta:
            err = {
                "ok": False,
                "error_code": "UNKNOWN_TOOL",
                "message": f"Tool '{name}' registered nahi hai.",
                "available_tools": sorted(self.fast_mcp.registry.keys()),
            }
            log_error("TOOL_ROUTING", err["message"], command_or_context=name)
            return err

        clean_args = dict(args or {})

        # 1. Hard Safety Shield Gate on ALL incoming arguments (JSON serialized so nested values can't bypass!)
        combined_text = json.dumps(clean_args, ensure_ascii=False)
        shield_msg = check_hard_shields(combined_text, read_only=(name in READ_ONLY_TOOLS))
        if shield_msg:
            res = {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield_msg}
            log_error("SAFETY_SHIELD", shield_msg, command_or_context=f"{name}({_redact_sensitive_args(clean_args)})", status="BLOCKED")
            log_action_audit(name, _redact_sensitive_args(clean_args), res, source=source)
            return res

        # 2. Strict Required, Enum & Type Coercion (including BOOLEAN security fix!)
        params_schema = meta["parameters"]
        props = params_schema.get("properties", {})
        for req_key in params_schema.get("required", []):
            if req_key not in clean_args or clean_args[req_key] is None or clean_args[req_key] == "":
                return {
                    "ok": False,
                    "error_code": "MISSING_ARGUMENT",
                    "message": f"Required parameter '{req_key}' missing for tool '{name}'.",
                    "expected_schema": props.get(req_key, {}),
                }

        for key, val in list(clean_args.items()):
            if key not in props:
                clean_args.pop(key, None)
                continue
            p_meta = props[key]
            p_type = str(p_meta.get("type", "STRING")).upper()

            if p_type == "BOOLEAN":
                clean_args[key] = _coerce_bool(val)
                val = clean_args[key]
            elif p_type == "INTEGER" and not isinstance(val, bool):
                try:
                    clean_args[key] = int(float(str(val).strip()))
                    val = clean_args[key]
                except Exception:
                    pass
            elif p_type == "NUMBER" and not isinstance(val, bool):
                try:
                    clean_args[key] = float(str(val).strip())
                    val = clean_args[key]
                except Exception:
                    pass

            allowed_enum = p_meta.get("enum")
            if allowed_enum:
                if isinstance(val, str):
                    matched = next((e for e in allowed_enum if str(e).lower() == val.strip().lower()), None)
                    if matched is not None:
                        clean_args[key] = matched
                        val = matched
                if val not in allowed_enum:
                    return {
                        "ok": False,
                        "error_code": "INVALID_ENUM",
                        "message": f"Invalid value '{val}' for '{key}'.",
                        "allowed_values": allowed_enum,
                    }

        # 2.5 Voice/Passphrase Security Lock Gate for sensitive actions (opt-in once passphrase is set)
        gate_block = SECURITY_GUARD.check_gate(name, clean_args)
        if gate_block:
            log_action_audit(name, _redact_sensitive_args(clean_args), gate_block, source=source)
            return gate_block

        # 3. Execute handler with structured error capture & audit trail
        handler = meta["handler"]
        try:
            result = handler(**clean_args)
            final_res = result if isinstance(result, dict) else {"ok": True, "output": str(result)}
            # Redact passphrase values before writing audit logs!
            audit_args = _redact_sensitive_args(clean_args)
            log_action_audit(name, audit_args, final_res, source=source)
            return final_res
        except Exception as exc:
            log_error(
                category="TOOL_EXECUTION",
                error_message=f"{type(exc).__name__}: {exc}",
                command_or_context=f"{name}({_redact_sensitive_args(clean_args)})",
                exception=exc,
            )
            err_res = {
                "ok": False,
                "error_code": "EXECUTION_ERROR",
                "message": f"Tool '{name}' failed: {type(exc).__name__}: {exc}",
            }
            log_action_audit(name, _redact_sensitive_args(clean_args), err_res, source=source)
            return err_res

    def get_mcp_manifest(self) -> dict[str, Any]:
        return self.fast_mcp.get_mcp_manifest()
