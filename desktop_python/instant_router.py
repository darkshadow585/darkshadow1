"""
DarkShadow Upgrade: Zero-LLM Instant Command Router (<5ms) + Free-Tier Rate-Limit Shield
========================================================================================
Designed strictly for 16 GB RAM machines running at ~70% active memory:
  - ZERO local LLM (NO Ollama, NO llama.cpp, NO PyTorch, NO model weights in RAM!).
  - Pure deterministic Python regex/intent matcher (<1 MB RAM, <5ms execution) handles
    common OS, media, volume, brightness, window, time, battery, focus, playbook, and
    passphrase unlock commands with 0 Gemini API calls (works even offline!).
  - Includes `GeminiRateShield`: smart free-tier 429 cooldown tracker + TTL response cache
    so DarkShadow automatically skips rate-limited models and falls back cleanly from
    `gemini-4-hydrogen` -> `gemini-3.1-flash-lite` without stalling!
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 1. Free-Tier Smart Rate-Limit Shield & Lightweight TTL Cache
# ---------------------------------------------------------------------------

class GeminiRateShield:
    """Tracks per-model 429 cooldowns & tiny TTL cache to protect Free-Tier Gemini quota."""

    def __init__(self, max_cache_entries: int = 48) -> None:
        self._lock = threading.Lock()
        self._cooldown_until: dict[str, float] = {}
        self._cache: dict[str, tuple[float, str]] = {}
        self._max_cache = max_cache_entries

    def is_available(self, model_name: str) -> bool:
        with self._lock:
            return time.monotonic() >= self._cooldown_until.get(model_name, 0.0)

    def mark_rate_limited(self, model_name: str, cooldown_seconds: float = 45.0) -> None:
        with self._lock:
            self._cooldown_until[model_name] = time.monotonic() + max(5.0, cooldown_seconds)

    def choose_models(self, preferred_models: list[str]) -> list[str]:
        """Returns models ordered with non-cooled-down models first (still keeps fallback at end)."""
        unique = list(dict.fromkeys(m for m in preferred_models if m))
        ready = [m for m in unique if self.is_available(m)]
        cooling = [m for m in unique if m not in ready]
        return ready + cooling

    @staticmethod
    def is_quota_error(exc: Exception) -> bool:
        msg = f"{type(exc).__name__}: {exc}".lower()
        return any(tok in msg for tok in ("429", "resource_exhausted", "quota", "rate limit", "too many requests"))

    def cache_get(self, key: str) -> str | None:
        norm = re.sub(r"\s+", " ", (key or "").strip().lower())
        if not norm:
            return None
        with self._lock:
            item = self._cache.get(norm)
            if not item:
                return None
            exp, val = item
            if time.monotonic() > exp:
                self._cache.pop(norm, None)
                return None
            return val

    def cache_put(self, key: str, value: str, ttl_seconds: float = 120.0) -> None:
        norm = re.sub(r"\s+", " ", (key or "").strip().lower())
        if not norm or not value:
            return
        with self._lock:
            if len(self._cache) >= self._max_cache:
                oldest = min(self._cache.items(), key=lambda kv: kv[1][0])[0]
                self._cache.pop(oldest, None)
            self._cache[norm] = (time.monotonic() + max(5.0, ttl_seconds), value)


RATE_SHIELD = GeminiRateShield()


# ---------------------------------------------------------------------------
# 2. Deterministic Zero-LLM Instant Command Router (<5ms, 0 API Calls)
# ---------------------------------------------------------------------------

_APP_ALIASES: dict[str, str] = {
    "edge": "edge",
    "browser": "edge",
    "chrome": "edge",
    "vscode": "vscode",
    "vs code": "vscode",
    "code": "vscode",
    "whatsapp": "whatsapp",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "terminal": "terminal",
    "cmd": "terminal",
    "powershell": "terminal",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "settings": "settings",
    "bluetooth": "bluetooth",
    "wifi": "wifi",
    "wi-fi": "wifi",
    "task manager": "task manager",
    "taskmgr": "task manager",
    "paint": "paint",
}

_APP_NAMES_PATTERN = "|".join(sorted((re.escape(k) for k in _APP_ALIASES), key=len, reverse=True))


class InstantCommandRouter:
    """
    Matches unambiguous single-intent Hinglish/English desktop commands in <5ms
    with ZERO LLM calls and <1 MB RAM. Any complex or conversational query returns
    None so it flows seamlessly to Gemini 4 Hydrogen!
    """

    def match(self, raw_text: str) -> tuple[str, dict[str, Any]] | None:
        text = re.sub(r"\s+", " ", (raw_text or "").strip())
        if not text or len(text) > 140:
            return None
        low = text.lower().strip(" .!?,")

        # Never intercept multi-clause compound commands ("open vscode and play lofi")
        if any(sep in low for sep in (" and ", " aur ", " then ", " phir ", " fir ", " uske baad ", ";")):
            # Exception: unlock/set passphrase or focus labels can be single intent
            if not low.startswith(("unlock ", "set passphrase", "lock shadow")):
                return None

        # --- Security Passphrase Quick Commands ---
        m = re.match(r"^(?:unlock\s+(?:dark)?shadow|unlock\s+guard|passphrase)\s+(.+)$", text, re.IGNORECASE)
        if m:
            return "system_control", {"action": "unlock_guard", "passphrase": m.group(1).strip()}

        if low in ("lock shadow", "lock darkshadow", "lock guard", "security lock"):
            return "system_control", {"action": "lock_guard"}

        # --- Volume Controls ---
        m = re.match(r"^(?:set\s+)?(?:volume|vol|awaz|awaaz|sound)\s*(?:to|ko|pe|par)?\s*(\d{1,3})\s*%?$", low)
        if m:
            return "media_and_device", {"action": "set_volume", "level": max(0, min(100, int(m.group(1))))}

        if re.match(r"^(?:volume\s+up|vol\s+up|increase\s+volume|awaz\s+badha(?:o|de)?|awaaz\s+badha(?:o|de)?|sound\s+badha(?:o|de)?)$", low):
            return "media_and_device", {"action": "volume_up", "level": 10}

        if re.match(r"^(?:volume\s+down|vol\s+down|decrease\s+volume|lower\s+volume|awaz\s+kam\s*(?:kar|karo|karde)?|awaaz\s+kam\s*(?:kar|karo|karde)?)$", low):
            return "media_and_device", {"action": "volume_down", "level": 10}

        if low in ("mute", "mute audio", "mute volume", "awaz band kar", "awaz band karo", "chup", "silent"):
            return "media_and_device", {"action": "mute"}

        if low in ("unmute", "unmute audio", "unmute volume", "awaz chalu kar", "awaz on kar"):
            return "media_and_device", {"action": "unmute"}

        # --- Brightness Controls ---
        m = re.match(r"^(?:set\s+)?(?:brightness|screen\s+brightness|roshni)\s*(?:to|ko|pe|par)?\s*(\d{1,3})\s*%?$", low)
        if m:
            return "media_and_device", {"action": "set_brightness", "level": max(5, min(100, int(m.group(1))))}

        # --- Media Playback Controls ---
        if low in ("pause", "pause music", "pause video", "gaana rok", "gana rok", "music pause"):
            return "media_and_device", {"action": "pause"}
        if low in ("resume", "resume music", "play music", "gaana chala", "gana chala", "unpause"):
            return "media_and_device", {"action": "resume"}
        if low in ("next", "next song", "next track", "agla gaana", "agla gana"):
            return "media_and_device", {"action": "next"}
        if low in ("previous", "prev", "previous song", "pichla gaana", "pichla gana"):
            return "media_and_device", {"action": "prev"}
        if low in ("stop music", "stop media", "gaana band kar", "music band kar"):
            return "media_and_device", {"action": "stop"}
        if low in ("now playing", "kya baj raha hai", "kaunsa gaana baj raha hai", "what is playing"):
            return "media_and_device", {"action": "now_playing"}

        # --- Time & System Health ---
        if re.match(r"^(?:time|what(?:'s| is) the time|time kya hua(?: hai)?|kitne baje(?: hain)?|aaj ki date|today'?s date)$", low):
            return "system_control", {"action": "time"}

        if re.match(r"^(?:system health|pc health|battery|battery kitni hai|ram kitna hai|cpu usage|system status)$", low):
            return "system_control", {"action": "health"}

        # --- Window Controls ---
        if low in ("minimize", "minimize window", "window minimize kar"):
            return "app_and_window", {"action": "minimize"}
        if low in ("maximize", "maximize window", "window maximize kar"):
            return "app_and_window", {"action": "maximize"}
        if low in ("show desktop", "desktop dikha", "desktop dikhao"):
            return "app_and_window", {"action": "show_desktop"}

        # --- Open / Close Allowlisted Apps ---
        m = re.match(rf"^(?:open|launch|start|khol|kholo)\s+({_APP_NAMES_PATTERN})$", low)
        if m:
            return "app_and_window", {"action": "open", "app_name": _APP_ALIASES[m.group(1)]}

        m = re.match(rf"^({_APP_NAMES_PATTERN})\s+(?:khol|kholo|khol\s+do|open\s+kar|open\s+karo)$", low)
        if m:
            return "app_and_window", {"action": "open", "app_name": _APP_ALIASES[m.group(1)]}

        m = re.match(rf"^(?:close|band\s+kar|band\s+karo)\s+(active|{_APP_NAMES_PATTERN})$", low)
        if m:
            target = m.group(1)
            return "app_and_window", {"action": "close", "app_name": "active" if target == "active" else _APP_ALIASES[target]}

        # --- Focus / Pomodoro Sentinel ---
        m = re.match(r"^(?:start\s+)?(?:focus|pomodoro)(?:\s+mode)?(?:\s+(\d{1,3})\s*(?:m|min|mins|minutes)?)?$", low)
        if m:
            mins = int(m.group(1)) if m.group(1) else 25
            return "playbook_and_focus", {"action": "focus_start", "minutes": mins}

        if low in ("stop focus", "end focus", "stop pomodoro", "focus band kar", "focus mode off"):
            return "playbook_and_focus", {"action": "focus_stop"}

        if low in ("focus status", "pomodoro status"):
            return "playbook_and_focus", {"action": "focus_status"}

        if low in ("eye care on", "eye break on", "eyecare on"):
            return "playbook_and_focus", {"action": "eye_care_on"}
        if low in ("eye care off", "eye break off", "eyecare off"):
            return "playbook_and_focus", {"action": "eye_care_off"}

        # --- Playbook 1-Second Replay ---
        m = re.match(r"^(?:run|start|activate)\s+(?:playbook|macro|routine)\s+([a-z0-9_ -]{2,40})$", low)
        if m:
            return "playbook_and_focus", {"action": "playbook_run", "name": m.group(1).strip()}

        if low in ("coding mode", "chill mode", "night winddown", "night mode"):
            return "playbook_and_focus", {"action": "playbook_run", "name": low.replace(" ", "_")}

        if low in ("list playbooks", "show playbooks", "playbooks"):
            return "playbook_and_focus", {"action": "playbook_list"}

        if low in ("morning briefing", "good morning briefing"):
            return "system_control", {"action": "run_routine", "routine": "morning_briefing"}

        # --- Standby / Emergency Stop ---
        if low in ("standby", "sleep mode", "go to sleep", "so ja", "standby mode"):
            return "system_control", {"action": "standby"}
        if low in ("stop all", "emergency stop", "kill switch", "cancel all jobs"):
            return "autonomous_agent", {"action": "cancel_all"}

        return None

    def try_dispatch(
        self,
        raw_text: str,
        execute_tool_fn: Callable[[str, dict[str, Any], str], dict[str, Any]],
    ) -> dict[str, Any] | None:
        """If matched, executes immediately with 0 Gemini API calls and returns the tool result."""
        hit = self.match(raw_text)
        if not hit:
            return None
        t0 = time.perf_counter()
        tool_name, tool_args = hit
        res = execute_tool_fn(tool_name, tool_args, "instant_router")
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        if isinstance(res, dict):
            res = dict(res)
            res["instant_routed"] = True
            res["latency_ms"] = elapsed_ms
            res["routed_tool"] = tool_name
        return res


INSTANT_ROUTER = InstantCommandRouter()
