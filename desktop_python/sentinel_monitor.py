"""
Proactive Desktop Sentinel Monitor.
Silently monitors due reminders and Windows battery health in the background.
"""

from __future__ import annotations

import threading
from typing import Callable

from memory_engine import SemanticMemoryEngine

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False


class DesktopSentinel:
    def __init__(
        self,
        memory: SemanticMemoryEngine,
        on_proactive_alert: Callable[[str], None],
        poll_seconds: float = 15.0,
        monitor_battery: bool = True,
    ) -> None:
        self._memory = memory
        self._on_alert = on_proactive_alert
        self._poll = poll_seconds
        self._monitor_battery = monitor_battery
        self._stop = threading.Event()
        self._battery_warned = False

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="darkshadow-sentinel").start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            try:
                due_list = self._memory.pop_due_reminders()
                for rem in due_list:
                    self._on_alert(f"Captain, Reminder: {rem.message}")
            except Exception:
                pass

            if self._monitor_battery and HAS_PSUTIL:
                try:
                    batt = psutil.sensors_battery()
                    if batt is not None:
                        if not batt.power_plugged and batt.percent <= 15 and not self._battery_warned:
                            self._battery_warned = True
                            self._on_alert(
                                f"Captain, laptop battery sirf {batt.percent:.0f}% bachi hai — charger connect kar lijiye."
                            )
                        elif batt.power_plugged or batt.percent >= 25:
                            self._battery_warned = False
                except Exception:
                    pass
