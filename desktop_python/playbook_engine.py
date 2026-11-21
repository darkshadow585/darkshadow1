"""
DarkShadow Upgrade: Self-Learning Playbooks / Macros Engine (1-Second Replay, 0 LLM Calls)
==========================================================================================
"Ek baar sikhao, hamesha 1 second mein replay!"
- Stores multi-step routines as clean JSON in `.darkshadow/playbooks.json`.
- Replays directly through MCPToolRegistry (0 Gemini API calls, full safety shields intact!).
- Can auto-save the latest successful multi-step ReAct plan from REASONING_ENGINE as a named playbook!
- RAM footprint: <0.3 MB (pure JSON + stdlib).
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import PLAYBOOKS_PATH

_DEFAULT_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "coding_mode": {
        "name": "coding_mode",
        "description": "Open VS Code, set comfortable 65% brightness, play Lofi Coding Beats in Edge.",
        "steps": [
            {"tool": "app_and_window", "args": {"action": "open", "app_name": "vscode"}},
            {"tool": "media_and_device", "args": {"action": "set_brightness", "level": 65}},
            {"tool": "media_and_device", "args": {"action": "play_music", "query": "Lofi Chill Beats for coding", "platform": "youtube"}},
        ],
        "created_at": "builtin",
        "run_count": 0,
    },
    "focus_mode": {
        "name": "focus_mode",
        "description": "Mute system audio, set 60% brightness, start a 25-minute Pomodoro Focus Session.",
        "steps": [
            {"tool": "media_and_device", "args": {"action": "mute"}},
            {"tool": "media_and_device", "args": {"action": "set_brightness", "level": 60}},
            {"tool": "playbook_and_focus", "args": {"action": "focus_start", "minutes": 25}},
        ],
        "created_at": "builtin",
        "run_count": 0,
    },
    "chill_mode": {
        "name": "chill_mode",
        "description": "Lower brightness to 50% and play Arijit Singh songs on Spotify Web.",
        "steps": [
            {"tool": "media_and_device", "args": {"action": "set_brightness", "level": 50}},
            {"tool": "media_and_device", "args": {"action": "play_music", "query": "Arijit Singh best songs", "platform": "spotify_web"}},
        ],
        "created_at": "builtin",
        "run_count": 0,
    },
    "night_winddown": {
        "name": "night_winddown",
        "description": "Dim screen to 30%, lower volume to 25%, pause distracting media.",
        "steps": [
            {"tool": "media_and_device", "args": {"action": "set_brightness", "level": 30}},
            {"tool": "media_and_device", "args": {"action": "set_volume", "level": 25}},
        ],
        "created_at": "builtin",
        "run_count": 0,
    },
}


def _slugify(name: str) -> str:
    clean = re.sub(r"[^a-z0-9_ -]+", "", (name or "").strip().lower())
    clean = re.sub(r"[\s-]+", "_", clean).strip("_")
    return clean[:48]


class PlaybookEngine:
    """Zero-LLM deterministic multi-step playbook store & replay engine."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._path = Path(store_path) if store_path else PLAYBOOKS_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._playbooks: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            data = json.loads(json.dumps(_DEFAULT_PLAYBOOKS))
            self._write_file(data)
            return data
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
        return json.loads(json.dumps(_DEFAULT_PLAYBOOKS))

    def _write_file(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def list_playbooks(self) -> dict[str, Any]:
        with self._lock:
            items = [
                {
                    "name": k,
                    "description": v.get("description", ""),
                    "step_count": len(v.get("steps", [])),
                    "run_count": int(v.get("run_count", 0)),
                }
                for k, v in sorted(self._playbooks.items())
            ]
        return {"ok": True, "count": len(items), "playbooks": items}

    def save_playbook(
        self,
        name: str,
        steps: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        key = _slugify(name)
        if not key:
            return {"ok": False, "error_code": "INVALID_NAME", "message": "Playbook ka valid naam batayein."}
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "error_code": "EMPTY_STEPS", "message": "Kam se kam 1 valid step required hai."}

        cleaned_steps: list[dict[str, Any]] = []
        for s in steps[:12]:
            if not isinstance(s, dict) or not s.get("tool"):
                continue
            tool_name = str(s["tool"]).strip()
            # Prevent recursive playbook infinite loops
            if tool_name == "playbook_and_focus" and str((s.get("args") or {}).get("action", "")).lower() == "playbook_run":
                continue
            step_obj: dict[str, Any] = {
                "tool": tool_name,
                "args": dict(s.get("args") or {}),
            }
            if s.get("delay_ms"):
                step_obj["delay_ms"] = max(0, min(5000, int(s["delay_ms"])))
            cleaned_steps.append(step_obj)

        if not cleaned_steps:
            return {"ok": False, "error_code": "INVALID_STEPS", "message": "Koi valid replayable step nahi mila."}

        with self._lock:
            self._playbooks[key] = {
                "name": key,
                "description": (description or f"Custom playbook '{key}'").strip()[:220],
                "steps": cleaned_steps,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "run_count": int(self._playbooks.get(key, {}).get("run_count", 0)),
            }
            self._write_file(self._playbooks)

        return {
            "ok": True,
            "verified_state": "playbook_saved",
            "name": key,
            "step_count": len(cleaned_steps),
            "message": f"Captain, playbook '{key}' ({len(cleaned_steps)} steps) save ho gaya! Ab seedha 1 second mein replay hoga.",
        }

    def delete_playbook(self, name: str) -> dict[str, Any]:
        key = _slugify(name)
        with self._lock:
            if key not in self._playbooks:
                return {"ok": False, "error_code": "NOT_FOUND", "message": f"Playbook '{name}' nahi mila."}
            self._playbooks.pop(key, None)
            self._write_file(self._playbooks)
        return {"ok": True, "verified_state": "playbook_deleted", "message": f"Playbook '{key}' delete kar diya gaya."}

    def _find_playbook(self, query: str) -> dict[str, Any] | None:
        key = _slugify(query)
        with self._lock:
            if key in self._playbooks:
                return json.loads(json.dumps(self._playbooks[key]))
            # Fuzzy substring match (e.g. "coding" -> "coding_mode")
            for k, v in self._playbooks.items():
                if key and (key in k or k in key):
                    return json.loads(json.dumps(v))
        return None

    def run_playbook(
        self,
        name: str,
        execute_tool_fn: Callable[[str, dict[str, Any], str], dict[str, Any]],
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        pb = self._find_playbook(name)
        if not pb:
            available = [p["name"] for p in self.list_playbooks()["playbooks"]]
            return {
                "ok": False,
                "error_code": "NOT_FOUND",
                "message": f"Playbook '{name}' nahi mila. Available: {', '.join(available)}",
            }

        results: list[dict[str, Any]] = []
        succeeded = 0
        for idx, step in enumerate(pb.get("steps", []), start=1):
            if cancel_event is not None and cancel_event.is_set():
                return {
                    "ok": False,
                    "error_code": "CANCELLED",
                    "playbook": pb["name"],
                    "steps_completed": succeeded,
                    "message": f"Playbook '{pb['name']}' Kill Switch se step {idx} par roka gaya.",
                }
            delay_ms = int(step.get("delay_ms") or 0)
            if delay_ms > 0:
                time.sleep(min(5.0, delay_ms / 1000.0))

            t_name = str(step.get("tool", ""))
            t_args = dict(step.get("args") or {})
            out = execute_tool_fn(t_name, t_args, f"playbook:{pb['name']}")
            results.append({"step": idx, "tool": t_name, "ok": bool(out.get("ok")), "message": out.get("message", "")})

            if out.get("error_code") in ("SHIELD_BLOCKED", "PASSPHRASE_LOCKED"):
                return {
                    "ok": False,
                    "error_code": out["error_code"],
                    "playbook": pb["name"],
                    "steps_completed": succeeded,
                    "details": results,
                    "message": out.get("message", "Security gate blocked playbook step."),
                }
            if out.get("ok"):
                succeeded += 1

        with self._lock:
            if pb["name"] in self._playbooks:
                self._playbooks[pb["name"]]["run_count"] = int(self._playbooks[pb["name"]].get("run_count", 0)) + 1
                self._write_file(self._playbooks)

        return {
            "ok": succeeded > 0,
            "verified_state": "playbook_executed",
            "playbook": pb["name"],
            "steps_completed": succeeded,
            "total_steps": len(results),
            "details": results,
            "message": f"Captain, playbook '{pb['name']}' complete ho gaya ({succeeded}/{len(results)} steps, 0 LLM calls).",
        }

    def save_from_react_trace(self, name: str, trace: list[dict[str, Any]], goal: str = "") -> dict[str, Any]:
        """Convert a recorded successful ReAct step trace into a reusable MCP playbook."""
        # Map ReAct internal tool names to MCPToolRegistry tool calls
        converted: list[dict[str, Any]] = []
        for item in trace:
            r_tool = str(item.get("tool", ""))
            r_args = dict(item.get("args") or {})
            if r_tool == "windows_app_open":
                converted.append({"tool": "app_and_window", "args": {"action": "open", "app_name": r_args.get("app_name", "")}})
            elif r_tool == "windows_system":
                act = str(r_args.get("action", "")).lower()
                if act in ("volume", "set_volume"):
                    converted.append({"tool": "media_and_device", "args": {"action": "set_volume", "level": int(r_args.get("level", 50))}})
                elif act in ("brightness", "set_brightness"):
                    converted.append({"tool": "media_and_device", "args": {"action": "set_brightness", "level": int(r_args.get("level", 60))}})
                elif act in ("health", "status"):
                    converted.append({"tool": "system_control", "args": {"action": "health"}})
            elif r_tool == "windows_uia_click":
                converted.append({"tool": "windows_ui_automation", "args": {"action": "click", "element_name": r_args.get("name", ""), "window_title": r_args.get("window_title", "")}})
            elif r_tool == "windows_uia_type":
                converted.append({"tool": "windows_ui_automation", "args": {"action": "type", "text": r_args.get("text", ""), "element_name": r_args.get("name", ""), "press_enter": bool(r_args.get("press_enter", False)), "window_title": r_args.get("window_title", "")}})
            elif r_tool == "mcp_hub_call":
                converted.append({
                    "tool": "mcp_hub_action",
                    "args": {
                        "action": "call_tool",
                        "server_name": r_args.get("server_name", ""),
                        "tool_name": r_args.get("tool_name", ""),
                        "arguments_json": json.dumps(r_args.get("arguments", {})),
                    },
                })
        if not converted:
            return {
                "ok": False,
                "error_code": "NO_REPLAYABLE_STEPS",
                "message": "Last ReAct run mein koi replayable desktop step nahi tha (ya abhi tak koi ReAct plan run nahi hua).",
            }
        return self.save_playbook(name=name, steps=converted, description=f"Learned from goal: {goal[:140]}")


PLAYBOOK_ENGINE = PlaybookEngine()
