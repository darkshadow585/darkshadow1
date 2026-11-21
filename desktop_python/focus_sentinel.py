"""
DarkShadow Upgrade: Smart Habit & Focus Sentinel (Ultra-Low RAM <1 MB)
======================================================================
Runs a featherweight background watcher (5s poll interval) providing:
  1. Pomodoro Focus Mode: Watches active Windows foreground title and gently
     nudges Captain if distracting sites/apps (Instagram, YouTube, Reddit,
     Netflix, Games, etc.) are opened during focus time.
  2. 20-20-20 Eye-Break Reminder: Optional gentle reminder every 20 minutes.
  3. Low Battery Guard: Proactive alert once when battery drops <= 20% unplugged.

ZERO heavy dependencies — only stdlib + get_active_window_title() + optional psutil.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from windows_tools import get_active_window_title

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

DEFAULT_DISTRACTIONS = (
    "instagram",
    "youtube",
    "reddit",
    "netflix",
    "twitter",
    "x.com",
    "facebook",
    "twitch",
    "shorts",
    "reels",
    "steam",
    "valorant",
    "epic games",
    "hotstar",
    "prime video",
)


class FocusHabitSentinel:
    """Ultra-lightweight Pomodoro Focus, Eye-Care & Battery Sentinel."""

    def __init__(self, on_alert: Callable[[str], None] | None = None) -> None:
        self._on_alert = on_alert
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Focus / Pomodoro state
        self._focus_active = False
        self._focus_label = "Deep Work"
        self._focus_end_ts = 0.0
        self._distractions: set[str] = set(DEFAULT_DISTRACTIONS)
        self._last_nudge_by_tag: dict[str, float] = {}
        self._distraction_hits = 0

        # Eye-care 20-20-20 state (off by default until enabled or during focus)
        self._eye_care_enabled = False
        self._next_eye_break_ts = 0.0

        # Battery alert dedupe
        self._low_battery_notified = False

    def set_alert_callback(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            self._on_alert = callback

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="ds-focus-sentinel")
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=1.5)

    def start_focus(
        self,
        minutes: int = 25,
        label: str = "Deep Work",
        extra_blocklist: list[str] | None = None,
    ) -> dict[str, Any]:
        mins = max(1, min(180, int(minutes or 25)))
        now = time.monotonic()
        with self._lock:
            self._focus_active = True
            self._focus_label = (label or "Deep Work").strip()[:60]
            self._focus_end_ts = now + (mins * 60.0)
            self._distraction_hits = 0
            self._last_nudge_by_tag.clear()
            if extra_blocklist:
                for item in extra_blocklist:
                    clean = str(item or "").strip().lower()
                    if clean:
                        self._distractions.add(clean)
        self.start()
        return {
            "ok": True,
            "verified_state": "focus_started",
            "minutes": mins,
            "label": self._focus_label,
            "message": f"Captain, {mins}-minute Pomodoro Focus Mode ('{self._focus_label}') start ho gaya! Distraction kholne par main tok doonga.",
        }

    def stop_focus(self) -> dict[str, Any]:
        with self._lock:
            was_active = self._focus_active
            hits = self._distraction_hits
            self._focus_active = False
            self._focus_end_ts = 0.0
        if not was_active:
            return {"ok": True, "verified_state": "focus_idle", "message": "Focus Mode abhi active nahi tha."}
        return {
            "ok": True,
            "verified_state": "focus_stopped",
            "distraction_nudges": hits,
            "message": f"Focus Mode band kar diya gaya, Captain (distraction nudges: {hits}).",
        }

    def set_eye_care(self, enabled: bool, interval_minutes: int = 20) -> dict[str, Any]:
        interval = max(10, min(90, int(interval_minutes or 20)))
        with self._lock:
            self._eye_care_enabled = bool(enabled)
            self._next_eye_break_ts = (time.monotonic() + interval * 60.0) if enabled else 0.0
        if enabled:
            self.start()
            return {
                "ok": True,
                "verified_state": "eye_care_enabled",
                "message": f"20-20-20 Eye-Care reminder ON ho gaya (har {interval} min mein gentle alert milega).",
            }
        return {"ok": True, "verified_state": "eye_care_disabled", "message": "Eye-Care reminder OFF kar diya gaya."}

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            rem_sec = max(0, int(self._focus_end_ts - now)) if self._focus_active else 0
            return {
                "ok": True,
                "focus_active": self._focus_active,
                "focus_label": self._focus_label,
                "remaining_minutes": round(rem_sec / 60.0, 1),
                "distraction_nudges": self._distraction_hits,
                "eye_care_enabled": self._eye_care_enabled,
            }

    def _emit(self, message: str) -> None:
        cb = self._on_alert
        if cb is not None:
            try:
                cb(message)
            except Exception:
                pass

    def _check_once(self, now: float, active_title: str | None = None) -> list[str]:
        """Single deterministic check tick (easy to unit test without sleeping!)."""
        alerts: list[str] = []

        # 1. Focus / Pomodoro check
        with self._lock:
            focus_on = self._focus_active
            focus_end = self._focus_end_ts
            focus_label = self._focus_label
            distractions = tuple(self._distractions)

        if focus_on:
            if now >= focus_end:
                with self._lock:
                    self._focus_active = False
                    hits = self._distraction_hits
                alerts.append(
                    f"Shabaash Captain! '{focus_label}' Pomodoro complete ho gaya (distractions: {hits}). Ab 5 minute ka break le lijiye!"
                )
            else:
                title = (active_title if active_title is not None else get_active_window_title()).lower()
                if title:
                    for tag in distractions:
                        if tag in title:
                            with self._lock:
                                last = self._last_nudge_by_tag.get(tag, 0.0)
                                if (now - last) >= 90.0:
                                    self._last_nudge_by_tag[tag] = now
                                    self._distraction_hits += 1
                                    rem_m = max(1, int((focus_end - now) / 60.0))
                                    alerts.append(
                                        f"Captain, Focus Mode chal raha hai ({rem_m} min bache hain) — '{tag}' band karke kaam par wapas aayein!"
                                    )
                            break

        # 2. 20-20-20 Eye-Break check
        with self._lock:
            if self._eye_care_enabled and self._next_eye_break_ts > 0 and now >= self._next_eye_break_ts:
                self._next_eye_break_ts = now + 20 * 60.0
                alerts.append("Captain, 20-20-20 eye break: 20 seconds ke liye screen se door dekhein aur aankhein blink karein.")

        # 3. Low Battery Guard (unplugged <= 20%)
        if HAS_PSUTIL:
            try:
                batt = psutil.sensors_battery()
                if batt is not None:
                    if batt.power_plugged:
                        with self._lock:
                            self._low_battery_notified = False
                    elif batt.percent <= 20:
                        with self._lock:
                            if not self._low_battery_notified:
                                self._low_battery_notified = True
                                alerts.append(f"Battery warning Captain: Sirf {int(batt.percent)}% bachi hai, charger laga lijiye!")
            except Exception:
                pass

        return alerts

    def _loop(self) -> None:
        while not self._stop_event.wait(5.0):
            try:
                for alert in self._check_once(time.monotonic()):
                    self._emit(alert)
            except Exception:
                pass


FOCUS_SENTINEL = FocusHabitSentinel()
