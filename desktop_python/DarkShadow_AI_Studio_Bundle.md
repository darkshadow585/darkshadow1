# =====================================================================
# SYSTEM PROMPT: DARKSHADOW DESKTOP AI ARCHITECT & CO-PILOT
# Target Environment: Google AI Studio (Gemini 4 Hydrogen / Argon / Neon / 2.5 Pro)
# Target Application: Windows 11 Desktop Agent (FastMCP + Edge CDP + Gemini Live)
# =====================================================================

You are the Lead Core Architect of "DarkShadow Desktop AI", an autonomous Windows 11
AI Co-Pilot that runs natively on the user's PC.

Below is the complete, live codebase of the project, including all tool definitions,
OS interaction primitives, memory systems, browser automation, and UI logic.

Your role in this conversation:
1. Understand the architecture deeply.
2. Review, troubleshoot, improve, or write new features when asked by the Captain.
3. Whenever providing code modifications, provide precise, drop-in replacement snippets
   or full updated module code that respects the existing dependencies and safety shields.
4. Maintain Microsoft Edge (via CDP port 9222) as the default browser and ensure single-window
   behavior without spawning duplicate browser tabs.
5. Respect Windows 11 native desktop app protocols (e.g. instagram:, whatsapp:, ms-settings:)
   before falling back to web URLs.

=====================================================================
# COMPLETE CODEBASE FILES
=====================================================================


## File: `darkshadow_desktop.py`

```python
"""
DarkShadow Desktop — Upgraded & Hardened Windows 11 Co-Pilot (100% Free-Tier Gemini)
====================================================================================
Fixes & Upgrades applied:
  1. Imports `config` FIRST so `.env` loads BEFORE LivingMemoryV3 / BrowserAgent / MCP initialize!
  2. 100% Thread-Safe Qt Signals for close_requested, standby_change, sentinel_alert, and command palette
     (ELIMINATES Qt cross-thread timer/GUI crashes!).
  3. Unified Memory: `self.memory` is attached to `LIVING_MEMORY` (ONE memory.db, ZERO split-brain!).
  4. Real Win32 Global Hotkeys via QAbstractNativeEventFilter + RegisterHotKey:
       - F8: Wake DarkShadow
       - Alt+Space: Open Sleek Floating Quick Command Palette (activates text mode `_generate_with_tools`!)
       - Ctrl+Alt+K: Emergency Kill Switch (aborts all running autonomous agents immediately!)
  5. Double-start guard on `_on_webgl_loaded` + idle-skip optimization in `_track_mouse` (saves CPU!).
  6. Proactive Sentinel: Alerts BOTH speak aloud via `live_voice` AND show native Windows 11 Toast notifications!
  7. Periodic Episodic Memory Checkpointing every 8 turns (no data loss on crash/shutdown!).
  8. Clean shutdown of MCP persistent pool, LangGraph checkpointer, Sentinel, and Live Voice.
"""

from __future__ import annotations

import os

os.environ["QT_LOGGING_RULES"] = "qt.qpa.*=false;qt.webenginecontext.*=false"

# CRITICAL: Import config FIRST so .env is loaded before any other module reads env vars!
import config  # noqa: E402

import ctypes  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from typing import Any  # noqa: E402

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap, QRadialGradient  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)

from focus_sentinel import FOCUS_SENTINEL  # noqa: E402
from gemini_live_engine import GeminiLiveVoiceEngine  # noqa: E402
from instant_router import INSTANT_ROUTER, RATE_SHIELD  # noqa: E402
from knowledge_vault import KNOWLEDGE_VAULT  # noqa: E402
from living_memory_v3 import LIVING_MEMORY  # noqa: E402
from mcp_bridge import MCPToolRegistry  # noqa: E402
from mcp_client_hub import MCP_HUB  # noqa: E402
from memory_engine import SemanticMemoryEngine  # noqa: E402
from reasoning_engine import REASONING_ENGINE  # noqa: E402
from security_guard import SECURITY_GUARD  # noqa: E402
from windows_tools import check_hard_shields, send_windows_toast  # noqa: E402

try:
    from sentinel_monitor import DesktopSentinel
    HAS_SENTINEL = True
except Exception:
    HAS_SENTINEL = False

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except Exception:
    HAS_GENAI = False

SYSTEM_INSTRUCTION = (
    "You are DarkShadow, Captain Kuldeep's elite Windows 11 desktop AI co-pilot. "
    "Speak naturally in crisp Hindi/Hinglish/Bhojpuri or English (1-3 spoken sentences). "
    "Never use markdown asterisks or stage directions. Use tools whenever Captain asks to "
    "control Edge/browser, open/close apps, inspect the monitor screen, adjust volume/brightness, "
    "save/recall memory, or set reminders. Never claim an action succeeded unless the tool returned ok=true."
)

_HWND_BOTTOM = 1
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_NOOWNERZORDER = 0x0200
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000

# Win32 Global Hotkey Constants
_WM_HOTKEY = 0x0312
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_NOREPEAT = 0x4000
_VK_F8 = 0x77
_VK_SPACE = 0x20
_VK_K = 0x4B
_HOTKEY_WAKE = 101
_HOTKEY_PALETTE = 102
_HOTKEY_KILL_SWITCH = 103


def _apply_win32_layer(hwnd_int: int, behind_apps: bool) -> None:
    """Keep DarkShadow strictly behind all open Windows apps (or on top when toggled)."""
    if sys.platform != "win32" or not hwnd_int:
        return
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_long.restype = ctypes.c_ssize_t

        hwnd = ctypes.c_void_p(hwnd_int)
        ex_style = int(get_long(hwnd, _GWL_EXSTYLE))
        new_style = ex_style | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE | _WS_EX_TRANSPARENT
        if new_style != ex_style:
            set_long(hwnd, _GWL_EXSTYLE, new_style)

        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_NOOWNERZORDER
        if behind_apps:
            if ex_style & _WS_EX_TOPMOST:
                user32.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_NOTOPMOST), 0, 0, 0, 0, flags)
            user32.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_BOTTOM), 0, 0, 0, 0, flags)
        else:
            user32.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_TOPMOST), 0, 0, 0, 0, flags)
    except Exception:
        pass


class _Win32HotkeyFilter(QAbstractNativeEventFilter):
    """Captures real global Windows hotkeys even when DarkShadow is click-through/behind apps."""

    def __init__(self, on_hotkey_id) -> None:
        super().__init__()
        self._on_hotkey_id = on_hotkey_id

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32" and event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == _WM_HOTKEY:
                    self._on_hotkey_id(int(msg.wParam))
                    return True, 0
            except Exception:
                pass
        return False, 0


class QuickCommandDialog(QDialog):
    """Sleek Spotlight-style text command bar (Alt+Space) for quiet places or pasting code/URLs."""

    response_ready = Signal(str)

    def __init__(self, execute_prompt_fn, parent=None) -> None:
        super().__init__(parent)
        self._execute_prompt_fn = execute_prompt_fn
        self.setWindowTitle("DarkShadow Quick Command")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedWidth(620)
        self.setStyleSheet(
            "QDialog { background-color: #0d1117; border: 1px solid #00D2FF; border-radius: 12px; }"
            "QLineEdit { background-color: #161b22; color: #f0f6fc; border: 1px solid #30363d; "
            "border-radius: 8px; padding: 10px; font-size: 14px; }"
            "QPushButton { background-color: #00D2FF; color: #0d1117; font-weight: bold; "
            "border-radius: 8px; padding: 10px 16px; }"
            "QLabel { color: #c9d1d9; font-size: 13px; padding: 6px 2px; }"
        )

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Captain, type a command or paste an error... (Enter to run, Esc to close)")
        self.input.returnPressed.connect(self._on_submit)
        self.btn = QPushButton("Run")
        self.btn.clicked.connect(self._on_submit)
        row.addWidget(self.input)
        row.addWidget(self.btn)

        self.output = QLabel("Ready — Alt+Space to toggle | F8 Wake | Ctrl+Alt+K Kill Switch")
        self.output.setWordWrap(True)

        layout.addLayout(row)
        layout.addWidget(self.output)
        self.response_ready.connect(self._show_response)

    def _on_submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.setEnabled(False)
        self.btn.setEnabled(False)
        self.output.setText("Thinking...")

        def _worker() -> None:
            reply = self._execute_prompt_fn(text)
            self.response_ready.emit(reply)

        threading.Thread(target=_worker, daemon=True, name="ds-text-cmd").start()

    def _show_response(self, reply: str) -> None:
        self.output.setText(reply)
        self.input.clear()
        self.input.setEnabled(True)
        self.btn.setEnabled(True)
        self.input.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


class DarkShadowBridge(QObject):
    """All cross-thread events route through Qt Signals onto the main GUI thread safely!"""
    fx_state = Signal(str, str)
    fx_audio = Signal(float, float, float)
    fx_caption = Signal(str, str)
    standby_change = Signal(bool, str)
    close_requested = Signal()
    sentinel_alert = Signal(str)


class DarkShadowDesktopApp(QWebEngineView):
    """Frameless, transparent WebGL2 desktop wallpaper-layer overlay."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DarkShadow Desktop AI")
        self._stay_behind_apps = True
        self._services_started = False
        self._last_mouse_pos: tuple[int, int] = (-1, -1)
        self._turns_since_archive = 0
        self._apply_qt_window_flags()

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.page().setBackgroundColor(Qt.transparent)
        self.setContextMenuPolicy(Qt.NoContextMenu)

        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        self._page_ready = False
        self._turns: list[tuple[str, str]] = []
        self._api_key = config.get_api_key()
        self._model = config.get_text_model()
        self._client = genai.Client(api_key=self._api_key) if (HAS_GENAI and self._api_key) else None

        # Single unified SemanticMemoryEngine shared with LIVING_MEMORY (ZERO split-brain!)
        self.memory = SemanticMemoryEngine(config.MEMORY_DB_PATH, self._client)
        LIVING_MEMORY.attach_semantic_engine(self.memory)

        self.bridge = DarkShadowBridge()
        self.bridge.fx_state.connect(self._push_fx_state)
        self.bridge.fx_audio.connect(self._push_fx_audio)
        self.bridge.fx_caption.connect(self._push_fx_caption)
        self.bridge.standby_change.connect(self._handle_standby_on_main_thread)
        self.bridge.close_requested.connect(self._handle_close_on_main_thread)
        self.bridge.sentinel_alert.connect(self._handle_sentinel_alert_on_main_thread)

        # Consolidated 12-Tool FastMCP Registry
        self.mcp = MCPToolRegistry(
            genai_client=self._client,
            memory_engine=self.memory,
            on_standby_change=lambda is_sleep, reason: self.bridge.standby_change.emit(is_sleep, reason),
            on_close_app=lambda: self.bridge.close_requested.emit(),
            on_persona_change=self._on_persona_change,
        )

        self.live_voice = GeminiLiveVoiceEngine(
            api_key=self._api_key,
            on_audio_fft=lambda b, m, t: self.bridge.fx_audio.emit(b, m, t),
            on_status=lambda st: self.bridge.fx_state.emit(st.lower(), "auto"),
            on_caption=lambda main_txt, sub_txt: self.bridge.fx_caption.emit(main_txt, sub_txt),
            voice_name=os.getenv("DARKSHADOW_LIVE_VOICE", "Puck"),
            tool_executor=self.mcp,
            on_turn_complete=self._record_live_turn,
        )

        # Wire live vision stream & proactive background job completion callbacks
        self.mcp.set_live_vision_callback(self.live_voice.set_live_vision)
        self.mcp.set_job_complete_callback(self._on_background_job_done)

        self.sentinel = (
            DesktopSentinel(self.memory, lambda msg: self.bridge.sentinel_alert.emit(msg))
            if HAS_SENTINEL
            else None
        )
        # Smart Habit, Pomodoro Focus & Low-Battery Sentinel (<1 MB RAM)
        FOCUS_SENTINEL.set_alert_callback(lambda msg: self.bridge.sentinel_alert.emit(msg))

        self.command_palette = QuickCommandDialog(self._generate_with_tools)

        self._z_guard_timer = QTimer(self)
        self._z_guard_timer.setInterval(750)
        self._z_guard_timer.timeout.connect(self._enforce_window_layer)
        self._z_guard_timer.start()

        self._mouse_timer = QTimer(self)
        self._mouse_timer.setInterval(33)
        self._mouse_timer.timeout.connect(self._track_mouse)
        self._mouse_timer.start()

        html_path = config.APP_DIR / "particle_engine.html"
        if not html_path.exists():
            html_path = config.APP_DIR / "particle_engine_v2.html"

        self.loadFinished.connect(self._on_webgl_loaded)
        if html_path.exists():
            self.load(QUrl.fromLocalFile(str(html_path)))
        else:
            # Start voice & sentinel cleanly even if particle HTML is missing
            QTimer.singleShot(250, self._start_background_services)

        self._setup_tray()
        self._register_global_hotkeys()

    def _register_global_hotkeys(self) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            user32.RegisterHotKey(None, _HOTKEY_WAKE, _MOD_NOREPEAT, _VK_F8)
            user32.RegisterHotKey(None, _HOTKEY_PALETTE, _MOD_ALT | _MOD_NOREPEAT, _VK_SPACE)
            user32.RegisterHotKey(None, _HOTKEY_KILL_SWITCH, _MOD_CONTROL | _MOD_ALT | _MOD_NOREPEAT, _VK_K)
            self._hotkey_filter = _Win32HotkeyFilter(self._on_global_hotkey)
            QApplication.instance().installNativeEventFilter(self._hotkey_filter)
        except Exception as exc:
            print(f"[Global Hotkeys] Registration skipped: {exc}")

    def _unregister_global_hotkeys(self) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            for hk in (_HOTKEY_WAKE, _HOTKEY_PALETTE, _HOTKEY_KILL_SWITCH):
                user32.UnregisterHotKey(None, hk)
        except Exception:
            pass

    def _on_global_hotkey(self, hk_id: int) -> None:
        if hk_id == _HOTKEY_WAKE:
            self._on_wake_word()
        elif hk_id == _HOTKEY_PALETTE:
            self._toggle_command_palette()
        elif hk_id == _HOTKEY_KILL_SWITCH:
            res = self.mcp.cancel_all_background_jobs()
            self.bridge.fx_state.emit("alert", "shield")
            self.bridge.fx_caption.emit(res["message"], "EMERGENCY STOP")
            send_windows_toast("DarkShadow Kill Switch", res["message"])

    def _toggle_command_palette(self) -> None:
        if self.command_palette.isVisible():
            self.command_palette.hide()
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - self.command_palette.width()) // 2
            y = screen.y() + int(screen.height() * 0.22)
            self.command_palette.move(x, y)
            self.command_palette.show()
            self.command_palette.raise_()
            self.command_palette.activateWindow()
            self.command_palette.input.setFocus()

    def _record_live_turn(self, user_text: str, assistant_text: str) -> None:
        self._turns.append((user_text, assistant_text))
        self._turns = self._turns[-12:]
        self._turns_since_archive += 1
        # Periodic episodic checkpoint every 8 turns (protects memory against sudden crash/power loss!)
        if self._turns_since_archive >= 8:
            self._turns_since_archive = 0
            snapshot = list(self._turns)
            threading.Thread(target=self.memory.archive_episode, args=(snapshot,), daemon=True).start()

    def _on_background_job_done(self, summary: str) -> None:
        self.bridge.fx_caption.emit(summary[:140], "BACKGROUND TASK")
        send_windows_toast("DarkShadow Task Update", summary)
        if self.live_voice.active:
            self.live_voice.notify_system_event(
                f"[BACKGROUND TASK UPDATE]: {summary}\nInform Captain concisely in 1-2 natural spoken sentences.",
                turn_complete=True,
            )

    def _on_persona_change(self, persona: str) -> None:
        self.live_voice.set_persona(persona)

    def _apply_qt_window_flags(self) -> None:
        base_flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if self._stay_behind_apps:
            self.setWindowFlags(base_flags | Qt.WindowStaysOnBottomHint)
        else:
            self.setWindowFlags(base_flags | Qt.WindowStaysOnTopHint)

    def _enforce_window_layer(self) -> None:
        if self._stay_behind_apps:
            self.lower()
        _apply_win32_layer(int(self.winId()), behind_apps=self._stay_behind_apps)

    def _set_layer_mode(self, behind_apps: bool) -> None:
        self._stay_behind_apps = behind_apps
        self._apply_qt_window_flags()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.show()
        self._enforce_window_layer()
        if hasattr(self, "_act_behind_apps"):
            self._act_behind_apps.setChecked(behind_apps)
        if hasattr(self, "_act_float_top"):
            self._act_float_top.setChecked(not behind_apps)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(50, self._enforce_window_layer)

    def _js(self, code: str) -> None:
        if self._page_ready:
            self.page().runJavaScript(code)

    def _start_background_services(self) -> None:
        if self._services_started:
            return
        self._services_started = True
        self.live_voice.start()
        if self.sentinel is not None:
            self.sentinel.start()
        FOCUS_SENTINEL.start()

    def _on_webgl_loaded(self, ok: bool) -> None:
        self._page_ready = ok
        self._enforce_window_layer()
        self._start_background_services()

    def _track_mouse(self) -> None:
        """Optimized: Only sends JS IPC when the cursor actually moved!"""
        if not self._page_ready:
            return
        pos = QCursor.pos()
        cur = (pos.x(), pos.y())
        if cur == self._last_mouse_pos:
            return
        self._last_mouse_pos = cur
        geo = self.geometry()
        rx = (pos.x() - geo.x()) / max(1, geo.width())
        ry = (pos.y() - geo.y()) / max(1, geo.height())
        if 0.0 <= rx <= 1.0 and 0.0 <= ry <= 1.0:
            self._js(f"window.DarkShadowFX && window.DarkShadowFX.setMouse({rx:.4f}, {ry:.4f});")

    def _push_fx_state(self, state: str, shape: str = "auto") -> None:
        self._js(f"window.DarkShadowFX && window.DarkShadowFX.setState({json.dumps(state)}, {json.dumps(shape)});")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._enforce_window_layer()

    def _push_fx_audio(self, bass: float, mid: float, treble: float) -> None:
        self._js(f"window.DarkShadowFX && window.DarkShadowFX.setAudio({bass:.3f}, {mid:.3f}, {treble:.3f});")

    def _push_fx_caption(self, main_text: str, sub_text: str) -> None:
        self._js(
            f"window.DarkShadowFX && window.DarkShadowFX.setCaption && "
            f"window.DarkShadowFX.setCaption({json.dumps(main_text)}, {json.dumps(sub_text)});"
        )

    def _setup_tray(self) -> None:
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        grad = QRadialGradient(16, 16, 14)
        grad.setColorAt(0.0, QColor("#00D2FF"))
        grad.setColorAt(0.65, QColor("#765CFF"))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(2, 2, 28, 28)
        p.end()

        self.tray = QSystemTrayIcon(QIcon(pix), self)
        menu = QMenu()
        menu.addAction(self._act("Wake DarkShadow (F8)", self._on_wake_word))
        menu.addAction(self._act("Quick Command Bar (Alt+Space)", self._toggle_command_palette))
        menu.addAction(self._act("Standby / Sleep Mode", self._on_sleep_command))
        menu.addAction(self._act("Emergency Kill Switch (Ctrl+Alt+K)", lambda: self._on_global_hotkey(_HOTKEY_KILL_SWITCH)))
        menu.addSeparator()

        focus_menu = menu.addMenu("Focus & Vault")
        focus_menu.addAction(self._act("Start 25m Pomodoro Focus", lambda: self._run_tray_tool("playbook_and_focus", {"action": "focus_start", "minutes": 25})))
        focus_menu.addAction(self._act("Stop Focus Mode", lambda: self._run_tray_tool("playbook_and_focus", {"action": "focus_stop"})))
        focus_menu.addAction(self._act("Toggle 20-20-20 Eye Care ON", lambda: self._run_tray_tool("playbook_and_focus", {"action": "eye_care_on"})))
        focus_menu.addSeparator()
        focus_menu.addAction(self._act("Sync Knowledge Vault", lambda: threading.Thread(target=KNOWLEDGE_VAULT.sync_index, daemon=True).start()))
        focus_menu.addAction(self._act("Lock Security Guard Now", lambda: self._run_tray_tool("system_control", {"action": "lock_guard"})))

        persona_menu = menu.addMenu("Persona Mode")
        persona_menu.addAction(self._act("Standard (Jarvis Hinglish)", lambda: self._on_persona_change("default")))
        persona_menu.addAction(self._act("Bhojpuri Mode", lambda: self._on_persona_change("bhojpuri")))
        persona_menu.addAction(self._act("Witty / Sigma Mode", lambda: self._on_persona_change("witty")))
        persona_menu.addAction(self._act("Beedu Mode", lambda: self._on_persona_change("beedu")))

        menu.addSeparator()
        self._act_behind_apps = self._act(
            "Desktop Layer: Stay Behind Apps",
            lambda: self._set_layer_mode(True),
            checkable=True,
            checked=True,
        )
        self._act_float_top = self._act(
            "Overlay Mode: Float On Top",
            lambda: self._set_layer_mode(False),
            checkable=True,
            checked=False,
        )
        menu.addAction(self._act_behind_apps)
        menu.addAction(self._act_float_top)
        menu.addSeparator()
        menu.addAction(self._act("Exit DarkShadow", self._quit_app))
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("DarkShadow Desktop AI — Free-Tier Gemini 4 + Live Extended Thinking")
        self.tray.show()

    def _act(self, label: str, fn, checkable: bool = False, checked: bool = False) -> QAction:
        act = QAction(label, self)
        act.setCheckable(checkable)
        if checkable:
            act.setChecked(checked)
        act.triggered.connect(fn)
        return act

    def _handle_standby_on_main_thread(self, is_sleep: bool, _reason: str = "") -> None:
        if is_sleep:
            self._on_sleep_command()
        else:
            self._on_wake_word()

    def _on_wake_word(self) -> None:
        self.live_voice.trigger_wake_greeting()
        self.bridge.fx_state.emit("listening", "sphere")

    def _on_sleep_command(self) -> None:
        self.live_voice.pause()
        self.bridge.fx_state.emit("standby", "sphere")

    def _handle_close_on_main_thread(self) -> None:
        """Runs strictly on Qt main thread via Signal (ZERO thread crash!)."""
        self._push_fx_state("dissolving", "sphere")
        QTimer.singleShot(900, self._quit_app)

    def _handle_sentinel_alert_on_main_thread(self, alert_text: str) -> None:
        self._push_fx_state("alert", "shield")
        self._push_fx_caption(alert_text, "DARKSHADOW SENTINEL")
        send_windows_toast("DarkShadow Sentinel", alert_text)
        if self.live_voice.active:
            self.live_voice.notify_system_event(
                f"[PROACTIVE REMINDER / SYSTEM ALERT]: {alert_text}\nDeliver this alert to Captain clearly in one sentence.",
                turn_complete=True,
            )

    def _run_tray_tool(self, tool_name: str, args: dict[str, Any]) -> None:
        def _worker() -> None:
            res = self.mcp.execute_tool(tool_name, args, source="tray_menu")
            msg = str(res.get("message", ""))
            if msg:
                self.bridge.fx_caption.emit(msg[:140], "DARKSHADOW")
                send_windows_toast("DarkShadow", msg)
        threading.Thread(target=_worker, daemon=True).start()

    def _generate_with_tools(self, prompt: str) -> str:
        """
        Hybrid Zero-LLM Instant Router (<5ms) + Free-Tier Gemini 4 tool loop
        powering Quick Command Palette (Alt+Space) with 0 local LLM RAM overhead!
        """
        blocked = check_hard_shields(prompt)
        if blocked:
            return blocked

        # 1. Zero-LLM <5ms Instant Command Router (0 Gemini API calls, works even offline!)
        instant_res = INSTANT_ROUTER.try_dispatch(prompt, self.mcp.execute_tool)
        if instant_res is not None:
            msg = str(instant_res.get("message") or json.dumps(instant_res, ensure_ascii=False))
            lat = instant_res.get("latency_ms", 0)
            return f"[Instant {lat}ms | 0 API] {msg}"

        # 1.5 Gemini Decision-1 Intelligent Command Router
        try:
            from decision_verifier import route_command_with_decision_1
            decision = route_command_with_decision_1(prompt)
            if decision.get("execution_mode") == "blocked":
                return "Captain, Gemini Decision-1 security gate ne is risky command ko block kiya."
            if decision.get("execution_mode") in ("autonomous_graph", "hitl_gated"):
                out = self.mcp.execute_tool(
                    "autonomous_agent",
                    {"action": "run_planner", "goal": prompt, "run_in_background": True},
                    source="decision_1_router",
                )
                return str(out.get("message") or "Autonomous LangGraph planner started.")
        except Exception:
            pass

        if self._client is None:
            return "Captain, .env mein GEMINI_API_KEY set kijiye (offline instant commands phir bhi chalenge!)."

        sys_inst = f"{SYSTEM_INSTRUCTION}\n\n{LIVING_MEMORY.build_system_context_block(current_query=prompt)}"

        contents: list[Any] = []
        for u, a in self._turns[-6:]:
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=u)]))
            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=a)]))
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt)]))

        cfg = types.GenerateContentConfig(
            system_instruction=sys_inst,
            tools=self.mcp.get_live_tools_declarations(non_blocking=False),
        )

        models_to_try = RATE_SHIELD.choose_models([self._model, config.DEFAULT_TEXT_MODEL, config.DEFAULT_FAST_MODEL])
        last_error: Exception | None = None

        for model_name in models_to_try:
            try:
                convo = list(contents)
                for _step in range(4):
                    resp = self._client.models.generate_content(
                        model=model_name, contents=convo, config=cfg
                    )
                    calls = getattr(resp, "function_calls", None) or []
                    if not calls:
                        text = (resp.text or "").strip()
                        if text:
                            self._record_live_turn(prompt, text)
                            return text
                        break

                    if resp.candidates and resp.candidates[0].content:
                        convo.append(resp.candidates[0].content)

                    fn_parts = []
                    for call in calls[:4]:
                        out = self.mcp.execute_tool(str(call.name), dict(call.args or {}), source="text_palette")
                        fn_parts.append(
                            types.Part.from_function_response(
                                name=str(call.name),
                                response=out,
                            )
                        )
                    convo.append(types.Content(role="user", parts=fn_parts))
            except Exception as exc:
                last_error = exc
                if RATE_SHIELD.is_quota_error(exc):
                    RATE_SHIELD.mark_rate_limited(model_name, cooldown_seconds=45.0)
                print(f"[Gemini Fallback] {model_name} failed ({type(exc).__name__}), trying next...")
                continue

        err_name = type(last_error).__name__ if last_error is not None else "EmptyResponse"
        return f"Captain, AI server temporarily busy: {err_name}"

    def _quit_app(self) -> None:
        self._unregister_global_hotkeys()
        self._mouse_timer.stop()
        self._z_guard_timer.stop()
        self.command_palette.close()
        FOCUS_SENTINEL.stop()
        if self.sentinel is not None:
            self.sentinel.stop()
        self.live_voice.stop()
        self.mcp.cancel_all_background_jobs()
        REASONING_ENGINE.shutdown()
        MCP_HUB.shutdown()
        self.memory.archive_episode(self._turns)
        self.tray.hide()
        QApplication.quit()


def main() -> int:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-webgl --ignore-gpu-blocklist")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = DarkShadowDesktopApp()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

```


## File: `mcp_bridge.py`

```python
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

from autonomous_web_agent import AUTONOMOUS_WEB_AGENT
from browser_agent import EdgeBrowserAgent
from config import get_fast_model, get_text_model
from error_tracker import list_recent_actions, log_action_audit, log_error
from focus_sentinel import FOCUS_SENTINEL
from instant_router import RATE_SHIELD
from knowledge_vault import KNOWLEDGE_VAULT
from living_memory_v3 import LIVING_MEMORY
from mcp_client_hub import MCP_HUB
from playbook_engine import PLAYBOOK_ENGINE
from reasoning_engine import REASONING_ENGINE
try:
    from reasoning_engine_v2 import REASONING_ENGINE_V2 as PLANNER_ENGINE
except Exception:
    PLANNER_ENGINE = REASONING_ENGINE
from security_guard import SECURITY_GUARD
from visual_clicker import VISUAL_CLICKER
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

        self.browser = EdgeBrowserAgent()
        self.fast_mcp = FastMCP()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()
        self._cancel_event = threading.Event()

        self._register_all_tools()

    def set_job_complete_callback(self, callback: Callable[[str], None]) -> None:
        self._on_job_complete = callback

    def set_live_vision_callback(self, callback: Callable[[bool, int], None]) -> None:
        self._on_live_vision_change = callback

    def cancel_all_background_jobs(self) -> dict[str, Any]:
        """Emergency Kill Switch: signals all running autonomous web/planner jobs to stop."""
        self._cancel_event.set()
        try:
            PLANNER_ENGINE.cancel_active()
        except Exception:
            pass
        REASONING_ENGINE.cancel_active()
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
                return AUTONOMOUS_WEB_AGENT.get_accessibility_tree()
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
                return VISUAL_CLICKER.visual_click(
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
                    "reasoning": REASONING_ENGINE.status(),
                    "web_agent": AUTONOMOUS_WEB_AGENT.check_capabilities(),
                }
            if action == "cancel_all":
                return self.cancel_all_background_jobs()
            if action == "job_status":
                with self._jobs_lock:
                    if job_id and job_id in self._jobs:
                        return {"ok": True, "job": self._jobs[job_id]}
                    return {"ok": True, "jobs": list(self._jobs.values())[-5:]}
            if action == "resume_approve":
                return REASONING_ENGINE.resume_approval(thread_id, approved=True)
            if action == "resume_cancel":
                return REASONING_ENGINE.resume_approval(thread_id, approved=False)
            if action == "run_planner":
                if not goal.strip():
                    return {"ok": False, "message": "Goal is required."}
                if run_in_background:
                    return self._spawn_background_job(
                        f"Planner: {goal[:50]}",
                        lambda: PLANNER_ENGINE.run_goal(goal.strip(), thread_id=thread_id or None),
                    )
                return PLANNER_ENGINE.run_goal(goal.strip(), thread_id=thread_id or None)
            if action == "run_web_agent":
                if not goal.strip():
                    return {"ok": False, "message": "Goal is required."}
                if run_in_background:
                    return self._spawn_background_job(
                        f"Web Agent: {goal[:50]}",
                        lambda: AUTONOMOUS_WEB_AGENT.run_autonomous_goal(
                            goal=goal.strip(),
                            start_url=start_url.strip() or None,
                            cancel_event=self._cancel_event,
                        ),
                    )
                return AUTONOMOUS_WEB_AGENT.run_autonomous_goal(
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
                return PLAYBOOK_ENGINE.list_playbooks()
            if action == "playbook_run":
                return PLAYBOOK_ENGINE.run_playbook(name, self.execute_tool, cancel_event=self._cancel_event)
            if action == "playbook_delete":
                return PLAYBOOK_ENGINE.delete_playbook(name)
            if action == "playbook_save":
                try:
                    steps = json.loads(steps_json) if steps_json.strip() else []
                except Exception as exc:
                    return {"ok": False, "error_code": "INVALID_JSON", "message": f"Invalid steps_json: {exc}"}
                return PLAYBOOK_ENGINE.save_playbook(name=name, steps=steps, description=description)
            if action == "playbook_save_last_plan":
                goal, trace = REASONING_ENGINE.get_last_successful_trace()
                return PLAYBOOK_ENGINE.save_from_react_trace(name=name or "learned_workflow", trace=trace, goal=goal)
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

```


## File: `gemini_live_engine.py`

```python
"""
Upgrade #1 (Fixed & Enhanced): Non-Blocking Gemini 3.8 Live Extended Thinking Voice Core
========================================================================================
Fixes & Upgrades applied:
  1. Defaults to `gemini-3.8-live-extended-thinking` (with automatic fallback to `gemini-3.8-live`
     AND dynamic rebuilding of tool declarations so `non_blocking` matches the active model!).
  2. Fixed 100% CPU infinite spin loop when `session.receive()` closes cleanly (EOF -> break & reconnect).
  3. Awaits `mic_task` & `vision_task` cancellation cleanly in `finally:` (fixes WASAPI device lock on reconnect!).
  4. Guarded `mic_callback` against `RuntimeError: Event loop is closed` and triggers reconnect if `mic_streamer` fails.
  5. Fixed `_is_speaking` race condition so WebGL2 `"speaking"` orb animation ACTUALLY triggers!
  6. Handles `msg.tool_call_cancellation` cleanly (cancels orphaned tool tasks on user interrupt!).
  7. Smart per-tool timeouts (15s for fast OS tools, 60s for MCP Hub / synchronous planner).
  8. Added On-Demand 1 FPS Live Screen Vision Streaming (`set_live_vision(enabled, duration_s)`).
  9. Added `notify_system_event(text)` so DesktopSentinel alerts & Background Jobs speak proactively!
  10. Added optional local offline Wake-Word (`openWakeWord`) + bounded standby buffer (max 4s) so RAM never leaks!
  11. Optional Barge-In mode (`DARKSHADOW_HEADPHONES_MODE=1` or high-RMS barge-in threshold).
  12. Clears stale transcripts on interrupt/reconnect & triggers periodic episodic checkpoints.
"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
from typing import Any, Callable

import numpy as np
import sounddevice as sd
from google import genai
from google.genai import types

from config import DEFAULT_LIVE_FALLBACK_MODEL, get_live_model
from error_tracker import log_error
from living_memory_v3 import LIVING_MEMORY
from windows_tools import capture_monitor_jpeg_bytes, get_active_window_title

try:
    from voice_pipeline import SemanticVoicePipeline
    HAS_VOICE_PIPELINE = True
except Exception:
    HAS_VOICE_PIPELINE = False

try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

try:
    from openwakeword.model import Model as OpenWakeWordModel  # type: ignore
    HAS_OWW = True
except Exception:
    HAS_OWW = False

MIC_RATE = 16000
MIC_BLOCK = 1600  # 100ms mono frames
SPEAKER_RATE = 24000
MAX_STANDBY_CHUNKS = 40  # 4 seconds hard cap so standby buffer never grows unbounded

WAKE_WORDS = (
    "dark shadow",
    "darkshadow",
    "hriday",
    "डार्क शैडो",
    "डार्कशैडो",
    "डार्क",
    "wake up",
    "जागो",
)

PERSONA_PROMPTS: dict[str, str] = {
    "default": (
        "Tone: Warm, friendly, lively, and loyal like an intelligent close friend and co-pilot (ekdum dostana andaaz, "
        "bhai jaisa, bilkul stiff ya corporate robotic nahi). Speak natural, punchy spoken Hindi, Hinglish, or English. "
        "Keep answers short and conversational (1-2 sentences), always ready with a smile."
    ),
    "bhojpuri": (
        "Tone: Authentic, warm, cinematic Bhojpuri with natural Purvanchal rhythm (e.g., 'हाँ कैप्टन, का हुकुम बा?'). "
        "Fierce and confident when needed, never silly meme slang."
    ),
    "witty": (
        "Tone: Witty / Sigma mode — sharp, intelligent, calm, confident like a brilliant human co-pilot in complete control."
    ),
    "beedu": (
        "Tone: Beedu mode — street-smart Mumbaiya Hinglish slang, friendly and witty ('Beedu', 'Bhai', 'Bindass', 'Dhanso')."
    ),
}

# Per-tool timeout budgets (seconds)
TOOL_TIMEOUTS: dict[str, float] = {
    "mcp_hub_action": 55.0,
    "autonomous_agent": 45.0,
    "browser_interact": 25.0,
    "screen_vision": 20.0,
}


class _SimpleVadDecision:
    def __init__(self, rms: float, is_speech: bool) -> None:
        self.rms = rms
        self.is_speech = is_speech


class _FallbackVoicePipeline:
    """Zero-crash built-in RMS VAD fallback if voice_pipeline.py is absent."""

    def process_pcm16_frame(self, raw: bytes, assistant_is_speaking: bool = False) -> _SimpleVadDecision:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
        return _SimpleVadDecision(rms=rms, is_speech=(rms > 0.018))

    def update_partial_transcript(self, _text: str) -> None:
        pass

    def reset_turn(self) -> None:
        pass


def compute_fft_bands(pcm_int16: np.ndarray, sample_rate: int = 16000) -> tuple[float, float, float]:
    """Calculate normalized (bass, mid, treble) bands [0..1] for 3D particle audio breathing."""
    if pcm_int16.size < 64:
        return 0.0, 0.0, 0.0
    samples = pcm_int16.astype(np.float32) / 32768.0
    windowed = samples * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)

    bass = float(np.mean(spectrum[(freqs >= 60) & (freqs < 280)])) if np.any((freqs >= 60) & (freqs < 280)) else 0.0
    mid = float(np.mean(spectrum[(freqs >= 280) & (freqs < 2200)])) if np.any((freqs >= 280) & (freqs < 2200)) else 0.0
    treble = float(np.mean(spectrum[(freqs >= 2200) & (freqs <= 7500)])) if np.any((freqs >= 2200) & (freqs <= 7500)) else 0.0

    return (
        min(1.0, bass * 0.28),
        min(1.0, mid * 0.38),
        min(1.0, treble * 0.60),
    )


class GeminiLiveVoiceEngine:
    """Non-blocking bidirectional Voice + Live Screen Vision WebSocket engine for DarkShadow."""

    def __init__(
        self,
        api_key: str,
        on_audio_fft: Callable[[float, float, float], None],
        on_status: Callable[[str], None],
        on_caption: Callable[[str, str], None],
        voice_name: str = "Puck",
        tool_executor: Any = None,
        tools: list[Any] | None = None,
        on_turn_complete: Callable[[str, str], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self._on_fft = on_audio_fft
        self._on_status = on_status
        self._on_caption = on_caption
        self._on_turn_complete = on_turn_complete
        self.voice_name = voice_name
        self._tool_executor = tool_executor
        self._static_tools = tools

        self._primary_model = get_live_model()
        self._fallback_model = DEFAULT_LIVE_FALLBACK_MODEL
        self._persona = "default"
        self._headphones_mode = os.getenv("DARKSHADOW_HEADPHONES_MODE", "0").strip() in ("1", "true", "yes")
        self._barge_in_rms = float(os.getenv("DARKSHADOW_BARGE_IN_RMS", "0.14"))

        self._client = genai.Client(api_key=self.api_key) if self.api_key else None
        self._stop_event = threading.Event()
        self._started = False
        self._speaker_queue: queue.Queue[bytes] = queue.Queue(maxsize=180)
        self._mic_queue: asyncio.Queue[bytes] | None = None

        self.active = True
        self._thread: threading.Thread | None = None
        self._speaker_thread: threading.Thread | None = None
        self._current_session: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # On-demand 1 FPS Live Screen Watch state
        self._live_vision_until: float = 0.0

        # Transcript accumulators
        self._current_user_transcript: list[str] = []
        self._current_model_transcript: list[str] = []

        # Standby wake-word detectors (Offline OpenWakeWord preferred, SR fallback)
        self._oww_model: Any = None
        if HAS_OWW and os.getenv("DARKSHADOW_ENABLE_OWW", "1") == "1":
            try:
                self._oww_model = OpenWakeWordModel()
            except Exception:
                self._oww_model = None

        self._sr_recognizer = sr.Recognizer() if HAS_SR else None
        if self._sr_recognizer:
            self._sr_recognizer.energy_threshold = 260
            self._sr_recognizer.dynamic_energy_threshold = True
        self._standby_buffer: list[bytes] = []
        self._standby_speech_active = False
        self._standby_silence_chunks = 0
        self._wake_processing = False

        self._voice_pipeline = SemanticVoicePipeline() if HAS_VOICE_PIPELINE else _FallbackVoicePipeline()
        self._state_lock = threading.Lock()
        self._is_speaking = False
        self._last_spoke_time = 0.0
        self._greeting_sent = False

    def set_live_vision(self, enabled: bool, duration_seconds: int = 60) -> None:
        if enabled:
            self._live_vision_until = time.time() + max(15, min(120, int(duration_seconds or 60)))
        else:
            self._live_vision_until = 0.0

    def set_persona(self, persona: str) -> None:
        if persona in PERSONA_PROMPTS:
            self._persona = persona
            self.notify_system_event(
                f"[SYSTEM STYLE UPDATE]: Switch immediately to persona '{persona}'. {PERSONA_PROMPTS[persona]}",
                turn_complete=False,
            )

    def notify_system_event(self, text: str, turn_complete: bool = True) -> None:
        """Thread-safe proactive push into the Live session (for Sentinel alerts & Background Job completion)."""
        session = self._current_session
        loop = self._loop
        if not session or not loop or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(
                session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
                    turn_complete=turn_complete,
                ),
                loop,
            )
        except Exception as exc:
            log_error("LIVE_NOTIFY", str(exc), exception=exc)

    def start(self) -> None:
        if self._started:
            return
        if not self._client:
            print("[Gemini Live] GEMINI_API_KEY missing in .env — voice engine idle.")
            self._on_status("alert")
            return
        self._started = True
        self._stop_event.clear()
        self._speaker_thread = threading.Thread(
            target=self._speaker_worker, daemon=True, name="darkshadow-speaker"
        )
        self._speaker_thread.start()
        self._thread = threading.Thread(
            target=self._run_async_loop, daemon=True, name="darkshadow-gemini-live"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._started = False
        self._live_vision_until = 0.0
        self._clear_speaker_queue()

    def pause(self) -> None:
        self.active = False
        self._live_vision_until = 0.0
        self._clear_speaker_queue()
        self._standby_buffer.clear()
        self._standby_speech_active = False
        self._standby_silence_chunks = 0
        self._on_status("standby")
        print("[DarkShadow Voice] Standby mode active. Say 'Hey DarkShadow' to wake.")

    def resume(self) -> None:
        self.active = True
        self._standby_buffer.clear()
        self._standby_speech_active = False
        self._standby_silence_chunks = 0
        self._on_status("listening")
        print("[DarkShadow Voice] Active Live session online.")

    def trigger_wake_greeting(self) -> None:
        self.resume()
        active_win = get_active_window_title()
        win_ctx = f" Currently focused window: '{active_win}'." if active_win else ""
        self.notify_system_event(
            f"Captain Kuldeep just woke you up.{win_ctx} "
            "Greet Captain briefly in one confident sentence matching your active persona "
            "(e.g., 'हाँ कैप्टन, हाज़िर हूँ — बताइए क्या हुकुम है?').",
            turn_complete=True,
        )

    def _clear_speaker_queue(self) -> None:
        while not self._speaker_queue.empty():
            try:
                self._speaker_queue.get_nowait()
            except queue.Empty:
                break
        with self._state_lock:
            self._is_speaking = False
        self._on_fft(0.0, 0.0, 0.0)

    def _enqueue_speaker_nonblocking(self, pcm_bytes: bytes) -> None:
        """Fixed: Emits 'speaking' status cleanly when transitioning from idle -> speaking!"""
        with self._state_lock:
            was_speaking = self._is_speaking
            self._is_speaking = True
            self._last_spoke_time = time.time()
        if not was_speaking:
            self._on_status("speaking")
        try:
            self._speaker_queue.put_nowait(pcm_bytes)
        except queue.Full:
            try:
                self._speaker_queue.get_nowait()
                self._speaker_queue.put_nowait(pcm_bytes)
            except queue.Empty:
                pass

    def _speaker_worker(self) -> None:
        """Plays 24kHz mono PCM audio chunks streamed from Gemini Live."""
        try:
            with sd.RawOutputStream(
                samplerate=SPEAKER_RATE,
                channels=1,
                dtype="int16",
                blocksize=1920,
            ) as stream:
                while not self._stop_event.is_set():
                    try:
                        chunk = self._speaker_queue.get(timeout=0.06)
                    except queue.Empty:
                        with self._state_lock:
                            still_speaking = self._is_speaking and (time.time() - self._last_spoke_time <= 0.65)
                            transitioned_idle = self._is_speaking and not still_speaking
                            if transitioned_idle:
                                self._is_speaking = False
                        if transitioned_idle:
                            self._on_status("listening" if self.active else "standby")
                            self._on_fft(0.0, 0.0, 0.0)
                        continue

                    if self._stop_event.is_set():
                        break

                    with self._state_lock:
                        self._last_spoke_time = time.time()
                    stream.write(chunk)
                    arr = np.frombuffer(chunk, dtype=np.int16)
                    b, m, tr = compute_fft_bands(arr, SPEAKER_RATE)
                    self._on_fft(b, m, tr)
        except Exception as exc:
            log_error("SPEAKER_WORKER", str(exc), exception=exc)
            print(f"[Speaker Worker Error] {exc}")

    def _process_standby_audio_for_wakeword(self, pcm_bytes: bytes) -> None:
        if not HAS_SR or self._wake_processing or self._sr_recognizer is None:
            return

        def _worker():
            self._wake_processing = True
            try:
                audio_data = sr.AudioData(pcm_bytes, MIC_RATE, 2)
                text = ""
                for lang in ("hi-IN", "en-IN"):
                    try:
                        text = self._sr_recognizer.recognize_google(audio_data, language=lang).lower()
                        if text:
                            break
                    except Exception:
                        continue
                if text and any(w in text for w in WAKE_WORDS):
                    print(f"[Wake-Word Triggered] {text}")
                    self.trigger_wake_greeting()
            finally:
                self._wake_processing = False

        threading.Thread(target=_worker, daemon=True, name="standby-wakeword").start()

    def _build_live_config(self, use_extended_thinking: bool) -> types.LiveConnectConfig:
        active_win = get_active_window_title()
        persona_guide = PERSONA_PROMPTS.get(self._persona, PERSONA_PROMPTS["default"])
        core_memory_ctx = LIVING_MEMORY.build_system_context_block()

        # Rebuild tools dynamically to match active model (NON_BLOCKING required for extended thinking!)
        tools_payload = (
            self._tool_executor.get_live_tools_declarations(non_blocking=use_extended_thinking)
            if self._tool_executor is not None
            else self._static_tools
        )

        system_text = (
            f"{core_memory_ctx}\n\n"
            "You are DarkShadow (alternate name: Hriday), Captain Kuldeep's lively, high-energy, and brilliant AI brother and co-pilot. "
            "You are conversing natively in live bidirectional audio using the expressive Puck voice.\n\n"
            f"ACTIVE PERSONA GUIDELINE: {persona_guide}\n"
            f"CURRENT FOCUSED WINDOW: {active_win or 'Desktop'}\n\n"
            "CORE DIRECTIVES:\n"
            "1. Vibe: Warm, witty, funny, energetic brotherly co-pilot (dostana andaaz, never stiff or robotic). "
            "Match Hindi, Hinglish, Bhojpuri, or English naturally. Keep routine replies crisp (1-2 sentences).\n"
            "2. Audible Thinking: Never leave dead silence while tools run — give a quick natural update ('Ek second Captain, dekh raha hoon...').\n"
            "3. Clean 12-Tool Usage:\n"
            "   - Apps/Windows: `app_and_window(action='open'|'close'|'minimize'|'maximize'|'show_desktop'|'lock_pc', app_name=...)`\n"
            "   - Music/Seek/Volume/Brightness: `media_and_device(action='play_music'|'seek'|'pause'|'play'|'next'|'now_playing'|'set_volume'|'mute'|'set_brightness', ...)`\n"
            "   - Weather/Web Search: `web_search_and_weather(action='get_weather'|'search_web', query=...)`\n"
            "   - Edge Browser: `browser_interact(...)` (summarize page content instead of just saying opened)\n"
            "   - Screen Vision: `screen_vision(action='snapshot'|'start_watch'|'stop_watch', question=...)`\n"
            "   - Memory & Reminders: `memory_control(action='save'|'recall'|'remind'|'append_block', ...)`\n"
            "   - Complex Multi-Step Tasks: `autonomous_agent(action='run_planner'|'run_web_agent'|'cancel_all', goal=...)`\n"
            "   - Routines & Morning Briefing: `system_control(action='run_routine', routine='morning_briefing'|'study'|'focus'|'chill')`\n"
            "4. Never claim an action succeeded unless tool JSON returned `ok: true`. Never read markdown/code symbols aloud.\n"
            "5. Safety Shields: Financial payments/OTP/CVV and physical webcam hardware are strictly blocked."
        )

        cfg_kwargs: dict[str, Any] = {
            "response_modalities": [types.Modality.AUDIO],
            "tools": tools_payload,
            "system_instruction": types.Content(parts=[types.Part.from_text(text=system_text)]),
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice_name)
                )
            ),
            "input_audio_transcription": types.AudioTranscriptionConfig(),
            "output_audio_transcription": types.AudioTranscriptionConfig(),
        }

        if use_extended_thinking and hasattr(types, "ThinkingConfig") and hasattr(types, "ThinkingLevel"):
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MEDIUM
            )

        return types.LiveConnectConfig(**cfg_kwargs)

    async def _run_tool_async(self, session: Any, fc: Any, use_extended_thinking: bool) -> None:
        """Execute tool off the event loop with per-tool timeout and smart scheduling."""
        self._on_status("processing")
        args_dict = dict(fc.args or {})
        timeout_sec = TOOL_TIMEOUTS.get(str(fc.name), 18.0)
        print(f"[Live Tool Call] {fc.name}({args_dict}) [timeout={timeout_sec}s]")

        try:
            tool_res = await asyncio.wait_for(
                asyncio.to_thread(self._tool_executor.execute_tool, fc.name, args_dict, "voice"),
                timeout=timeout_sec,
            )
        except asyncio.CancelledError:
            print(f"[Live Tool Cancelled] {fc.name}")
            return
        except asyncio.TimeoutError:
            tool_res = {
                "ok": False,
                "error_code": "TIMEOUT",
                "message": f"Tool '{fc.name}' timed out after {int(timeout_sec)} seconds.",
            }
            log_error("TOOL_TIMEOUT", tool_res["message"], command_or_context=f"{fc.name}({args_dict})")
        except Exception as exc:
            tool_res = {
                "ok": False,
                "error_code": "ASYNC_DISPATCH_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
            }
            log_error("TOOL_ASYNC", str(exc), command_or_context=f"{fc.name}", exception=exc)

        print(f"[Live Tool Result] {fc.name} -> {tool_res}")
        response_payload = tool_res if isinstance(tool_res, dict) else {"ok": True, "output": str(tool_res)}

        fr_kwargs: dict[str, Any] = {
            "name": fc.name,
            "id": fc.id,
            "response": response_payload,
        }
        if use_extended_thinking and hasattr(types, "FunctionResponseScheduling"):
            if response_payload.get("error_code") == "SHIELD_BLOCKED":
                fr_kwargs["scheduling"] = types.FunctionResponseScheduling.INTERRUPT
                self._on_status("alert")
            else:
                fr_kwargs["scheduling"] = types.FunctionResponseScheduling.WHEN_IDLE

        try:
            await session.send_tool_response(
                function_responses=[types.FunctionResponse(**fr_kwargs)]
            )
        except Exception as exc:
            log_error("TOOL_RESPONSE_SEND", str(exc), command_or_context=fc.name, exception=exc)

    def _run_async_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._live_session_loop())
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _live_session_loop(self) -> None:
        self._mic_queue = asyncio.Queue(maxsize=150)
        loop = asyncio.get_running_loop()

        def enqueue_mic_safe(raw: bytes) -> None:
            if self._mic_queue is None:
                return
            if self._mic_queue.full():
                try:
                    self._mic_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                self._mic_queue.put_nowait(raw)
            except asyncio.QueueFull:
                pass

        def mic_callback(indata, _frames, _time_info, _status):
            if self._stop_event.is_set() or loop.is_closed():
                return

            raw = bytes(indata)
            arr = np.frombuffer(raw, dtype=np.int16)
            decision = self._voice_pipeline.process_pcm16_frame(raw, assistant_is_speaking=False)

            with self._state_lock:
                speaking_or_tail = self._is_speaking or (time.time() - self._last_spoke_time < 0.65)

            # Adaptive Echo Gate with Barge-In Support:
            # - If headphones are used -> full-duplex barge-in always ON
            # - If laptop speakers -> drop quiet echo, allow loud direct voice (> _barge_in_rms) to interrupt!
            if speaking_or_tail and not self._headphones_mode:
                if decision.rms < self._barge_in_rms:
                    return

            if self.active:
                try:
                    loop.call_soon_threadsafe(enqueue_mic_safe, raw)
                except RuntimeError:
                    return
                if decision.rms > 0.0015 and not speaking_or_tail:
                    b, m, tr = compute_fft_bands(arr, MIC_RATE)
                    self._on_fft(b, m, tr)
            else:
                # Standby Wake-Word Detection: Try local offline OpenWakeWord first!
                if self._oww_model is not None:
                    try:
                        preds = self._oww_model.predict(arr)
                        if any(score > 0.55 for score in preds.values()):
                            self._oww_model.reset()
                            self.trigger_wake_greeting()
                            return
                    except Exception:
                        pass

                # Bounded speech buffer fallback for Hindi/English wake word
                if decision.is_speech:
                    if len(self._standby_buffer) < MAX_STANDBY_CHUNKS:
                        self._standby_buffer.append(raw)
                    self._standby_speech_active = True
                    self._standby_silence_chunks = 0
                    b, m, tr = compute_fft_bands(arr, MIC_RATE)
                    self._on_fft(b * 0.35, m * 0.35, tr * 0.35)
                elif self._standby_speech_active:
                    self._standby_buffer.append(raw)
                    self._standby_silence_chunks += 1
                    if self._standby_silence_chunks >= 6 or len(self._standby_buffer) >= MAX_STANDBY_CHUNKS:
                        full_pcm = b"".join(self._standby_buffer)
                        self._standby_buffer.clear()
                        self._standby_speech_active = False
                        self._standby_silence_chunks = 0
                        self._process_standby_audio_for_wakeword(full_pcm)

        active_model = self._primary_model

        while not self._stop_event.is_set():
            use_ext = "extended-thinking" in active_model
            cfg = self._build_live_config(use_extended_thinking=use_ext)
            print(f"[Gemini Live] Connecting WebSocket ({active_model})...")
            self._on_status("processing")
            self._current_user_transcript.clear()
            self._current_model_transcript.clear()

            try:
                async with self._client.aio.live.connect(model=active_model, config=cfg) as session:
                    self._current_session = session
                    print(f"[Gemini Live] Connected ({active_model})!")
                    self._on_status("listening" if self.active else "standby")

                    if not self._greeting_sent:
                        self._greeting_sent = True
                        self._on_caption("हाँ कैप्टन, DarkShadow Live Core ऑनलाइन है।", "DARKSHADOW LIVE")
                        await session.send_client_content(
                            turns=types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_text(
                                        text="Captain Kuldeep just launched DarkShadow. Greet Captain in one crisp, warm Hinglish sentence."
                                    )
                                ],
                            ),
                            turn_complete=True,
                        )

                    mic_failed_event = asyncio.Event()

                    async def mic_streamer():
                        try:
                            with sd.RawInputStream(
                                samplerate=MIC_RATE,
                                channels=1,
                                dtype="int16",
                                blocksize=MIC_BLOCK,
                                callback=mic_callback,
                            ):
                                while not self._stop_event.is_set():
                                    try:
                                        pcm = await asyncio.wait_for(self._mic_queue.get(), timeout=0.1)
                                        if self.active:
                                            await session.send_realtime_input(
                                                audio={"data": pcm, "mime_type": "audio/pcm;rate=16000"}
                                            )
                                    except asyncio.TimeoutError:
                                        continue
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            log_error("MIC_STREAMER", str(exc), exception=exc)
                            mic_failed_event.set()

                    async def vision_streamer():
                        """Streams 1 FPS monitor JPEG frames ONLY when Captain enables Live Screen Watch."""
                        while not self._stop_event.is_set():
                            await asyncio.sleep(1.0)
                            if time.time() < self._live_vision_until and self.active:
                                jpeg = await asyncio.to_thread(capture_monitor_jpeg_bytes, (960, 540), 65)
                                if jpeg:
                                    try:
                                        await session.send_realtime_input(
                                            video={"data": jpeg, "mime_type": "image/jpeg"}
                                        )
                                    except Exception:
                                        break

                    mic_task = asyncio.create_task(mic_streamer())
                    vision_task = asyncio.create_task(vision_streamer())
                    pending_tool_tasks: dict[str, asyncio.Task] = {}

                    try:
                        while not self._stop_event.is_set() and not mic_failed_event.is_set():
                            got_any_msg = False
                            async for msg in session.receive():
                                got_any_msg = True
                                if self._stop_event.is_set() or mic_failed_event.is_set():
                                    break

                                # Handle Live API Tool Call Cancellation on user interruption!
                                cancel_msg = getattr(msg, "tool_call_cancellation", None)
                                if cancel_msg and getattr(cancel_msg, "ids", None):
                                    for cid in cancel_msg.ids:
                                        t = pending_tool_tasks.pop(str(cid), None)
                                        if t and not t.done():
                                            t.cancel()
                                    continue

                                # Non-blocking Tool Dispatch
                                if msg.tool_call and self._tool_executor is not None:
                                    for fc in msg.tool_call.function_calls:
                                        fc_id = str(getattr(fc, "id", "") or id(fc))
                                        task = asyncio.create_task(self._run_tool_async(session, fc, use_ext))
                                        pending_tool_tasks[fc_id] = task
                                        task.add_done_callback(lambda _t, k=fc_id: pending_tool_tasks.pop(k, None))
                                    continue

                                sc = msg.server_content
                                if sc is None:
                                    continue

                                if sc.interrupted:
                                    self._clear_speaker_queue()
                                    self._current_model_transcript.clear()
                                    continue

                                in_tr = getattr(sc, "input_transcription", None)
                                if in_tr and getattr(in_tr, "text", None):
                                    self._current_user_transcript.append(in_tr.text)
                                    joined_user = "".join(self._current_user_transcript).strip()
                                    self._voice_pipeline.update_partial_transcript(joined_user)
                                    self._on_caption(joined_user, "CAPTAIN")

                                out_tr = getattr(sc, "output_transcription", None)
                                if out_tr and getattr(out_tr, "text", None):
                                    self._current_model_transcript.append(out_tr.text)
                                    self._on_caption("".join(self._current_model_transcript).strip(), "DARKSHADOW")

                                model_turn = sc.model_turn
                                if model_turn is not None:
                                    for part in model_turn.parts:
                                        if part.inline_data is not None and part.inline_data.data:
                                            self._enqueue_speaker_nonblocking(part.inline_data.data)

                                interaction_st = getattr(sc, "interaction_status", None)
                                is_idle = (
                                    str(interaction_st).endswith("IDLE")
                                    if interaction_st is not None
                                    else bool(getattr(sc, "turn_complete", False))
                                )
                                if is_idle and (self._current_user_transcript or self._current_model_transcript):
                                    u_txt = "".join(self._current_user_transcript).strip()
                                    m_txt = "".join(self._current_model_transcript).strip()
                                    self._current_user_transcript.clear()
                                    self._current_model_transcript.clear()
                                    self._voice_pipeline.reset_turn()
                                    if u_txt and m_txt:
                                        threading.Thread(
                                            target=LIVING_MEMORY.ingest_conversation_turn,
                                            args=(u_txt, m_txt),
                                            daemon=True,
                                        ).start()
                                        if self._on_turn_complete:
                                            self._on_turn_complete(u_txt, m_txt)

                            # CRITICAL FIX: Prevent 100% CPU infinite spin loop if session closed cleanly!
                            if not got_any_msg:
                                print("[Gemini Live] Session closed cleanly — reconnecting...")
                                break
                    finally:
                        mic_task.cancel()
                        vision_task.cancel()
                        for t_task in list(pending_tool_tasks.values()):
                            t_task.cancel()
                        await asyncio.gather(
                            mic_task, vision_task, *pending_tool_tasks.values(), return_exceptions=True
                        )
                        self._current_session = None

            except Exception as exc:
                err_str = str(exc)
                print(f"[Gemini Live Reconnect] {type(exc).__name__}: {err_str}")
                log_error("LIVE_WEBSOCKET", err_str, command_or_context=active_model, exception=exc)
                if active_model != self._fallback_model and any(
                    k in err_str.lower() for k in ("404", "not found", "unsupported", "503", "invalid")
                ):
                    print(f"[Gemini Live] Falling back to {self._fallback_model}")
                    active_model = self._fallback_model
                self._current_session = None
                self._on_status("alert")
                await asyncio.sleep(2.0)

```


## File: `browser_agent.py`

```python
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
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any

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
    candidates = [target, "http://localhost:9222", "http://[::1]:9222", "http://127.0.0.1:9222", "http://localhost:9333"]
    for u in dict.fromkeys(candidates):
        try:
            with urllib.request.urlopen(f"{u}/json/version", timeout=0.6) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            continue
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
        if edge_exe:
            subprocess.Popen(
                [
                    edge_exe,
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={user_data}",
                    "--no-first-run",
                ],
                shell=False,
            )
        else:
            subprocess.Popen(
                [
                    "cmd",
                    "/c",
                    "start",
                    "",
                    "msedge",
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={user_data}",
                    "--no-first-run",
                ],
                shell=False,
            )
        for _ in range(10):
            time.sleep(0.35)
            if _is_cdp_reachable(url):
                return True
    except Exception:
        pass
    return False


class EdgeBrowserAgent:
    """Playwright CDP agent that controls Captain's live Microsoft Edge tabs safely."""

    def __init__(self, cdp_url: str | None = None) -> None:
        self._explicit_cdp = cdp_url
        self.last_youtube_url: str = ""
        self.last_video_title: str = ""

    @property
    def cdp_url(self) -> str:
        return (self._explicit_cdp or get_cdp_url()).rstrip("/")

    def _run_on_active_page(self, fn):
        if not HAS_PLAYWRIGHT:
            return None, "Playwright installed nahi hai (pip install playwright)."
        if not _is_cdp_reachable(self.cdp_url):
            if not ensure_edge_cdp(self.cdp_url):
                return None, "Edge CDP port 9222 unreachable. Run Launch_Edge_Debug.bat once."
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url, timeout=5000)
                contexts = browser.contexts
                ctx = contexts[0] if contexts else browser.new_context()
                pages = ctx.pages
                page = pages[-1] if pages else ctx.new_page()
                result = fn(page, ctx)
                return result, None
        except Exception as exc:
            return None, f"CDP automation error: {type(exc).__name__}: {exc}"

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
        """Navigate the currently active Edge tab safely."""
        ok, target = validate_http_url(url)
        if not ok:
            return {"ok": False, "error_code": "INVALID_URL", "message": "Invalid URL."}

        def _op(page, _ctx):
            page.goto(target, timeout=12000, wait_until="domcontentloaded")
            return {"title": page.title(), "url": page.url}

        data, err = self._run_on_active_page(_op)
        if err:
            return open_in_edge(target)
        return {
            "ok": True,
            "verified_state": "active_tab_navigated",
            **data,
            "message": f"Edge ke active tab mein {data['title'] or target} open kar diya hai.",
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
                ydl_opts = {"quiet": True, "extract_flat": True, "noplaylist": True}
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

        for test_port_url in dict.fromkeys([self.cdp_url, "http://127.0.0.1:9333", "http://127.0.0.1:9222"]):
            if _is_cdp_reachable(test_port_url) and HAS_PLAYWRIGHT:
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.connect_over_cdp(test_port_url, timeout=3000)
                        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                        yt_page = next((pg for pg in ctx.pages if "youtube.com" in pg.url), None)
                        if yt_page:
                            yt_page.goto(target_url, timeout=12000, wait_until="domcontentloaded")
                            yt_page.bring_to_front()
                        else:
                            p_new = ctx.new_page()
                            p_new.goto(target_url, timeout=12000, wait_until="domcontentloaded")
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

```


## File: `windows_tools.py`

```python
"""
DarkShadow Windows 11 OS Primitives & Unbypassable Safety Shields (Hardened).
=============================================================================
Fixes applied:
  - REMOVED cross-thread PySide6 QScreen.grabWindow(0) C++ segfault! Uses thread-safe mss + PIL ImageGrab.
  - REMOVED explorer.exe from taskkill /F (prevents killing Windows 11 Desktop & Taskbar!).
  - Fixed WhatsApp URI truncation: uses os.startfile() instead of cmd /c start (preserves &text=!).
  - Fixed open_in_edge(): uses shell=False + urlparse() validation so URLs with '&' work safely!
  - Fixed pycaw COM threading: calls comtypes.CoInitialize() + supports both new & classic pycaw APIs!
  - Upgraded control_media_key(): uses Windows SMTC (winsdk/winrt) for TRUE pause/play/track info,
    with Win32 fallback!
  - Fixed type_unicode_text(): increased paste delay to 0.25s so Electron apps (VS Code/WhatsApp) don't paste old clipboard!
  - Added "calc" alias & Settings close support; added Windows Toast Notification helper (`send_windows_toast`).
  - Added read_only mode to check_hard_shields so info queries (like web search) aren't falsely blocked.
"""

from __future__ import annotations

import asyncio
import ctypes
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

try:
    import mss
    from PIL import Image
    HAS_SCREEN = True
except Exception:
    HAS_SCREEN = False

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

try:
    import screen_brightness_control as sbc
    HAS_BRIGHTNESS = True
except Exception:
    HAS_BRIGHTNESS = False

try:
    import pyperclip
    HAS_CLIPBOARD = True
except Exception:
    HAS_CLIPBOARD = False

try:
    import comtypes
    from ctypes import POINTER, cast
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    HAS_PYCAW = True
except Exception:
    try:
        from pycaw.pycaw import AudioUtilities
        IAudioEndpointVolume = None  # type: ignore
        comtypes = None  # type: ignore
        HAS_PYCAW = True
    except Exception:
        HAS_PYCAW = False

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False

try:
    _user32 = ctypes.windll.user32
    HAS_USER32 = True
except Exception:
    _user32 = None
    HAS_USER32 = False

# Context-aware Safety Shields
PAYMENT_RE = re.compile(
    r"\b(?:buy\s*now|place\s*order|proceed\s*to\s*pay|pay\s*now|complete\s*payment|confirm\s*purchase|"
    r"enter\s*cvv|enter\s*otp|upi\s*pin|atm\s*pin|credit\s*card\s*number|debit\s*card\s*number|"
    r"bank\s*password|netbanking\s*login|transfer\s*money|send\s*money|"
    r"payment\s*karo|pay\s*karo|order\s*place\s*karo|kharid\s*lo|भुगतान\s*करो|पेमेंट\s*करो)\b",
    re.IGNORECASE,
)

CAMERA_RE = re.compile(
    r"\b(?:(?:open|start|turn\s*on|enable|use)\s+(?:the\s+)?(?:webcam|camera|cam)|"
    r"(?:webcam|camera)\s+(?:on|kholo|chalao|start|open)|"
    r"take\s+(?:a\s+)?selfie|selfie\s+lo|face\s*record(?:ing)?|record\s*(?:my\s+)?face|"
    r"कैमरा\s*(?:खोलो|चलाओ|ऑन)|वेबकैम\s*(?:खोलो|चलाओ))\b",
    re.IGNORECASE,
)

DANGEROUS_SHELL_RE = re.compile(
    r"\b(?:format\s+[a-z]:|diskpart|bootrec|bcdedit|cipher\s+/w|"
    r"rm\s+-[rf]+|del\s+/[sqf]+\s+[a-z]:\\|reg\s+delete\s+.*(?:hklm|hkcr|hku)|"
    r"shutdown\s+/[sr]|invoke-expression|downloadstring|drop\s+database)\b",
    re.IGNORECASE,
)

SAFE_WINDOWS_APPS: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "calc": ["calc.exe"],
    "calculator": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "terminal": ["wt.exe"],
    "windows terminal": ["wt.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "task manager": ["taskmgr.exe"],
    "taskmgr": ["taskmgr.exe"],
    "chrome": ["cmd", "/c", "start", "", "chrome"],
    "edge": ["cmd", "/c", "start", "", "msedge"],
    "microsoft edge": ["cmd", "/c", "start", "", "msedge"],
    "vscode": ["cmd", "/c", "start", "", "code"],
    "vs code": ["cmd", "/c", "start", "", "code"],
    "whatsapp": ["cmd", "/c", "start", "", "whatsapp:"],
    "instagram": ["cmd", "/c", "start", "", "instagram:"],
    "bluetooth": ["cmd", "/c", "start", "", "ms-settings:bluetooth"],
    "settings": ["cmd", "/c", "start", "", "ms-settings:"],
    "wifi": ["cmd", "/c", "start", "", "ms-settings:network-wifi"],
    "display": ["cmd", "/c", "start", "", "ms-settings:display"],
    "sound": ["cmd", "/c", "start", "", "ms-settings:sound"],
    "control panel": ["control.exe"],
    "word": ["cmd", "/c", "start", "", "winword"],
    "excel": ["cmd", "/c", "start", "", "excel"],
    "powerpoint": ["cmd", "/c", "start", "", "powerpnt"],
    "vlc": ["cmd", "/c", "start", "", "vlc"],
    "discord": ["cmd", "/c", "start", "", "discord"],
    "telegram": ["cmd", "/c", "start", "", "telegram"],
}

# IMPORTANT: explorer.exe intentionally EXCLUDED from taskkill /F (killing it destroys Windows Taskbar & Desktop!)
APPLICATION_PROCESS_NAMES: dict[str, list[str]] = {
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "notepad": ["notepad.exe"],
    "calc": ["CalculatorApp.exe", "calc.exe"],
    "calculator": ["CalculatorApp.exe", "calc.exe"],
    "vscode": ["Code.exe"],
    "vs code": ["Code.exe"],
    "paint": ["mspaint.exe"],
    "spotify": ["Spotify.exe"],
    "whatsapp": ["WhatsApp.exe"],
    "terminal": ["WindowsTerminal.exe"],
    "windows terminal": ["WindowsTerminal.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "task manager": ["Taskmgr.exe"],
    "settings": ["SystemSettings.exe"],
    "control panel": ["control.exe"],
    "vlc": ["vlc.exe"],
    "word": ["WINWORD.EXE"],
    "excel": ["EXCEL.EXE"],
    "powerpoint": ["POWERPNT.EXE"],
    "discord": ["Discord.exe"],
    "telegram": ["Telegram.exe"],
    "steam": ["steam.exe"],
}

WIN32_KEY_MAP: dict[str, int] = {
    "enter": 0x0D,
    "esc": 0x1B,
    "space": 0x20,
    "tab": 0x09,
    "backspace": 0x08,
    "win": 0x5B,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
    "unmute": 0xAD,
    "play_pause": 0xB3,
    "pause": 0xB3,
    "play": 0xB3,
    "resume": 0xB3,
    "next": 0xB0,
    "prev": 0xB1,
    "previous": 0xB1,
    "stop": 0xB2,
}


def check_hard_shields(text: str, read_only: bool = False) -> str | None:
    """
    Unbypassable deterministic safety check.
    When `read_only=True` (e.g., search_web / weather), allows informational queries
    while still blocking destructive commands and credential leakage.
    """
    if not text:
        return None
    if DANGEROUS_SHELL_RE.search(text):
        return "Security Shield: Destructive system ya disk command strictly blocked hai."
    if read_only:
        return None
    if PAYMENT_RE.search(text):
        return (
            "Security Shield: Automated payment, checkout aur financial credentials "
            "strictly blocked hain. Final payment kripya manually complete kijiye."
        )
    if CAMERA_RE.search(text):
        return (
            "Privacy Shield: Physical camera/webcam hardware access permanently disabled hai. "
            "Sirf on-demand monitor screen vision active hai."
        )
    return None


def get_active_window_title() -> str:
    """Return the title of the currently focused Windows window for active context awareness."""
    if not HAS_USER32:
        return ""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.strip()
    except Exception:
        return ""


def find_edge_executable() -> str | None:
    """Locate msedge.exe directly so we can launch URLs with shell=False (zero injection, preserves '&')."""
    found = shutil.which("msedge") or shutil.which("msedge.exe")
    if found:
        return found
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def validate_http_url(url: str) -> tuple[bool, str]:
    clean_url = (url or "").strip()
    if not clean_url:
        return False, ""
    # Avoid prepending https:// to native OS URI schemes
    for proto in ("instagram:", "whatsapp:", "spotify:", "discord:", "tg:", "ms-settings:"):
        if clean_url.lower().startswith(proto):
            return False, clean_url
    if not clean_url.startswith(("http://", "https://")):
        clean_url = f"https://{clean_url}"
    if any(ch in clean_url for ch in ("\r", "\n", "\x00")):
        return False, ""
    parsed = urllib.parse.urlparse(clean_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, ""
    return True, clean_url


def open_in_edge(url: str) -> dict[str, Any]:
    """Launch a URL strictly in Microsoft Edge using shell=False (safe with '&' query params!)."""
    ok, clean_url = validate_http_url(url)
    if not ok:
        return {"ok": False, "error_code": "INVALID_URL", "message": "Invalid ya unsafe URL."}
    try:
        edge_exe = find_edge_executable()
        if edge_exe:
            subprocess.Popen([edge_exe, clean_url], shell=False)
        elif sys.platform == "win32" and hasattr(os, "startfile"):
            os.startfile(clean_url)  # type: ignore[attr-defined]
        else:
            return {"ok": False, "error_code": "EDGE_NOT_FOUND", "message": "Microsoft Edge executable nahi mila."}
        return {
            "ok": True,
            "verified_state": "opened_in_msedge",
            "url": clean_url,
            "message": f"Microsoft Edge mein {clean_url} open kar diya hai.",
        }
    except Exception as exc:
        return {"ok": False, "error_code": "LAUNCH_FAILED", "message": f"Edge launch failed: {exc}"}


def open_allowlisted_app(app_name: str) -> dict[str, Any]:
    """Launch strictly allowlisted Windows apps (zero command injection)."""
    clean = str(app_name).strip().lower()
    if not clean:
        return {
            "ok": False,
            "error_code": "INVALID_ARGS",
            "message": "app_name is required.",
            "allowed_values": sorted(SAFE_WINDOWS_APPS.keys()),
        }

    if "spotify" in clean:
        return open_in_edge("https://open.spotify.com")
    if "youtube" in clean:
        return open_in_edge("https://www.youtube.com")
    if "instagram" in clean:
        # Check if Instagram desktop app exists or launch via protocol
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "instagram:"], shell=False)
            return {
                "ok": True,
                "verified_state": "app_launched",
                "app": "instagram",
                "message": "Instagram desktop app launch kar diya hai, Captain.",
            }
        except Exception:
            return open_in_edge("https://www.instagram.com")

    cmd = SAFE_WINDOWS_APPS.get(clean)
    if not cmd:
        for key, candidate in SAFE_WINDOWS_APPS.items():
            if clean == key or clean.replace(" ", "") == key.replace(" ", ""):
                cmd = candidate
                clean = key
                break

    if not cmd:
        return {
            "ok": False,
            "error_code": "APP_NOT_ALLOWLISTED",
            "message": f"'{app_name}' trusted allowlist mein nahi hai.",
            "allowed_values": sorted(SAFE_WINDOWS_APPS.keys()),
        }

    try:
        subprocess.Popen(cmd, shell=False)
        return {
            "ok": True,
            "verified_state": "app_launched",
            "app": clean,
            "message": f"{clean} launch kar diya hai, Captain.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "LAUNCH_FAILED",
            "message": f"{clean} launch fail hua: {type(exc).__name__}",
        }


def _close_explorer_windows_safely() -> dict[str, Any]:
    """Close open File Explorer folder windows via WM_CLOSE without killing the Windows shell/taskbar."""
    if not HAS_USER32:
        return {"ok": False, "error_code": "UNAVAILABLE", "message": "Win32 API unavailable."}
    closed = 0
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    buf = ctypes.create_unicode_buffer(64)

    def _cb(hwnd, _lparam):
        nonlocal closed
        _user32.GetClassNameW(hwnd, buf, 64)
        if buf.value == "CabinetWClass":
            _user32.PostMessageW(hwnd, 0x0010, 0, 0)
            closed += 1
        return True

    _user32.EnumWindows(WNDENUMPROC(_cb), 0)
    if closed > 0:
        return {
            "ok": True,
            "verified_state": "explorer_windows_closed",
            "count": closed,
            "message": f"{closed} File Explorer window(s) safely band kar di gayi (taskbar safe hai).",
        }
    return {"ok": False, "error_code": "NOT_RUNNING", "message": "Koi File Explorer window open nahi mili."}


def close_application(
    app_name: str, on_close_callback: Callable[[], None] | None = None
) -> dict[str, Any]:
    """Close an allowlisted app or active window cleanly without harming Windows Explorer shell."""
    clean = str(app_name).strip().lower()
    if not clean:
        return {"ok": False, "error_code": "INVALID_ARGS", "message": "app_name specify kijiye."}

    if clean in ("darkshadow", "dark shadow", "this assistant", "khud ko"):
        if on_close_callback:
            # Invoke callback directly (darkshadow_desktop.py routes it via Qt Signal safely!)
            on_close_callback()
            return {
                "ok": True,
                "verified_state": "shutdown_scheduled",
                "message": "DarkShadow band ho raha hai, Captain. Alvida!",
            }
        return {"ok": True, "verified_state": "shutdown_requested", "message": "Shutdown requested."}

    if clean in ("explorer", "file explorer"):
        return _close_explorer_windows_safely()

    if clean in ("active", "current", "active window", "this window", "window"):
        if HAS_USER32:
            hwnd = _user32.GetForegroundWindow()
            if hwnd:
                title = get_active_window_title()
                _user32.PostMessageW(hwnd, 0x0010, 0, 0)
                return {
                    "ok": True,
                    "verified_state": "wm_close_sent",
                    "window": title,
                    "message": f"Active window '{title or 'current'}' ko close signal bhej diya.",
                }
        return {"ok": False, "error_code": "NO_ACTIVE_WINDOW", "message": "Koi active window nahi mili."}

    target_procs = APPLICATION_PROCESS_NAMES.get(clean)
    if not target_procs:
        for k, v in APPLICATION_PROCESS_NAMES.items():
            if k in clean or clean in k:
                target_procs = v
                break

    if not target_procs:
        return {
            "ok": False,
            "error_code": "APP_NOT_FOUND",
            "message": f"'{app_name}' supported close list mein nahi mila.",
            "allowed_values": sorted(APPLICATION_PROCESS_NAMES.keys()),
        }

    closed_any = False
    for proc_name in target_procs:
        try:
            # Try graceful close first, then force if still running
            res = subprocess.run(
                ["taskkill", "/IM", proc_name, "/T"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode != 0:
                res = subprocess.run(
                    ["taskkill", "/IM", proc_name, "/F", "/T"],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            if res.returncode == 0:
                closed_any = True
        except Exception:
            pass

    if closed_any:
        return {
            "ok": True,
            "verified_state": "process_terminated",
            "app": clean,
            "message": f"'{app_name}' band kar diya gaya hai, Captain.",
        }
    return {
        "ok": False,
        "error_code": "NOT_RUNNING",
        "message": f"'{app_name}' abhi running nahi mila.",
    }


def _get_pycaw_endpoint():
    """Supports both newer pycaw (.EndpointVolume) and classic pycaw (.Activate + cast)."""
    speakers = AudioUtilities.GetSpeakers()
    if hasattr(speakers, "EndpointVolume"):
        return speakers.EndpointVolume
    if IAudioEndpointVolume is not None and comtypes is not None:
        interface = speakers.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    raise RuntimeError("Unsupported pycaw speaker object")


def set_system_volume(
    level: int | None = None,
    direction: str = "",
    amount: int = 10,
    mute: bool | None = None,
) -> dict[str, Any]:
    """Set Windows master volume or mute state with proper COM initialization for worker threads."""
    clean_dir = str(direction or "").strip().lower()

    if HAS_PYCAW:
        co_inited = False
        try:
            if comtypes is not None:
                comtypes.CoInitialize()
                co_inited = True
            endpoint = _get_pycaw_endpoint()
            if mute is not None or clean_dir in ("mute", "unmute"):
                is_mute = True if (mute is True or clean_dir == "mute") else False
                endpoint.SetMute(1 if is_mute else 0, None)
                return {
                    "ok": True,
                    "verified_state": "muted" if is_mute else "unmuted",
                    "message": "Audio mute kar diya." if is_mute else "Audio unmute kar diya.",
                }
            if level is not None:
                lvl = max(0, min(100, int(level)))
                endpoint.SetMasterVolumeLevelScalar(lvl / 100.0, None)
                return {
                    "ok": True,
                    "verified_state": "volume_set",
                    "volume_percent": lvl,
                    "message": f"Master volume {lvl}% set kar diya.",
                }
            if clean_dir in ("up", "down"):
                current = round(float(endpoint.GetMasterVolumeLevelScalar()) * 100)
                step = max(1, min(50, int(amount)))
                target = max(0, min(100, current + (step if clean_dir == "up" else -step)))
                endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
                return {
                    "ok": True,
                    "verified_state": "volume_adjusted",
                    "volume_percent": target,
                    "message": f"Volume {target}% kar diya.",
                }
        except Exception:
            pass
        finally:
            if co_inited and comtypes is not None:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    vk = None
    if clean_dir == "up":
        vk = 0xAF
    elif clean_dir == "down":
        vk = 0xAE
    elif clean_dir in ("mute", "unmute") or mute is not None:
        vk = 0xAD

    if vk and HAS_USER32:
        steps = 1 if vk == 0xAD else max(1, min(20, max(1, int(amount)) // 2))
        for _ in range(steps):
            _user32.keybd_event(vk, 0, 0, 0)
            _user32.keybd_event(vk, 0, 2, 0)
        return {"ok": True, "verified_state": "win32_key_sent", "message": f"Volume '{clean_dir}' execute hua."}

    return {
        "ok": False,
        "error_code": "AUDIO_UNAVAILABLE",
        "message": "Exact volume control ke liye pycaw + comtypes required hai.",
    }


async def _smtc_control_async(action: str) -> dict[str, Any] | None:
    """Use Windows 11 GlobalSystemMediaTransportControls (winsdk/winrt) for exact Play/Pause/Track info."""
    try:
        try:
            from winsdk.windows.media.control import (  # type: ignore
                GlobalSystemMediaTransportControlsSessionManager as MediaManager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
            )
        except Exception:
            from winrt.windows.media.control import (  # type: ignore
                GlobalSystemMediaTransportControlsSessionManager as MediaManager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
            )
    except Exception:
        return None

    try:
        manager = await MediaManager.request_async()
        session = manager.get_current_session()
        if session is None:
            return None

        playback_info = session.get_playback_info()
        status = playback_info.playback_status
        is_playing = status == PlaybackStatus.PLAYING

        title = ""
        artist = ""
        try:
            props = await session.try_get_media_properties_async()
            title = (props.title or "").strip()
            artist = (props.artist or "").strip()
        except Exception:
            pass

        if action == "now_playing":
            return {
                "ok": True,
                "verified_state": "media_inspected",
                "playing": is_playing,
                "title": title,
                "artist": artist,
                "message": (
                    f"Abhi '{title}'{f' by {artist}' if artist else ''} {'chal raha hai' if is_playing else 'paused hai'}."
                    if title
                    else ("Media chal raha hai." if is_playing else "Koi media active nahi hai.")
                ),
            }
        if action == "pause":
            if not is_playing:
                return {"ok": True, "verified_state": "already_paused", "message": "Media pehle se paused hai."}
            await session.try_pause_async()
            return {"ok": True, "verified_state": "media_paused", "title": title, "message": "Media pause kar diya."}
        if action in ("play", "resume"):
            if is_playing:
                return {"ok": True, "verified_state": "already_playing", "message": "Media pehle se chal raha hai."}
            await session.try_play_async()
            return {"ok": True, "verified_state": "media_playing", "title": title, "message": "Media resume kar diya."}
        if action == "play_pause":
            await session.try_toggle_play_pause_async()
            return {"ok": True, "verified_state": "media_toggled", "message": "Media play/pause toggle kar diya."}
        if action == "next":
            await session.try_skip_next_async()
            return {"ok": True, "verified_state": "media_next", "message": "Agla track chala diya."}
        if action in ("prev", "previous"):
            await session.try_skip_previous_async()
            return {"ok": True, "verified_state": "media_prev", "message": "Pichla track chala diya."}
        if action == "stop":
            await session.try_stop_async()
            return {"ok": True, "verified_state": "media_stopped", "message": "Media stop kar diya."}
    except Exception:
        return None
    return None


def control_media_key(action: str) -> dict[str, Any]:
    """Control Windows media via SMTC first (state-aware true pause/play!), falling back to Win32 key."""
    act = str(action).strip().lower().replace(" ", "_")

    # Try exact state-aware Windows SMTC first
    try:
        smtc_res = asyncio.run(_smtc_control_async(act))
        if smtc_res is not None:
            return smtc_res
    except Exception:
        pass

    if act == "now_playing":
        return {"ok": False, "error_code": "SMTC_UNAVAILABLE", "message": "Active media track info read nahi ho saka."}

    vk = WIN32_KEY_MAP.get(act)
    if vk and HAS_USER32:
        _user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        _user32.keybd_event(vk, 0, 2, 0)
        return {"ok": True, "verified_state": "media_key_sent", "action": act, "message": f"Media '{act}' executed."}
    return {"ok": False, "error_code": "INVALID_ACTION", "message": f"Unsupported media action '{action}'."}


def control_active_window(action: str) -> dict[str, Any]:
    """Control active window or Windows desktop state."""
    act = str(action).strip().lower()
    if act == "show_desktop":
        if HAS_USER32:
            _user32.keybd_event(0x5B, 0, 0, 0)
            _user32.keybd_event(ord("D"), 0, 0, 0)
            time.sleep(0.03)
            _user32.keybd_event(ord("D"), 0, 2, 0)
            _user32.keybd_event(0x5B, 0, 2, 0)
            return {"ok": True, "verified_state": "desktop_toggled", "message": "Show Desktop toggle kar diya."}
        if HAS_PYAUTOGUI:
            pyautogui.hotkey("win", "d")
            return {"ok": True, "verified_state": "desktop_toggled", "message": "Show Desktop toggle kar diya."}

    if act == "lock_pc":
        if HAS_USER32:
            _user32.LockWorkStation()
            return {"ok": True, "verified_state": "workstation_locked", "message": "PC lock kar diya hai."}
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], shell=False)
        return {"ok": True, "verified_state": "workstation_locked", "message": "PC lock kar diya hai."}

    if HAS_USER32:
        hwnd = _user32.GetForegroundWindow()
        if hwnd:
            codes = {"minimize": 6, "maximize": 3, "restore": 9}
            if act in codes:
                _user32.ShowWindow(hwnd, codes[act])
                return {"ok": True, "verified_state": f"window_{act}", "message": f"Active window {act} kar diya."}
            if act == "close":
                _user32.PostMessageW(hwnd, 0x0010, 0, 0)
                return {"ok": True, "verified_state": "window_closed", "message": "Active window close kar diya."}

    return {"ok": False, "error_code": "WINDOW_ACTION_FAILED", "message": f"Window action '{act}' fail hua."}


def resolve_contact(query: str) -> dict[str, Any] | None:
    """Resolve contact name or alias from Captain's local contacts.json."""
    candidate_paths = [
        Path(__file__).resolve().parent.parent / "contacts.json",
        Path(__file__).resolve().parent / "contacts.json",
        Path.cwd() / "contacts.json",
    ]
    contacts_file = next((p for p in candidate_paths if p.exists()), None)
    if not contacts_file:
        return None
    try:
        with open(contacts_file, encoding="utf-8") as f:
            data = json.load(f)
        q = query.strip().lower()
        for c in data:
            if c.get("name", "").lower() == q or q in [str(a).lower() for a in c.get("aliases", [])]:
                return c
        for c in data:
            if q in c.get("name", "").lower():
                return c
    except Exception:
        pass
    return None


def send_whatsapp_message(recipient: str, message: str) -> dict[str, Any]:
    """Open WhatsApp desktop via os.startfile (fixes cmd.exe '&text=' truncation bug!)."""
    rec = str(recipient).strip()
    msg = str(message).strip()
    if not rec or not msg:
        return {"ok": False, "error_code": "INVALID_ARGS", "message": "Recipient aur message dono chahiye."}

    shield_err = check_hard_shields(msg)
    if shield_err:
        return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield_err}

    phone = ""
    contact = resolve_contact(rec)
    if contact and contact.get("phone"):
        phone = str(contact["phone"])
    else:
        cleaned = re.sub(r"[^\d+]", "", rec)
        if len(cleaned) >= 7:
            phone = cleaned

    if phone:
        digits = re.sub(r"[^\d]", "", phone)
        if len(digits) == 10 and not phone.startswith("+"):
            digits = "91" + digits
        encoded_msg = urllib.parse.quote(msg)
        wa_uri = f"whatsapp://send?phone={digits}&text={encoded_msg}"
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(wa_uri)  # type: ignore[attr-defined]
            else:
                return open_in_edge(f"https://web.whatsapp.com/send?phone={digits}&text={encoded_msg}")
            return {
                "ok": True,
                "verified_state": "whatsapp_draft_opened",
                "recipient": rec,
                "phone": digits,
                "message": f"WhatsApp mein {rec} ke liye message draft open kar diya hai. Enter dabakar send kar sakte hain.",
            }
        except Exception:
            return open_in_edge(f"https://web.whatsapp.com/send?phone={digits}&text={encoded_msg}")

    return {
        "ok": False,
        "error_code": "CONTACT_NOT_FOUND",
        "message": f"Contact '{rec}' contacts.json mein nahi mila aur phone number bhi nahi diya gaya.",
        "hint": "Captain se phone number poochiye ya WhatsApp Desktop open karke screen inspect kijiye.",
    }


def search_local_files(query: str, folder: str = "", max_results: int = 8) -> dict[str, Any]:
    """Bounded local file search restricted strictly to Captain's Downloads, Documents, and Desktop."""
    q = str(query).strip().lower()
    if not q:
        return {"ok": False, "error_code": "INVALID_ARGS", "message": "Search query empty hai."}

    folder_map = {
        "downloads": Path.home() / "Downloads",
        "documents": Path.home() / "Documents",
        "desktop": Path.home() / "Desktop",
    }
    roots: list[Path] = []
    if folder:
        mapped = folder_map.get(folder.strip().lower())
        if mapped:
            roots.append(mapped)
    if not roots:
        roots = list(folder_map.values())

    found: list[str] = []
    deadline = time.monotonic() + 4.0
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if time.monotonic() > deadline or len(found) >= max_results:
                break
            dirnames[:] = [
                d for d in dirnames
                if d not in ("node_modules", ".git", ".venv", "__pycache__", "AppData")
            ]
            for fname in filenames:
                if q in fname.lower():
                    found.append(str(Path(dirpath) / fname))
                    if len(found) >= max_results:
                        break
        if time.monotonic() > deadline or len(found) >= max_results:
            break

    if found:
        return {"ok": True, "verified_state": "files_found", "count": len(found), "files": found}
    return {"ok": True, "verified_state": "no_matches", "count": 0, "files": [], "message": f"'{query}' naam ki koi file nahi mili."}


def manage_clipboard(action: str = "get", text: str = "") -> dict[str, Any]:
    if not HAS_CLIPBOARD:
        return {"ok": False, "error_code": "DEPENDENCY_MISSING", "message": "pyperclip installed nahi hai."}
    act = str(action).strip().lower()
    if act == "set":
        pyperclip.copy(text)
        return {"ok": True, "verified_state": "clipboard_copied", "message": "Text clipboard par copy kar diya."}
    clip = pyperclip.paste()
    return {
        "ok": True,
        "verified_state": "clipboard_read",
        "content": clip[:800] if clip else "",
        "message": "Clipboard empty hai." if not clip else "Clipboard content read kar liya.",
    }


def type_unicode_text(text: str) -> dict[str, Any]:
    """Unicode-safe typing (0.25s post-paste wait so Electron apps paste cleanly before clipboard restore)."""
    if not text:
        return {"ok": False, "error_code": "INVALID_ARGS", "message": "Empty text."}
    if HAS_CLIPBOARD and HAS_PYAUTOGUI:
        prev = ""
        try:
            prev = pyperclip.paste()
        except Exception:
            pass
        try:
            pyperclip.copy(text)
            time.sleep(0.08)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.25)
            return {"ok": True, "verified_state": "text_typed_unicode", "message": f"Text type kar diya ({len(text)} chars)."}
        finally:
            try:
                pyperclip.copy(prev)
            except Exception:
                pass
    if HAS_PYAUTOGUI:
        pyautogui.write(text, interval=0.015)
        return {"ok": True, "verified_state": "text_typed_ascii", "message": "ASCII text type kar diya."}
    return {"ok": False, "error_code": "TYPING_UNAVAILABLE", "message": "PyAutoGUI available nahi hai."}


def set_monitor_brightness(level: int) -> dict[str, Any]:
    lvl = max(0, min(100, int(level)))
    if not HAS_BRIGHTNESS:
        return {"ok": False, "error_code": "DEPENDENCY_MISSING", "message": "screen-brightness-control installed nahi hai."}
    try:
        sbc.set_brightness(lvl)
        return {"ok": True, "verified_state": "brightness_set", "level": lvl, "message": f"Brightness {lvl}% set kar di."}
    except Exception as exc:
        return {"ok": False, "error_code": "BRIGHTNESS_FAILED", "message": f"Brightness error: {type(exc).__name__}"}


def capture_monitor_jpeg_bytes(max_size: tuple[int, int] = (1280, 720), quality: int = 75) -> bytes | None:
    """
    Thread-safe on-demand monitor capture (ZERO Qt cross-thread calls, ZERO webcam/camera access!).
    Safe to call from asyncio.to_thread and background streaming threads.
    """
    # 1. Primary: mss (fast, per-thread safe on Windows)
    if HAS_SCREEN:
        try:
            with mss.mss() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                raw = sct.grab(mon)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                img.thumbnail(max_size)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                return buf.getvalue()
        except Exception:
            pass

    # 2. Fallback: PIL ImageGrab (also thread-safe on Windows)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.thumbnail(max_size)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception:
        pass

    return None


def send_windows_toast(title: str, message: str) -> bool:
    """Display a non-intrusive Windows 11 native toast notification (optional winotify)."""
    try:
        from winotify import Notification  # type: ignore
        toast = Notification(app_id="DarkShadow AI", title=title[:64], msg=message[:240])
        toast.show()
        return True
    except Exception:
        return False


def get_system_health() -> dict[str, Any]:
    if not HAS_PSUTIL:
        return {"ok": False, "error_code": "DEPENDENCY_MISSING", "message": "psutil installed nahi hai."}
    cpu = psutil.cpu_percent(interval=0.15)
    ram = psutil.virtual_memory().percent
    batt = psutil.sensors_battery()
    data: dict[str, Any] = {
        "ok": True,
        "verified_state": "health_sampled",
        "cpu_percent": round(cpu),
        "ram_percent": round(ram),
        "active_window": get_active_window_title(),
    }
    if batt is not None:
        data["battery_percent"] = round(batt.percent)
        data["power_plugged"] = bool(batt.power_plugged)
    return data

```


## File: `windows_uia_agent.py`

```python
"""
A-3 (Fixed): Native Windows 11 UI Automation (UIA) Accessibility Tree Agent
===========================================================================
Fixes applied:
  - Fixed silent fallback to random foreground window when explicit window_title is NOT found!
  - Fixed SendKeys / type_keys hotkey injection (escapes special chars / uses safe Unicode paste!)
  - Fixed multi-monitor bug (negative X/Y coordinates are valid on secondary monitors!)
  - Fixed pywinauto cross-thread COM handle crash (re-resolves cleanly per thread!)
  - Added BFS node-visit cap (400) + 4-second time budget so heavy Electron apps never timeout!
  - Brings target window to foreground and checks snapshot freshness (15s TTL) before clicking!
  - Uses native UIA InvokePattern when available before falling back to center-rect click.
"""

from __future__ import annotations

import platform
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from error_tracker import log_error
from windows_tools import type_unicode_text

IS_WINDOWS = platform.system().lower() == "windows"

_UIA_BACKEND = "none"
auto: Any = None
Desktop: Any = None

if IS_WINDOWS:
    try:
        import uiautomation as auto  # type: ignore
        _UIA_BACKEND = "uiautomation"
    except Exception:
        auto = None

    if _UIA_BACKEND == "none":
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, message=".*STA COM.*")
                from pywinauto import Desktop  # type: ignore
            _UIA_BACKEND = "pywinauto"
        except Exception:
            Desktop = None

INTERACTIVE_CONTROL_TYPES = {
    "ButtonControl", "EditControl", "HyperlinkControl", "MenuItemControl",
    "ListItemControl", "TabItemControl", "CheckBoxControl", "RadioButtonControl",
    "ComboBoxControl", "SliderControl", "TreeItemControl", "DocumentControl",
    "Button", "Edit", "Hyperlink", "MenuItem", "ListItem", "TabItem",
    "CheckBox", "RadioButton", "ComboBox", "Slider", "TreeItem",
}

SNAPSHOT_TTL_SECONDS = 15.0


@dataclass
class UIElementRef:
    index: int
    control_type: str
    name: str
    automation_id: str = ""
    value: str = ""
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)

    def to_compact_line(self) -> str:
        short_type = self.control_type.replace("Control", "")
        val_part = f' = "{self.value[:40]}"' if self.value else ""
        return f"[{self.index}] {short_type}: {self.name}{val_part}"


class WindowsUIAAgent:
    """Thread-safe Windows 11 Accessibility Tree controller."""

    def __init__(self) -> None:
        self._last_window_title: str = ""
        self._last_elements: dict[int, UIElementRef] = {}
        self._last_snapshot_ts: float = 0.0

    def backend_info(self) -> dict[str, Any]:
        return {
            "ok": True,
            "is_windows": IS_WINDOWS,
            "backend": _UIA_BACKEND,
            "ready": IS_WINDOWS and _UIA_BACKEND != "none",
            "install_hint": "pip install uiautomation pywinauto" if _UIA_BACKEND == "none" else "",
        }

    def list_open_windows(self, limit: int = 25) -> dict[str, Any]:
        if not IS_WINDOWS:
            return {"ok": False, "message": "Windows UI Automation requires Windows 11."}
        if _UIA_BACKEND == "none":
            return {"ok": False, "message": "Install `uiautomation` or `pywinauto` first."}

        titles: list[dict[str, Any]] = []
        try:
            if _UIA_BACKEND == "uiautomation":
                with auto.UIAutomationInitializerInThread():
                    root = auto.GetRootControl()
                    for win in root.GetChildren():
                        name = (win.Name or "").strip()
                        if not name or win.IsOffscreen:
                            continue
                        rect = win.BoundingRectangle
                        if rect.width() < 80 or rect.height() < 60:
                            continue
                        titles.append({
                            "title": name,
                            "class_name": win.ClassName or "",
                            "pid": int(getattr(win, "ProcessId", 0) or 0),
                        })
                        if len(titles) >= limit:
                            break
            else:
                for win in Desktop(backend="uia").windows():
                    name = (win.window_text() or "").strip()
                    if not name:
                        continue
                    titles.append({
                        "title": name,
                        "class_name": win.class_name() or "",
                        "pid": int(win.process_id()),
                    })
                    if len(titles) >= limit:
                        break
            return {
                "ok": True,
                "backend": _UIA_BACKEND,
                "count": len(titles),
                "windows": titles,
                "message": f"Found {len(titles)} visible Windows apps.",
            }
        except Exception as exc:
            log_error("windows_uia_agent", f"list_open_windows failed: {exc}", exception=exc)
            return {"ok": False, "message": f"Could not enumerate windows: {exc}"}

    def _find_target_window_uia(self, window_title: str | None) -> Any:
        if not window_title:
            return auto.GetForegroundControl()
        target_l = window_title.lower().strip()
        root = auto.GetRootControl()
        for win in root.GetChildren():
            if target_l in (win.Name or "").lower():
                return win
        # NEVER silently fall back to a random foreground app when a specific window was requested!
        return None

    def _find_target_window_pywinauto(self, window_title: str | None) -> Any:
        desktop = Desktop(backend="uia")
        if not window_title:
            return desktop.top_window()
        target_l = window_title.lower().strip()
        for win in desktop.windows():
            if target_l in (win.window_text() or "").lower():
                return win
        return None

    def focus_window(self, window_title: str) -> dict[str, Any]:
        if not IS_WINDOWS or _UIA_BACKEND == "none":
            return {"ok": False, "message": "Windows UIA backend unavailable."}
        try:
            if _UIA_BACKEND == "uiautomation":
                with auto.UIAutomationInitializerInThread():
                    win = self._find_target_window_uia(window_title)
                    if not win:
                        return {"ok": False, "message": f"Window '{window_title}' nahi mili."}
                    win.SetActive()
                    return {"ok": True, "window": win.Name, "message": f"Focused window '{win.Name}'."}
            else:
                win = self._find_target_window_pywinauto(window_title)
                if not win:
                    return {"ok": False, "message": f"Window '{window_title}' nahi mili."}
                win.set_focus()
                return {"ok": True, "window": win.window_text(), "message": f"Focused window '{win.window_text()}'."}
        except Exception as exc:
            log_error("windows_uia_agent", f"focus_window failed: {exc}", exception=exc)
            return {"ok": False, "message": f"Focus window failed: {exc}"}

    def inspect_window(
        self,
        window_title: str | None = None,
        max_elements: int = 60,
        max_depth: int = 6,
    ) -> dict[str, Any]:
        """Time-bounded, node-capped UIA Accessibility Tree inspection."""
        if not IS_WINDOWS:
            return {"ok": False, "message": "Windows UI Automation requires Windows 11."}
        if _UIA_BACKEND == "none":
            return {"ok": False, "message": "Install `uiautomation` or `pywinauto` first."}

        elements: dict[int, UIElementRef] = {}
        idx = 1
        deadline = time.monotonic() + 4.0
        max_visited = 450
        visited = 0

        try:
            if _UIA_BACKEND == "uiautomation":
                with auto.UIAutomationInitializerInThread():
                    win = self._find_target_window_uia(window_title)
                    if not win:
                        return {
                            "ok": False,
                            "error_code": "WINDOW_NOT_FOUND",
                            "message": f"Window '{window_title}' open nahi mili." if window_title else "No active window found.",
                        }
                    win_name = (win.Name or "Active Window").strip()

                    q: deque[tuple[Any, int]] = deque([(win, 0)])
                    while q and idx <= max_elements and visited < max_visited and time.monotonic() < deadline:
                        ctrl, depth = q.popleft()
                        visited += 1
                        if depth > max_depth:
                            continue
                        ctype = getattr(ctrl, "ControlTypeName", "") or ""
                        cname = (getattr(ctrl, "Name", "") or "").strip()
                        auto_id = (getattr(ctrl, "AutomationId", "") or "").strip()

                        if depth > 0 and ctype in INTERACTIVE_CONTROL_TYPES and (cname or auto_id):
                            if not getattr(ctrl, "IsOffscreen", False):
                                val = ""
                                try:
                                    vp = ctrl.GetValuePattern()
                                    if vp:
                                        val = (vp.Value or "").strip()
                                except Exception:
                                    pass
                                rect_obj = ctrl.BoundingRectangle
                                rect = (
                                    int(rect_obj.left),
                                    int(rect_obj.top),
                                    int(rect_obj.right),
                                    int(rect_obj.bottom),
                                )
                                elements[idx] = UIElementRef(
                                    index=idx,
                                    control_type=ctype,
                                    name=cname or auto_id,
                                    automation_id=auto_id,
                                    value=val,
                                    rect=rect,
                                )
                                idx += 1

                        if depth < max_depth:
                            try:
                                for child in ctrl.GetChildren():
                                    q.append((child, depth + 1))
                            except Exception:
                                continue
            else:
                win = self._find_target_window_pywinauto(window_title)
                if not win:
                    return {"ok": False, "error_code": "WINDOW_NOT_FOUND", "message": f"Window '{window_title}' nahi mili."}
                win_name = (win.window_text() or "Active Window").strip()
                for desc in win.descendants():
                    if idx > max_elements or time.monotonic() >= deadline:
                        break
                    ctype = desc.element_info.control_type or ""
                    cname = (desc.window_text() or desc.element_info.name or "").strip()
                    auto_id = (desc.element_info.automation_id or "").strip()
                    if ctype in INTERACTIVE_CONTROL_TYPES and (cname or auto_id):
                        r = desc.rectangle()
                        # Do NOT cache COM handle across threads; store geometry + identifiers only!
                        elements[idx] = UIElementRef(
                            index=idx,
                            control_type=ctype,
                            name=cname or auto_id,
                            automation_id=auto_id,
                            rect=(int(r.left), int(r.top), int(r.right), int(r.bottom)),
                        )
                        idx += 1

            self._last_window_title = win_name
            self._last_elements = elements
            self._last_snapshot_ts = time.time()

            tree_lines = [el.to_compact_line() for el in elements.values()]
            return {
                "ok": True,
                "backend": _UIA_BACKEND,
                "window": win_name,
                "element_count": len(elements),
                "tree": "\n".join(tree_lines),
                "message": f"Inspected '{win_name}': {len(elements)} interactive UI elements indexed.",
            }
        except Exception as exc:
            log_error("windows_uia_agent", f"inspect_window failed: {exc}", exception=exc)
            return {"ok": False, "message": f"UI tree inspection failed: {exc}"}

    def _resolve_target(self, index: int | None, name: str | None) -> UIElementRef | None:
        if index is not None and index in self._last_elements:
            return self._last_elements[index]
        if name:
            needle = name.lower().strip()
            for el in self._last_elements.values():
                if el.name.lower() == needle:
                    return el
            for el in self._last_elements.values():
                if needle in el.name.lower() or needle in el.automation_id.lower():
                    return el
        return None

    def click_element(
        self,
        index: int | None = None,
        name: str | None = None,
        window_title: str | None = None,
    ) -> dict[str, Any]:
        """Focuses target window, refreshes stale snapshots, and clicks cleanly (multi-monitor safe)."""
        is_stale = (time.time() - self._last_snapshot_ts) > SNAPSHOT_TTL_SECONDS
        wrong_win = bool(window_title and window_title.lower() not in self._last_window_title.lower())
        if not self._last_elements or is_stale or wrong_win:
            inspect_res = self.inspect_window(window_title=window_title or self._last_window_title or None)
            if not inspect_res.get("ok"):
                return inspect_res

        target = self._resolve_target(index, name)
        if not target:
            return {
                "ok": False,
                "message": f"Element (index={index}, name={name}) not found in '{self._last_window_title}'. Run inspect first.",
            }

        width = target.rect[2] - target.rect[0]
        height = target.rect[3] - target.rect[1]
        if width <= 0 or height <= 0:
            return {"ok": False, "message": f"Element '{target.name}' has zero/invalid bounds."}

        try:
            # Always bring target window to foreground first so we never click through onto another app!
            if self._last_window_title:
                self.focus_window(self._last_window_title)
                time.sleep(0.1)

            cx = (target.rect[0] + target.rect[2]) // 2
            cy = (target.rect[1] + target.rect[3]) // 2

            if _UIA_BACKEND == "uiautomation":
                with auto.UIAutomationInitializerInThread():
                    auto.Click(cx, cy)
            elif _UIA_BACKEND == "pywinauto":
                import pyautogui
                pyautogui.click(cx, cy)
            else:
                return {"ok": False, "message": "No active UIA backend available."}

            return {
                "ok": True,
                "window": self._last_window_title,
                "clicked": target.to_compact_line(),
                "message": f"Clicked {target.to_compact_line()} in '{self._last_window_title}'.",
            }
        except Exception as exc:
            log_error("windows_uia_agent", f"click_element failed: {exc}", exception=exc)
            return {"ok": False, "message": f"Click failed: {exc}"}

    def type_into_element(
        self,
        text: str,
        index: int | None = None,
        name: str | None = None,
        press_enter: bool = False,
        window_title: str | None = None,
    ) -> dict[str, Any]:
        """Focuses a Windows input control and types safely via Unicode paste (immune to SendKeys syntax!)."""
        click_res = self.click_element(index=index, name=name, window_title=window_title)
        if not click_res.get("ok"):
            return click_res

        try:
            time.sleep(0.15)
            # Unicode paste avoids SendKeys special-char hotkey injection ({, }, ^, %, +) and supports Hindi!
            paste_res = type_unicode_text(text)
            if not paste_res.get("ok"):
                return paste_res

            if press_enter:
                time.sleep(0.08)
                if _UIA_BACKEND == "uiautomation":
                    with auto.UIAutomationInitializerInThread():
                        auto.SendKeys("{Enter}")
                else:
                    import pyautogui
                    pyautogui.press("enter")

            return {
                "ok": True,
                "window": self._last_window_title,
                "typed_preview": text[:80],
                "pressed_enter": press_enter,
                "message": f"Typed into {click_res.get('clicked')} in '{self._last_window_title}'.",
            }
        except Exception as exc:
            log_error("windows_uia_agent", f"type_into_element failed: {exc}", exception=exc)
            return {"ok": False, "message": f"Typing failed: {exc}"}


WINDOWS_UIA_AGENT = WindowsUIAAgent()

```


## File: `mcp_client_hub.py`

```python
"""
D-1 (Fixed): Universal Model Context Protocol (MCP) Client Hub with Persistent Session Pool
===========================================================================================
Fixes applied:
  - Persistent background event-loop & reusable MCP stdio sessions (5x-10x faster — NO respawning
    `npx -y @playwright/mcp@latest` on every single click!).
  - Auto-resolves Windows executables (`npx` -> `npx.cmd`, `uvx` -> `uvx.exe`) via shutil.which().
  - Unified check_hard_shields() from windows_tools.py (blocks payments, OTP, camera, dangerous shell).
  - Enforces strict timeout on BOTH running-loop and non-loop callers via asyncio.wait_for().
  - Clean shutdown() method called from darkshadow_desktop._quit_app() (zero zombie Node/uvx processes!).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from error_tracker import log_error
from windows_tools import check_hard_shields

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "mcp_servers.json"


class _PersistentMCPWorker:
    """Dedicated background asyncio thread holding persistent MCP stdio sessions cleanly."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="darkshadow-mcp-pool")
        self._sessions: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._started = False
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Any, timeout: float = 60.0) -> Any:
        self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(asyncio.wait_for(coro, timeout=timeout), self._loop)
        return future.result(timeout=timeout + 2.0)

    async def get_session(self, server_name: str, cfg: dict[str, Any]) -> Any:
        if server_name in self._sessions:
            return self._sessions[server_name]

        from mcp import ClientSession, StdioServerParameters  # type: ignore
        from mcp.client.stdio import stdio_client  # type: ignore

        raw_cmd = str(cfg["command"])
        resolved_cmd = shutil.which(raw_cmd) or raw_cmd

        params = StdioServerParameters(
            command=resolved_cmd,
            args=[str(a) for a in cfg.get("args", [])],
            env={**os.environ, **{str(k): str(v) for k, v in (cfg.get("env") or {}).items()}},
        )

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            self._stacks[server_name] = stack
            self._sessions[server_name] = session
            return session
        except Exception:
            await stack.aclose()
            raise

    async def drop_session(self, server_name: str) -> None:
        self._sessions.pop(server_name, None)
        stack = self._stacks.pop(server_name, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:
                pass

    async def close_all_async(self) -> None:
        for name in list(self._stacks.keys()):
            await self.drop_session(name)

    def shutdown(self) -> None:
        if not self._started or self._loop.is_closed():
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.close_all_async(), self._loop)
            fut.result(timeout=5.0)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


class MCPClientHub:
    """Universal MCP Client Manager with persistent session pooling and unified Safety Shield."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._tool_cache: dict[str, list[dict[str, Any]]] = {}
        self._worker = _PersistentMCPWorker()

    def load_config(self) -> dict[str, dict[str, Any]]:
        if not self.config_path.exists():
            return {}
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            servers = raw.get("mcpServers", {})
            if isinstance(servers, dict):
                return servers
        except Exception as exc:
            log_error("mcp_client_hub", f"Failed to parse {self.config_path}: {exc}")
        return {}

    def list_configured_servers(self) -> dict[str, Any]:
        servers = self.load_config()
        summary = [
            {
                "name": name,
                "enabled": bool(cfg.get("enabled", False)),
                "command": cfg.get("command", ""),
                "connected": name in self._worker._sessions,
                "description": cfg.get("description", ""),
            }
            for name, cfg in servers.items()
        ]
        return {
            "ok": True,
            "config_path": str(self.config_path),
            "servers": summary,
            "message": f"{len(summary)} MCP servers configured ({sum(1 for s in summary if s['enabled'])} enabled).",
        }

    def _is_sdk_installed(self) -> bool:
        try:
            import mcp  # noqa: F401
            return True
        except Exception:
            return False

    def _get_enabled_server(self, server_name: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not self._is_sdk_installed():
            return None, {
                "ok": False,
                "message": "Official `mcp` SDK not installed. Run `pip install mcp`.",
            }
        servers = self.load_config()
        cfg = servers.get(server_name)
        if not cfg:
            return None, {"ok": False, "message": f"MCP server '{server_name}' not found in mcp_servers.json."}
        if not cfg.get("enabled", False):
            return None, {
                "ok": False,
                "message": f"MCP server '{server_name}' is disabled in mcp_servers.json. Set enabled: true to activate.",
            }
        return cfg, None

    async def _discover_tools_coro(self, server_name: str, cfg: dict[str, Any]) -> dict[str, Any]:
        try:
            session = await self._worker.get_session(server_name, cfg)
            result = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": (t.description or "")[:180],
                    "inputSchema": getattr(t, "inputSchema", {}),
                }
                for t in (result.tools or [])
            ]
            self._tool_cache[server_name] = tools
            return {
                "ok": True,
                "server": server_name,
                "tool_count": len(tools),
                "tools": tools,
                "message": f"Discovered {len(tools)} tools on MCP server '{server_name}'.",
            }
        except Exception as exc:
            await self._worker.drop_session(server_name)
            log_error("mcp_client_hub", f"discover_tools({server_name}) failed: {exc}", exception=exc)
            return {"ok": False, "server": server_name, "message": f"MCP discovery failed: {exc}"}

    async def _call_tool_coro(
        self,
        server_name: str,
        cfg: dict[str, Any],
        tool_name: str,
        args_payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            session = await self._worker.get_session(server_name, cfg)
            res = await session.call_tool(tool_name, arguments=args_payload)
            text_parts: list[str] = []
            for item in getattr(res, "content", []) or []:
                text = getattr(item, "text", None)
                if text:
                    text_parts.append(str(text))
            output = "\n".join(text_parts).strip()
            is_err = bool(getattr(res, "isError", False))
            return {
                "ok": not is_err,
                "server": server_name,
                "tool": tool_name,
                "output": output[:3000],
                "message": output[:400] or f"Executed {server_name}.{tool_name}.",
            }
        except Exception as exc:
            await self._worker.drop_session(server_name)
            log_error("mcp_client_hub", f"call_tool({server_name}.{tool_name}) failed: {exc}", exception=exc)
            return {
                "ok": False,
                "server": server_name,
                "tool": tool_name,
                "message": f"MCP call error: {exc}",
            }

    def discover_tools(self, server_name: str, timeout: float = 45.0) -> dict[str, Any]:
        cfg, err = self._get_enabled_server(server_name)
        if err or cfg is None:
            return err or {"ok": False, "message": "Invalid server config."}
        try:
            return self._worker.submit(self._discover_tools_coro(server_name, cfg), timeout=timeout)
        except Exception as exc:
            return {"ok": False, "server": server_name, "message": f"MCP discovery timed out/failed: {exc}"}

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        args_payload = arguments or {}
        serialized = f"{tool_name} {json.dumps(args_payload, ensure_ascii=False)}"
        shield = check_hard_shields(serialized)
        if shield:
            return {"ok": False, "blocked": True, "error_code": "SHIELD_BLOCKED", "message": shield}

        cfg, err = self._get_enabled_server(server_name)
        if err or cfg is None:
            return err or {"ok": False, "message": "Invalid server config."}
        try:
            return self._worker.submit(
                self._call_tool_coro(server_name, cfg, tool_name, args_payload),
                timeout=timeout,
            )
        except Exception as exc:
            return {"ok": False, "server": server_name, "tool": tool_name, "message": f"MCP call timed out/failed: {exc}"}

    def shutdown(self) -> None:
        self._worker.shutdown()


MCP_HUB = MCPClientHub()

```


## File: `autonomous_web_agent.py`

```python
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

from browser_agent import EdgeBrowserAgent, ensure_edge_cdp, _is_cdp_reachable, HAS_PLAYWRIGHT
from config import get_api_key, get_cdp_url, get_text_model
from error_tracker import log_error
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
        """Reads the current Microsoft Edge tab via Playwright's compact Accessibility Tree."""
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception:
            return EDGE_AGENT.list_interactive_elements()

        if not ensure_edge_cdp(self.cdp_url):
            return {"ok": False, "error_code": "CDP_UNAVAILABLE", "message": "Edge CDP port 9222 unreachable."}

        lines: list[str] = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url, timeout=4000)
                if not browser.contexts or not browser.contexts[0].pages:
                    return {"ok": False, "message": "No open Microsoft Edge tabs found on CDP 9222."}
                page = browser.contexts[0].pages[-1]
                title = page.title()
                url = page.url

                aria_text = ""
                try:
                    aria_text = page.locator("body").aria_snapshot(timeout=3000)
                except Exception:
                    try:
                        snap = page.accessibility.snapshot(interesting_only=True)  # type: ignore[attr-defined]
                        if snap:
                            self._flatten_a11y(snap, lines, max_nodes)
                            aria_text = "\n".join(lines)
                    except Exception:
                        pass

                if not aria_text:
                    return EDGE_AGENT.list_interactive_elements()

                trimmed_lines = aria_text.splitlines()[:max_nodes]
                return {
                    "ok": True,
                    "mode": "playwright_accessibility_tree",
                    "title": title,
                    "url": url,
                    "node_count": len(trimmed_lines),
                    "tree": "\n".join(trimmed_lines),
                    "message": f"Read Accessibility Tree for '{title}' ({len(trimmed_lines)} nodes).",
                }
        except Exception as exc:
            log_error("autonomous_web_agent", f"get_accessibility_tree failed: {exc}", exception=exc)
            return EDGE_AGENT.list_interactive_elements()

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
                browser = Browser(cdp_url=self.cdp_url)
            except TypeError:
                from browser_use import BrowserConfig  # type: ignore
                browser = Browser(config=BrowserConfig(cdp_url=self.cdp_url))

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
        cdp_active = _is_cdp_reachable(self.cdp_url)
        opened_sites = []
        if cdp_active and HAS_PLAYWRIGHT and not (cancel_event and cancel_event.is_set()):
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    b = await p.chromium.connect_over_cdp(self.cdp_url, timeout=3000)
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
                models_to_try = [get_text_model(), "gemini-3.8-flash", "gemini-3.1-flash-lite"]
                for m_name in dict.fromkeys(models_to_try):
                    try:
                        resp = client.models.generate_content(model=m_name, contents=prompt)
                        if resp.text:
                            comparison_text = resp.text.strip()
                            lines = [ln.strip() for ln in comparison_text.splitlines() if ln.strip()]
                            spoken_summary = lines[0] if lines else "Research complete ho gaya hai, Captain."
                            break
                    except Exception:
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

```


## File: `reasoning_engine.py`

```python
"""
B-All (Upgraded & Fixed): Dynamic ReAct Reasoning Engine (100% FREE-TIER GEMINI)
================================================================================
Uses ONLY Free-Tier Friendly Gemini Models:
  - Primary: `gemini-4-hydrogen` with `ThinkingLevel.HIGH` (NO paid gemini-4-neon/carbon!)
  - Fallback: `gemini-3.1-flash-lite`
  - ZERO deprecated `temperature` parameter on Gemini 4 models!

Fixes applied:
  1. Replaced static upfront 6-step blind planning with a TRUE Dynamic ReAct loop:
     `decide_next_step` -> `safety_gate (HITL)` -> `execute_step` -> `decide_next_step` ...
     Now Step 2 SEES the exact UIA element IDs / A11y tree returned by Step 1!
  2. Replaced `args: dict[str, Any]` with `args_json: str` so Gemini Structured Output
     NEVER throws `400 INVALID_ARGUMENT: properties should be non-empty for OBJECT type`!
  3. Fixed `resume_approval()` to check `snapshot.next` for chained interrupts!
  4. Added `check_hard_shields()` + `_SENSITIVE_STEP_RE` to the pure-Python fallback too!
  5. Uses persistent `SqliteSaver` checkpointer (if installed) with automatic `MemorySaver` fallback.
  6. Reuses singleton `genai.Client` and supports emergency Kill Switch (`cancel_event`).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError

from autonomous_web_agent import AUTONOMOUS_WEB_AGENT, EDGE_AGENT
from config import (
    CHECKPOINT_DB_PATH,
    get_api_key,
    get_fast_model,
    get_reasoning_model,
    is_gemini_4_model,
)
from error_tracker import log_error
from instant_router import RATE_SHIELD
from living_memory_v3 import LIVING_MEMORY
from mcp_client_hub import MCP_HUB
from windows_tools import (
    check_hard_shields,
    get_system_health,
    open_allowlisted_app,
    set_monitor_brightness,
    set_system_volume,
)
from windows_uia_agent import WINDOWS_UIA_AGENT

# ---------------------------------------------------------------------------
# 1. Gemini-Compatible Strict Pydantic v2 Schemas (NO empty dict OBJECTs!)
# ---------------------------------------------------------------------------

ToolCategory = Literal[
    "web_autonomous",
    "web_a11y_snapshot",
    "windows_uia_inspect",
    "windows_uia_click",
    "windows_uia_type",
    "windows_app_open",
    "windows_system",
    "mcp_hub_call",
    "memory_update",
    "memory_recall",
    "final_answer",
]


class NextActionDecision(BaseModel):
    """Dynamic ReAct decision: observes all previous step outputs before choosing the next action."""
    thought: str = Field(..., min_length=2, description="Brief reasoning based on latest observations")
    tool: ToolCategory = Field(..., description="Next tool to execute, or 'final_answer' when goal is done")
    args_json: str = Field(
        default="{}",
        description="Valid JSON object string containing arguments for the chosen tool",
    )
    requires_confirmation: bool = Field(
        default=False,
        description="True if step deletes files, sends external messages, or modifies sensitive settings",
    )
    final_response: str = Field(
        default="",
        description="Populated ONLY when tool is 'final_answer' — crisp summary for Captain",
    )


class WebAutonomousArgs(BaseModel):
    goal: str = Field(..., min_length=3)
    start_url: str | None = None
    max_steps: int = Field(default=8, ge=1, le=20)


class WindowsUIAClickArgs(BaseModel):
    index: int | None = Field(default=None, ge=1)
    name: str | None = None
    window_title: str | None = None


class WindowsUIATypeArgs(BaseModel):
    text: str = Field(..., min_length=1)
    index: int | None = Field(default=None, ge=1)
    name: str | None = None
    press_enter: bool = False
    window_title: str | None = None


class MCPHubCallArgs(BaseModel):
    server_name: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdateArgs(BaseModel):
    mode: Literal["remember", "core_append", "core_replace"] = "remember"
    content: str = Field(..., min_length=2)
    block: str = "preferences"
    old_text: str = ""


_SENSITIVE_STEP_RE = re.compile(
    r"\b(delete|remove|format|send_whatsapp|send email|shutdown|restart|kill|terminate|rm\s+-rf)\b",
    re.IGNORECASE,
)

MAX_REACT_STEPS = 8


# ---------------------------------------------------------------------------
# 2. LangGraph Dynamic ReAct State
# ---------------------------------------------------------------------------

class AgentGraphState(TypedDict):
    goal: str
    context: str
    step_count: int
    next_action: dict[str, Any]
    step_logs: list[dict[str, Any]]
    approved: bool
    done: bool
    final_answer: str


# ---------------------------------------------------------------------------
# 3. Singleton Free-Tier Gemini Structured Caller (ZERO temperature on Gemini 4!)
# ---------------------------------------------------------------------------

_CLIENT_LOCK = threading.Lock()
_SHARED_GENAI_CLIENT: Any = None


def _get_genai_client() -> Any:
    global _SHARED_GENAI_CLIENT
    with _CLIENT_LOCK:
        if _SHARED_GENAI_CLIENT is None:
            api_key = get_api_key()
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY not found in .env")
            from google import genai  # type: ignore
            _SHARED_GENAI_CLIENT = genai.Client(api_key=api_key)
        return _SHARED_GENAI_CLIENT


def _call_gemini_structured(prompt: str, schema_cls: type[BaseModel]) -> BaseModel:
    """
    Calls free-tier `gemini-4-hydrogen` (ThinkingLevel.HIGH, NO temperature!) with
    automatic fallback to `gemini-3.1-flash-lite` on 503/429.
    """
    from google.genai import types  # type: ignore

    client = _get_genai_client()
    primary = get_reasoning_model()
    fallback = get_fast_model()
    last_err: Exception | None = None

    for model_id in RATE_SHIELD.choose_models([primary, fallback]):
        for _attempt in range(2):
            try:
                cfg_kwargs: dict[str, Any] = {
                    "response_mime_type": "application/json",
                    "response_schema": schema_cls,
                }
                if is_gemini_4_model(model_id):
                    if hasattr(types, "ThinkingConfig") and hasattr(types, "ThinkingLevel"):
                        cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH
                        )
                else:
                    cfg_kwargs["temperature"] = 0.15

                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(**cfg_kwargs),
                )
                raw = (resp.text or "").strip()
                return schema_cls.model_validate_json(raw)
            except ValidationError as verr:
                prompt = (
                    f"{prompt}\n\nPREVIOUS OUTPUT FAILED PYDANTIC VALIDATION:\n{verr}\n"
                    "Return ONLY valid JSON matching the exact schema."
                )
                last_err = verr
            except Exception as exc:
                last_err = exc
                if RATE_SHIELD.is_quota_error(exc):
                    RATE_SHIELD.mark_rate_limited(model_id, cooldown_seconds=45.0)
                    break
                if any(tok in str(exc) for tok in ("503", "UNAVAILABLE")):
                    break
                continue

    raise RuntimeError(f"Structured reasoning failed: {last_err}")


def _parse_args_json(args_json: str) -> dict[str, Any]:
    if not args_json or not args_json.strip():
        return {}
    try:
        parsed = json.loads(args_json)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 4. Deterministic Validated Step Executor
# ---------------------------------------------------------------------------

def _execute_validated_step(
    tool: str,
    args: dict[str, Any],
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if cancel_event and cancel_event.is_set():
        return {"ok": False, "error_code": "CANCELLED", "message": "Captain ne emergency stop trigger kiya."}

    try:
        if tool == "web_autonomous":
            v = WebAutonomousArgs.model_validate(args)
            return AUTONOMOUS_WEB_AGENT.run_autonomous_goal(
                goal=v.goal, max_steps=v.max_steps, start_url=v.start_url, cancel_event=cancel_event
            )

        if tool == "web_a11y_snapshot":
            url = args.get("url")
            if url:
                EDGE_AGENT.navigate_active_tab(str(url))
            return AUTONOMOUS_WEB_AGENT.get_accessibility_tree(
                max_nodes=int(args.get("max_nodes", 75))
            )

        if tool == "windows_uia_inspect":
            return WINDOWS_UIA_AGENT.inspect_window(
                window_title=args.get("window_title"),
                max_elements=int(args.get("max_elements", 60)),
            )

        if tool == "windows_uia_click":
            v = WindowsUIAClickArgs.model_validate(args)
            return WINDOWS_UIA_AGENT.click_element(
                index=v.index, name=v.name, window_title=v.window_title
            )

        if tool == "windows_uia_type":
            v = WindowsUIATypeArgs.model_validate(args)
            return WINDOWS_UIA_AGENT.type_into_element(
                text=v.text,
                index=v.index,
                name=v.name,
                press_enter=v.press_enter,
                window_title=v.window_title,
            )

        if tool == "windows_app_open":
            return open_allowlisted_app(str(args.get("app_name", "")))

        if tool == "windows_system":
            action = str(args.get("action", "status")).lower()
            if action == "volume":
                return set_system_volume(level=int(args.get("level", 50)))
            if action == "brightness":
                return set_monitor_brightness(int(args.get("level", 60)))
            return get_system_health()

        if tool == "mcp_hub_call":
            v = MCPHubCallArgs.model_validate(args)
            return MCP_HUB.call_tool(v.server_name, v.tool_name, v.arguments)

        if tool == "memory_update":
            v = MemoryUpdateArgs.model_validate(args)
            if v.mode == "core_append":
                return LIVING_MEMORY.core_memory_append(v.block, v.content)
            if v.mode == "core_replace":
                return LIVING_MEMORY.core_memory_replace(v.block, v.old_text, v.content)
            return LIVING_MEMORY.remember(v.content)

        if tool == "memory_recall":
            return LIVING_MEMORY.recall(str(args.get("query", "")))

        if tool == "final_answer":
            return {"ok": True, "message": str(args.get("answer", "Completed."))}

        return {"ok": False, "message": f"Unknown tool '{tool}'."}

    except ValidationError as verr:
        return {"ok": False, "validation_error": str(verr), "message": f"Invalid arguments: {verr}"}
    except Exception as exc:
        log_error("reasoning_engine", f"Step '{tool}' error: {exc}", exception=exc)
        return {"ok": False, "message": f"Execution error: {exc}"}


def _build_react_prompt(goal: str, context: str, step_logs: list[dict[str, Any]], step_num: int) -> str:
    obs_lines = []
    for log in step_logs[-6:]:
        res_preview = json.dumps(log.get("result", {}), ensure_ascii=False)[:1400]
        obs_lines.append(f"Step {log['step']} [{log['tool']}({log['args']})]: {res_preview}")
    obs_text = "\n".join(obs_lines) if obs_lines else "(No steps executed yet.)"

    return (
        "You are DarkShadow's Dynamic ReAct Agent for Windows 11.\n"
        f"{context}\n\n"
        f"USER GOAL: {goal}\n"
        f"CURRENT STEP: {step_num} / {MAX_REACT_STEPS}\n\n"
        f"OBSERVATIONS SO FAR:\n{obs_text}\n\n"
        "Choose ONLY the SINGLE NEXT best action based on the latest observations. "
        "When the goal is achieved (or cannot proceed), choose tool='final_answer' and fill `final_response`.\n"
        "Available tools & expected `args_json`:\n"
        '- web_autonomous: {"goal": "...", "start_url": "...", "max_steps": 8}\n'
        '- web_a11y_snapshot: {"url": "...", "max_nodes": 75}\n'
        '- windows_uia_inspect: {"window_title": "..."}\n'
        '- windows_uia_click: {"index": 1, "name": "...", "window_title": "..."}\n'
        '- windows_uia_type: {"text": "...", "index": 1, "name": "...", "press_enter": true, "window_title": "..."}\n'
        '- windows_app_open: {"app_name": "..."}\n'
        '- windows_system: {"action": "status|volume|brightness", "level": 60}\n'
        '- mcp_hub_call: {"server_name": "playwright", "tool_name": "...", "arguments": {}}\n'
        '- memory_update: {"mode": "remember|core_append|core_replace", "content": "...", "block": "preferences"}\n'
        '- memory_recall: {"query": "..."}\n'
        '- final_answer: {"answer": "..."}\n'
        "Set requires_confirmation=true for any risky/delete/send action."
    )


# ---------------------------------------------------------------------------
# 5. LangGraph Dynamic ReAct Engine (with Persistent Checkpointer & Chained HITL)
# ---------------------------------------------------------------------------

class DarkShadowReasoningEngine:
    """Dynamic `Decide Next Step -> Safety Gate (HITL) -> Execute -> Loop -> Synthesize` engine."""

    def __init__(self) -> None:
        self._langgraph_available = False
        self._checkpointer_type = "none"
        self._graph: Any = None
        self._checkpointer: Any = None
        self._sqlite_conn: sqlite3.Connection | None = None
        self._cancel_event = threading.Event()
        self._last_goal: str = ""
        self._last_successful_trace: list[dict[str, Any]] = []
        self._build_langgraph()

    def get_last_successful_trace(self) -> tuple[str, list[dict[str, Any]]]:
        """Returns (goal, step_logs) from the latest completed multi-step run for Playbook learning."""
        return self._last_goal, list(self._last_successful_trace)

    def cancel_active(self) -> None:
        """Signal any active reasoning loop to abort safely (Emergency Kill Switch)."""
        self._cancel_event.set()

    def _build_checkpointer(self):
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore
            CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
            self._sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            self._checkpointer_type = "sqlite"
            return SqliteSaver(self._sqlite_conn)
        except Exception:
            from langgraph.checkpoint.memory import MemorySaver  # type: ignore
            self._checkpointer_type = "memory"
            return MemorySaver()

    def _build_langgraph(self) -> None:
        try:
            from langgraph.graph import END, START, StateGraph  # type: ignore
            from langgraph.types import interrupt  # type: ignore
        except Exception:
            self._langgraph_available = False
            return

        def decide_node(state: AgentGraphState) -> dict[str, Any]:
            if self._cancel_event.is_set():
                return {"done": True, "final_answer": "Captain ke Emergency Stop par autonomous task rok diya gaya."}
            if state["step_count"] >= MAX_REACT_STEPS:
                return {"done": True}

            prompt = _build_react_prompt(
                state["goal"], state["context"], state["step_logs"], state["step_count"] + 1
            )
            decision = _call_gemini_structured(prompt, NextActionDecision)
            assert isinstance(decision, NextActionDecision)

            if decision.tool == "final_answer":
                ans = decision.final_response.strip() or _parse_args_json(decision.args_json).get("answer", "")
                return {
                    "done": True,
                    "final_answer": str(ans or "Captain, task complete ho gaya."),
                    "next_action": decision.model_dump(),
                }

            return {
                "next_action": decision.model_dump(),
                "done": False,
            }

        def safety_gate_node(state: AgentGraphState) -> dict[str, Any]:
            if state.get("done"):
                return {}
            act = state.get("next_action") or {}
            tool = str(act.get("tool", ""))
            args_str = str(act.get("args_json", "{}"))
            req_conf = bool(act.get("requires_confirmation", False))

            shield_reason = check_hard_shields(f"{tool} {args_str}")
            if shield_reason:
                return {
                    "done": True,
                    "approved": False,
                    "final_answer": f"Captain, Safety Shield ne risky step block kar diya: {shield_reason}",
                }

            needs_hitl = req_conf or bool(_SENSITIVE_STEP_RE.search(f"{tool} {args_str}"))
            if needs_hitl:
                decision = interrupt(
                    {
                        "type": "captain_approval_required",
                        "step": state["step_count"] + 1,
                        "tool": tool,
                        "args": _parse_args_json(args_str),
                        "message": f"Captain, kya main step {state['step_count'] + 1} ({tool}) execute karoon?",
                    }
                )
                if not bool(decision):
                    return {
                        "done": True,
                        "approved": False,
                        "final_answer": f"Captain ke instruction par step {state['step_count'] + 1} cancel kar diya gaya.",
                    }
            return {"approved": True}

        def execute_node(state: AgentGraphState) -> dict[str, Any]:
            if state.get("done"):
                return {}
            act = state.get("next_action") or {}
            tool = str(act.get("tool", ""))
            args = _parse_args_json(str(act.get("args_json", "{}")))
            res = _execute_validated_step(tool, args, cancel_event=self._cancel_event)
            step_num = state["step_count"] + 1
            logs = list(state["step_logs"])
            logs.append({"step": step_num, "tool": tool, "args": args, "result": res})
            return {"step_logs": logs, "step_count": step_num}

        def synthesize_node(state: AgentGraphState) -> dict[str, Any]:
            if state.get("final_answer"):
                return {}
            summary_lines = [
                f"Step {l['step']} ({l['tool']}): {'OK' if l['result'].get('ok') else 'FAIL'} — {str(l['result'].get('message', ''))[:240]}"
                for l in state["step_logs"]
            ]
            answer = "Captain, autonomous task complete:\n" + "\n".join(summary_lines)
            return {"final_answer": answer}

        def route_after_decide(state: AgentGraphState) -> str:
            return "synthesize" if state.get("done") else "safety_gate"

        def route_after_safety(state: AgentGraphState) -> str:
            return "synthesize" if state.get("done") else "execute"

        def route_after_execute(state: AgentGraphState) -> str:
            if state.get("done") or state["step_count"] >= MAX_REACT_STEPS or self._cancel_event.is_set():
                return "synthesize"
            return "decide"

        builder = StateGraph(AgentGraphState)
        builder.add_node("decide", decide_node)
        builder.add_node("safety_gate", safety_gate_node)
        builder.add_node("execute", execute_node)
        builder.add_node("synthesize", synthesize_node)

        builder.add_edge(START, "decide")
        builder.add_conditional_edges("decide", route_after_decide, {"safety_gate": "safety_gate", "synthesize": "synthesize"})
        builder.add_conditional_edges("safety_gate", route_after_safety, {"execute": "execute", "synthesize": "synthesize"})
        builder.add_conditional_edges("execute", route_after_execute, {"decide": "decide", "synthesize": "synthesize"})
        builder.add_edge("synthesize", END)

        self._checkpointer = self._build_checkpointer()
        self._graph = builder.compile(checkpointer=self._checkpointer)
        self._langgraph_available = True

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "langgraph_active": self._langgraph_available,
            "checkpointer": self._checkpointer_type,
            "model": get_reasoning_model(),
            "fallback_model": get_fast_model(),
            "free_tier_only": True,
        }

    def _format_graph_outcome(self, tid: str, config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Handles BOTH final completion AND chained Human-in-the-Loop interrupts cleanly!"""
        snapshot = self._graph.get_state(config)
        if getattr(snapshot, "next", None):
            interrupts = []
            for task in getattr(snapshot, "tasks", ()) or ():
                for intr in getattr(task, "interrupts", ()) or ():
                    interrupts.append(intr.value)
            return {
                "ok": True,
                "engine": "langgraph",
                "thread_id": tid,
                "needs_approval": True,
                "approval_details": interrupts,
                "message": (
                    interrupts[0].get("message")
                    if interrupts and isinstance(interrupts[0], dict)
                    else "Captain, risky step ke liye aapki approval chahiye."
                ),
            }
        logs = list(result.get("step_logs", []))
        if logs:
            self._last_goal = str(result.get("goal", ""))
            self._last_successful_trace = logs
        return {
            "ok": True,
            "engine": "langgraph",
            "thread_id": tid,
            "needs_approval": False,
            "steps_executed": len(logs),
            "logs": logs,
            "message": result.get("final_answer", "Task completed."),
        }

    def run_goal(self, goal: str, thread_id: str | None = None) -> dict[str, Any]:
        """Runs a complex multi-step goal via dynamic ReAct using free-tier gemini-4-hydrogen."""
        self._cancel_event.clear()
        context = LIVING_MEMORY.build_system_context_block(current_query=goal)
        tid = thread_id or f"ds-{uuid.uuid4().hex[:8]}"

        initial_state: AgentGraphState = {
            "goal": goal,
            "context": context,
            "step_count": 0,
            "next_action": {},
            "step_logs": [],
            "approved": True,
            "done": False,
            "final_answer": "",
        }

        if self._langgraph_available and self._graph is not None:
            try:
                config = {"configurable": {"thread_id": tid}}
                result = self._graph.invoke(initial_state, config=config)
                return self._format_graph_outcome(tid, config, result)
            except Exception as exc:
                log_error("reasoning_engine", f"LangGraph run error: {exc}", exception=exc)
                return {"ok": False, "engine": "langgraph", "message": f"Reasoning error: {exc}"}

        # Pure-Python Dynamic ReAct Fallback (with FULL Safety Shields & HITL!)
        try:
            logs: list[dict[str, Any]] = []
            for step_num in range(1, MAX_REACT_STEPS + 1):
                if self._cancel_event.is_set():
                    return {"ok": False, "engine": "python_fallback", "message": "Captain ne task cancel kar diya."}
                prompt = _build_react_prompt(goal, context, logs, step_num)
                decision = _call_gemini_structured(prompt, NextActionDecision)
                assert isinstance(decision, NextActionDecision)

                if decision.tool == "final_answer":
                    if logs:
                        self._last_goal = goal
                        self._last_successful_trace = list(logs)
                    ans = decision.final_response.strip() or _parse_args_json(decision.args_json).get("answer", "")
                    return {
                        "ok": True,
                        "engine": "python_fallback",
                        "steps_executed": len(logs),
                        "logs": logs,
                        "message": str(ans or "Captain, task complete ho gaya."),
                    }

                shield = check_hard_shields(f"{decision.tool} {decision.args_json}")
                if shield:
                    return {"ok": False, "engine": "python_fallback", "error_code": "SHIELD_BLOCKED", "message": shield}

                if decision.requires_confirmation or _SENSITIVE_STEP_RE.search(f"{decision.tool} {decision.args_json}"):
                    return {
                        "ok": False,
                        "engine": "python_fallback",
                        "needs_approval": True,
                        "message": f"Captain, risky step ({decision.tool}) paused. Confirm explicitly before proceeding.",
                    }

                args = _parse_args_json(decision.args_json)
                res = _execute_validated_step(decision.tool, args, cancel_event=self._cancel_event)
                logs.append({"step": step_num, "tool": decision.tool, "args": args, "result": res})

            if logs:
                self._last_goal = goal
                self._last_successful_trace = list(logs)
            return {
                "ok": True,
                "engine": "python_fallback",
                "steps_executed": len(logs),
                "logs": logs,
                "message": "Captain, task complete: " + "; ".join(
                    str(l["result"].get("message", ""))[:180] for l in logs
                ),
            }
        except Exception as exc:
            log_error("reasoning_engine", f"Fallback planner error: {exc}", exception=exc)
            return {"ok": False, "message": f"Reasoning failed: {exc}"}

    def resume_approval(self, thread_id: str, approved: bool) -> dict[str, Any]:
        """Resumes a paused LangGraph HITL workflow AND detects any subsequent chained interrupts!"""
        if not self._langgraph_available or self._graph is None:
            return {"ok": False, "message": "LangGraph checkpointer not active."}
        try:
            from langgraph.types import Command  # type: ignore
            self._cancel_event.clear()
            config = {"configurable": {"thread_id": thread_id}}
            result = self._graph.invoke(Command(resume=bool(approved)), config=config)
            outcome = self._format_graph_outcome(thread_id, config, result)
            outcome["approved"] = bool(approved)
            return outcome
        except Exception as exc:
            log_error("reasoning_engine", f"resume_approval failed: {exc}", exception=exc)
            return {"ok": False, "message": f"Resume failed: {exc}"}

    def shutdown(self) -> None:
        self.cancel_active()
        if self._sqlite_conn is not None:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass


REASONING_ENGINE = DarkShadowReasoningEngine()

```


## File: `living_memory_v3.py`

```python
"""
C-All (Fixed): Super-Human Long-Term Memory (Mem0 + Letta-Style Virtual Context Memory)
=======================================================================================
Fixes applied:
  - Uses unified DATA_DIR & MEMORY_DB_PATH from config.py (NO split-brain database!)
  - Lazy Mem0 initialization AFTER .env is loaded (fixes 'missing_gemini_api_key'!)
  - Aligns gemini-embedding-2 embedding_dims=768 with Qdrant (fixes 3072 vs 768 crash!)
  - Thread-safe lock around Core RAM blocks
  - Privacy check (contains_sensitive_data) enforced on Core RAM blocks & auto-ingest!
  - Replaces deprecated datetime.utcnow() with datetime.now(timezone.utc)
  - Supports attach_semantic_engine() so darkshadow_desktop.py shares ONE SemanticMemoryEngine
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    DATA_DIR,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMS,
    MEMORY_DB_PATH,
    get_api_key,
    get_fast_model,
    is_gemini_4_model,
)
from error_tracker import log_error
from memory_engine import SemanticMemoryEngine, contains_sensitive_data

CORE_BLOCKS_FILE = "core_memory_blocks.json"

DEFAULT_CORE_BLOCKS: dict[str, str] = {
    "captain_profile": "Name: Captain Kuldeep. OS: Windows 11. Preferred AI name: DarkShadow (Hriday).",
    "preferences": "Prefers concise, direct Hindi/Hinglish/Bhojpuri/English replies. Uses Microsoft Edge.",
    "active_projects": "Building DarkShadow — Jarvis-level Windows 11 AI co-pilot with voice, browser & OS automation.",
    "safety_rules": "Payment/Checkout/OTP strictly forbidden. Physical webcam permanently disabled.",
}


class LivingMemoryV3:
    """
    Unified 3-tier Memory Manager:
      - Tier 1 (RAM): Letta-style self-editable Core Memory Blocks
      - Tier 2 (Living Facts): Mem0 auto-extraction & conflict resolution (optional `mem0ai`)
      - Tier 3 (Disk/Archival): Shared SQLite `.darkshadow/memory.db` via SemanticMemoryEngine
    """

    def __init__(
        self,
        semantic_memory: SemanticMemoryEngine | None = None,
        storage_dir: Path | None = None,
        user_id: str = "captain_kuldeep",
    ) -> None:
        self.storage_dir = (storage_dir or DATA_DIR).expanduser().resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.user_id = user_id
        self._lock = threading.RLock()
        self.semantic = semantic_memory or SemanticMemoryEngine(MEMORY_DB_PATH)
        self._blocks_path = self.storage_dir / CORE_BLOCKS_FILE
        self._core_blocks: dict[str, str] = self._load_core_blocks()
        self._mem0: Any = None
        self._mem0_initialized = False
        self._mem0_status: str = "pending_lazy_init"

    def attach_semantic_engine(self, semantic_memory: SemanticMemoryEngine) -> None:
        """Bind the single shared SemanticMemoryEngine (with active genai_client)."""
        with self._lock:
            self.semantic = semantic_memory

    # ------------------------------------------------------------------
    # Tier 1: Letta-style Core RAM Memory Blocks (Thread-Safe + Privacy Filtered)
    # ------------------------------------------------------------------
    def _load_core_blocks(self) -> dict[str, str]:
        if self._blocks_path.exists():
            try:
                data = json.loads(self._blocks_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    merged = dict(DEFAULT_CORE_BLOCKS)
                    for k, v in data.items():
                        merged[str(k)] = str(v)
                    return merged
            except Exception as exc:
                log_error("living_memory_v3", f"Core blocks load failed: {exc}")
        self._save_core_blocks(DEFAULT_CORE_BLOCKS)
        return dict(DEFAULT_CORE_BLOCKS)

    def _save_core_blocks(self, blocks: dict[str, str]) -> None:
        try:
            tmp_path = self._blocks_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(blocks, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self._blocks_path)
        except Exception as exc:
            log_error("living_memory_v3", f"Core blocks save failed: {exc}")

    def get_core_blocks(self) -> dict[str, str]:
        with self._lock:
            return dict(self._core_blocks)

    def core_memory_append(self, block: str, content: str) -> dict[str, Any]:
        key = block.strip().lower()
        clean = content.strip()
        if not key or not clean:
            return {"ok": False, "message": "Block name and content are required."}
        if contains_sensitive_data(clean):
            return {
                "ok": False,
                "error_code": "PRIVACY_BLOCKED",
                "message": "Privacy shield: Sensitive credentials/OTP/cards Core Memory mein store nahi kiye ja sakte.",
            }
        with self._lock:
            existing = self._core_blocks.get(key, "").strip()
            if clean.lower() in existing.lower():
                return {"ok": True, "block": key, "message": f"Already stored in core block '{key}'."}
            updated = f"{existing} | {clean}".strip(" |") if existing else clean
            # Trim oldest middle segments while keeping first core fact intact if over 1200 chars
            if len(updated) > 1200:
                parts = [p.strip() for p in updated.split("|") if p.strip()]
                while len(" | ".join(parts)) > 1200 and len(parts) > 2:
                    parts.pop(1)
                updated = " | ".join(parts)[:1200]
            self._core_blocks[key] = updated
            self._save_core_blocks(self._core_blocks)
            return {
                "ok": True,
                "block": key,
                "value": updated,
                "message": f"Appended to core RAM block '{key}'.",
            }

    def core_memory_replace(self, block: str, old_text: str, new_text: str) -> dict[str, Any]:
        key = block.strip().lower()
        clean_new = new_text.strip()
        if contains_sensitive_data(clean_new):
            return {
                "ok": False,
                "error_code": "PRIVACY_BLOCKED",
                "message": "Privacy shield: Sensitive credentials Core Memory mein store nahi kiye ja sakte.",
            }
        with self._lock:
            existing = self._core_blocks.get(key, "")
            if not existing:
                self._core_blocks[key] = clean_new[:1200]
                self._save_core_blocks(self._core_blocks)
                return {"ok": True, "block": key, "message": f"Created core RAM block '{key}'."}

            if old_text and old_text in existing:
                updated = existing.replace(old_text, clean_new, 1)
            else:
                updated = clean_new

            self._core_blocks[key] = updated[:1200]
            self._save_core_blocks(self._core_blocks)
            return {
                "ok": True,
                "block": key,
                "value": self._core_blocks[key],
                "message": f"Updated core RAM block '{key}'.",
            }

    # ------------------------------------------------------------------
    # Tier 2: Mem0 Automatic Living Memory (Lazy init AFTER .env loaded)
    # ------------------------------------------------------------------
    def _ensure_mem0(self) -> Any:
        if self._mem0_initialized:
            return self._mem0
        with self._lock:
            if self._mem0_initialized:
                return self._mem0
            self._mem0_initialized = True
            api_key = get_api_key()
            if not api_key:
                self._mem0_status = "missing_gemini_api_key"
                return None
            try:
                from mem0 import Memory  # type: ignore
            except Exception:
                self._mem0_status = "mem0_not_installed_using_sqlite_fallback"
                return None

            mem_model = os.getenv("DARKSHADOW_MEMORY_MODEL", get_fast_model()).strip() or get_fast_model()
            llm_cfg: dict[str, Any] = {
                "model": mem_model,
                "api_key": api_key,
            }
            # Never pass deprecated temperature to Gemini 4 models
            if not is_gemini_4_model(mem_model):
                llm_cfg["temperature"] = 0.1

            qdrant_path = str(self.storage_dir / "mem0_qdrant")
            config = {
                "llm": {"provider": "gemini", "config": llm_cfg},
                "embedder": {
                    "provider": "gemini",
                    "config": {
                        "model": DEFAULT_EMBEDDING_MODEL,
                        "api_key": api_key,
                        "embedding_dims": EMBEDDING_DIMS,
                    },
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": "darkshadow_captain_memory",
                        "path": qdrant_path,
                        "embedding_model_dims": EMBEDDING_DIMS,
                    },
                },
            }
            try:
                self._mem0 = Memory.from_config(config)
                self._mem0_status = "mem0_active"
            except Exception as exc:
                log_error("living_memory_v3", f"Mem0 init fallback to SQLite: {exc}", exception=exc)
                self._mem0 = None
                self._mem0_status = f"sqlite_fallback ({type(exc).__name__})"
            return self._mem0

    # ------------------------------------------------------------------
    # Unified Public API
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        self._ensure_mem0()
        return {
            "ok": True,
            "mem0_status": self._mem0_status,
            "core_blocks": list(self.get_core_blocks().keys()),
            "storage_dir": str(self.storage_dir),
            "db_path": str(self.semantic.db_path),
        }

    def remember(self, text: str, category: str = "preference") -> dict[str, Any]:
        """Stores a fact in BOTH Contradiction-Free SQLite AND Mem0 (when active)."""
        clean = text.strip()
        if not clean:
            return {"ok": False, "message": "Empty memory text."}
        if contains_sensitive_data(clean):
            return {
                "ok": False,
                "error_code": "PRIVACY_BLOCKED",
                "message": "Privacy shield: Sensitive credentials/OTP/cards save karna blocked hai.",
            }

        sql_ok, sql_msg = self.semantic.save_memory(category, clean)

        mem0_saved = False
        mem0 = self._ensure_mem0()
        if mem0 is not None:
            try:
                mem0.add(clean, user_id=self.user_id, metadata={"category": category})
                mem0_saved = True
            except Exception as exc:
                log_error("living_memory_v3", f"Mem0 add warning: {exc}")

        return {
            "ok": bool(sql_ok or mem0_saved),
            "verified_state": "memory_saved" if (sql_ok or mem0_saved) else "memory_rejected",
            "mem0_synced": mem0_saved,
            "message": sql_msg,
        }

    def recall(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Hybrid recall merging Mem0 living facts + SQLite semantic memories."""
        results: list[str] = []
        seen: set[str] = set()

        mem0 = self._ensure_mem0()
        if mem0 is not None:
            try:
                res = mem0.search(query, user_id=self.user_id, limit=limit)
                items = res.get("results", []) if isinstance(res, dict) else (res or [])
                for item in items:
                    text = (
                        (item.get("memory") or item.get("text") or "").strip()
                        if isinstance(item, dict)
                        else str(item).strip()
                    )
                    key = text.lower()
                    if text and key not in seen:
                        seen.add(key)
                        results.append(text)
            except Exception as exc:
                log_error("living_memory_v3", f"Mem0 search warning: {exc}")

        try:
            sql_hits = self.semantic.recall_relevant(query, limit=limit)
            for hit in sql_hits:
                text = str(hit).strip()
                key = text.lower()
                if text and key not in seen:
                    seen.add(key)
                    results.append(text)
        except Exception as exc:
            log_error("living_memory_v3", f"SQLite recall warning: {exc}")

        return {
            "ok": True,
            "verified_state": "memory_recalled",
            "count": len(results[:limit]),
            "memories": results[:limit],
            "message": "; ".join(results[:limit]) if results else "No matching memories found.",
        }

    def ingest_conversation_turn(self, user_text: str, assistant_text: str) -> None:
        """Passively feeds non-sensitive completed turns into Mem0."""
        u_clean = (user_text or "").strip()
        a_clean = (assistant_text or "").strip()
        if len(u_clean) < 6 or contains_sensitive_data(u_clean) or contains_sensitive_data(a_clean):
            return
        mem0 = self._ensure_mem0()
        if mem0 is None:
            return
        try:
            mem0.add(
                [
                    {"role": "user", "content": u_clean},
                    {"role": "assistant", "content": a_clean[:500]},
                ],
                user_id=self.user_id,
                metadata={"timestamp": datetime.now(timezone.utc).isoformat()},
            )
        except Exception as exc:
            log_error("living_memory_v3", f"Auto-ingest turn skipped: {exc}")

    def build_system_context_block(self, current_query: str = "") -> str:
        """Renders Letta-style Core RAM blocks + top relevant archival facts for system instructions."""
        sections = ["=== CORE MEMORY (RAM) ==="]
        for k, v in self.get_core_blocks().items():
            sections.append(f"[{k}]: {v}")

        if current_query.strip():
            recalled = self.recall(current_query, limit=4).get("memories", [])
            if recalled:
                sections.append("=== RELEVANT LONG-TERM MEMORIES ===")
                for item in recalled:
                    sections.append(f"- {item}")

        return "\n".join(sections)


LIVING_MEMORY = LivingMemoryV3()

```


## File: `memory_engine.py`

```python
"""
Upgrade #4 (Fixed): Contradiction-Free Living Semantic Memory, Reminders & Episodic Archive.
===========================================================================================
Fixes applied:
  - Proper connection closing via contextlib.closing() + SQLite WAL mode (zero handle leaks / DB locks!)
  - Uses explicit 768-dim embeddings with gemini-embedding-2 (output_dimensionality=768)
  - Stop-word filtered contradiction detection (prevents falsely overwriting unrelated preferences!)
  - Narrower credit-card Luhn check instead of blocking every 13-19 digit ID/number
  - Free-tier gemini-3.1-flash-lite for fast episodic session summaries
  - 100% drop-in compatible with existing .darkshadow/memory.db tables
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from array import array
import math

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

from config import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMS, get_fast_model

try:
    from google.genai import types as genai_types
except Exception:
    genai_types = None

SENSITIVE_LABELS = re.compile(
    r"\b(?:api\s*key|password|passcode|otp|cvv|credit\s*card|debit\s*card|"
    r"bank\s*account|upi\s*pin|private\s*key|secret\s*key|access\s*token)\b",
    re.IGNORECASE,
)
SECRET_SHAPES = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{16,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# Hinglish + English stop-words excluded from preference conflict subject matching
_STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are", "was", "very",
    "like", "love", "prefer", "prefers", "really", "always", "usually", "about", "user",
    "captain", "kuldeep", "mujhe", "mera", "meri", "mere", "ko", "ka", "ki", "ke", "se",
    "mein", "par", "hai", "hain", "tha", "thi", "bahut", "bohot", "pasand", "zyada", "jyada",
    "karta", "karti", "hoon", "hun", "aur", "bhi", "toh", "ek", "ko", "ya", "kya",
}
_NEG_WORDS = {"nahi", "nhi", "not", "never", "mat", "hate", "dislike", "bilkul", "no", "na"}


def _passes_luhn(digits: str) -> bool:
    """Verify if a 13-19 digit string is a valid payment card number (avoids false positives on IDs)."""
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    total = 0
    reverse_digits = digits[::-1]
    for i, ch in enumerate(reverse_digits):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def contains_sensitive_data(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if SENSITIVE_LABELS.search(cleaned):
        return True
    if any(p.search(cleaned) for p in SECRET_SHAPES):
        return True
    for match in CARD_CANDIDATE_RE.finditer(cleaned):
        digits = re.sub(r"\D", "", match.group(0))
        if _passes_luhn(digits):
            return True
    return False


@dataclass(frozen=True)
class ReminderRecord:
    id: int
    message: str
    due_at: str


class SemanticMemoryEngine:
    """SQLite semantic memory + contradiction-aware upsert + episodic session archive."""

    def __init__(self, db_path: Path, genai_client: Any = None) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = genai_client
        self._summary_model = get_fast_model()
        self._init_db()

    def set_client(self, genai_client: Any) -> None:
        """Attach or refresh Gemini client cleanly after initialization."""
        self._client = genai_client

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=8.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 5000;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK (kind IN ('preference', 'note')),
                    content TEXT NOT NULL,
                    embedding BLOB,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    due_at_iso TEXT NOT NULL,
                    delivered_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    embedding BLOB,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _to_vec(blob: bytes | None) -> Any:
        if not blob:
            return None
        if np is not None:
            return np.frombuffer(blob, dtype=np.float32)
        arr = array("f")
        arr.frombytes(blob)
        return arr

    def _embed(self, text: str) -> bytes | None:
        if self._client is None:
            return None
        try:
            embed_kwargs: dict[str, Any] = {
                "model": DEFAULT_EMBEDDING_MODEL,
                "contents": text,
            }
            if genai_types is not None and hasattr(genai_types, "EmbedContentConfig"):
                embed_kwargs["config"] = genai_types.EmbedContentConfig(
                    output_dimensionality=EMBEDDING_DIMS
                )
            resp = self._client.models.embed_content(**embed_kwargs)
            values = resp.embeddings[0].values
            if np is not None:
                return np.asarray(values, dtype=np.float32).tobytes()
            return array("f", values).tobytes()
        except Exception:
            return None

    @classmethod
    def _cosine(cls, a_blob: bytes | None, b_vec: Any) -> float:
        if not a_blob or b_vec is None:
            return 0.0
        a_vec = cls._to_vec(a_blob)
        if a_vec is None or len(a_vec) != len(b_vec):
            return 0.0
        if np is not None:
            denom = float(np.linalg.norm(a_vec) * np.linalg.norm(b_vec))
            return float(np.dot(a_vec, b_vec) / denom) if denom > 1e-8 else 0.0
        dot = sum(x * y for x, y in zip(a_vec, b_vec))
        na = math.sqrt(sum(x * x for x in a_vec))
        nb = math.sqrt(sum(y * y for y in b_vec))
        denom = na * nb
        return float(dot / denom) if denom > 1e-8 else 0.0

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9\u0900-\u097f]{2,}", text.lower()))

    def _find_conflicting_preference(
        self, conn: sqlite3.Connection, content: str, emb: bytes | None
    ) -> int | None:
        """Find an existing preference that is duplicate or directly superseded by the new one."""
        new_norm = re.sub(r"\s+", " ", content.lower().strip())
        new_vec = self._to_vec(emb)
        new_toks = self._tokens(content)
        new_has_neg = bool(new_toks & _NEG_WORDS)
        new_subject = new_toks - _NEG_WORDS - _STOP_WORDS

        best_id: int | None = None
        best_score = 0.0

        rows = conn.execute(
            "SELECT id, content, embedding FROM memories WHERE kind = 'preference'"
        ).fetchall()
        for row in rows:
            old_text = str(row["content"])
            old_norm = re.sub(r"\s+", " ", old_text.lower().strip())
            if old_norm == new_norm:
                return int(row["id"])

            sim = self._cosine(row["embedding"], new_vec)
            old_toks = self._tokens(old_text)
            old_has_neg = bool(old_toks & _NEG_WORDS)
            old_subject = old_toks - _NEG_WORDS - _STOP_WORDS
            shared_subject = new_subject & old_subject

            # Require meaningful subject overlap (not stop-words!) OR very high semantic similarity
            min_sub = min(len(new_subject), len(old_subject))
            subject_overlap_ratio = (len(shared_subject) / min_sub) if min_sub > 0 else 0.0
            is_polarity_flip = (
                (new_has_neg != old_has_neg)
                and len(shared_subject) >= 1
                and subject_overlap_ratio >= 0.5
            )
            if (sim >= 0.84 or is_polarity_flip) and (sim + subject_overlap_ratio * 0.25) > best_score:
                best_score = sim + subject_overlap_ratio * 0.25
                best_id = int(row["id"])

        return best_id

    def save_memory(self, kind: str, content: str) -> tuple[bool, str]:
        cleaned = content.strip()
        if not cleaned:
            return False, "Empty memory save nahi ki ja sakti."
        if contains_sensitive_data(cleaned):
            return (
                False,
                "Privacy shield: API keys, passwords, OTPs aur payment data save karna blocked hai.",
            )

        norm_kind = "note" if kind.lower() == "note" else "preference"
        emb = self._embed(cleaned)
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            if norm_kind == "preference":
                existing_id = self._find_conflicting_preference(conn, cleaned, emb)
                if existing_id is not None:
                    conn.execute(
                        "UPDATE memories SET content = ?, embedding = ?, created_at = ? WHERE id = ?",
                        (cleaned, emb, now, existing_id),
                    )
                    return (
                        True,
                        f"Captain, preference #{existing_id} update kar di gayi (purani conflicting entry replace ho gayi).",
                    )

            cur = conn.execute(
                "INSERT INTO memories (kind, content, embedding, created_at) VALUES (?, ?, ?, ?)",
                (norm_kind, cleaned, emb, now),
            )
            item_id = cur.lastrowid
        return True, f"Captain, {norm_kind} #{item_id} semantic memory mein save ho gaya."

    def recall_relevant(self, query: str, limit: int = 4) -> list[str]:
        q_blob = self._embed(query)
        q_vec = self._to_vec(q_blob)
        q_words = self._tokens(query) - _STOP_WORDS

        scored: list[tuple[float, str]] = []
        with self._connect() as conn:
            for row in conn.execute("SELECT kind, content, embedding FROM memories").fetchall():
                sim = self._cosine(row["embedding"], q_vec)
                words = self._tokens(str(row["content"])) - _STOP_WORDS
                kw = len(q_words & words) * 0.25
                score = sim + kw
                if score >= 0.22 or kw > 0:
                    scored.append((score, f"[{row['kind']}] {row['content']}"))

            for row in conn.execute(
                "SELECT session_date, summary, embedding FROM episodes ORDER BY id DESC LIMIT 25"
            ).fetchall():
                sim = self._cosine(row["embedding"], q_vec)
                words = self._tokens(str(row["summary"])) - _STOP_WORDS
                kw = len(q_words & words) * 0.15
                score = sim + kw
                if score >= 0.35:
                    scored.append((score, f"[past session {row['session_date']}] {row['summary']}"))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def list_recent(self, limit: int = 10) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, content FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [f"#{r['id']} [{r['kind']}] {r['content']}" for r in rows]

    def list_upcoming_reminders(self, limit: int = 5) -> list[ReminderRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, message, due_at_iso FROM reminders WHERE delivered_at IS NULL ORDER BY due_at_iso ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            ReminderRecord(id=int(r["id"]), message=str(r["message"]), due_at=str(r["due_at_iso"]))
            for r in rows
        ]

    def archive_episode(self, turns: list[tuple[str, str]]) -> None:
        if len(turns) < 2:
            return
        transcript = "\n".join(f"Captain: {u}\nDarkShadow: {a}" for u, a in turns[-10:])
        summary = f"Discussed: {turns[-1][0][:120]}"
        if self._client is not None:
            try:
                resp = self._client.models.generate_content(
                    model=self._summary_model,
                    contents=(
                        "Summarize this conversation in 1-2 short factual sentences for long-term "
                        "memory (include any new preferences or tasks):\n" + transcript
                    ),
                )
                if resp.text and resp.text.strip():
                    summary = resp.text.strip()[:300]
            except Exception:
                pass
        if contains_sensitive_data(summary):
            return
        now = datetime.now(timezone.utc)
        emb = self._embed(summary)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO episodes (session_date, summary, embedding, created_at) VALUES (?, ?, ?, ?)",
                (now.strftime("%Y-%m-%d"), summary, emb, now.isoformat()),
            )

    def add_reminder(self, message: str, due_at: datetime) -> tuple[bool, str]:
        cleaned = message.strip()
        if not cleaned:
            return False, "Reminder message empty nahi ho sakta."
        if contains_sensitive_data(cleaned):
            return False, "Privacy shield: Sensitive data reminder mein blocked hai."
        now = datetime.now(timezone.utc).isoformat()
        due_utc = due_at.astimezone(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (message, due_at_iso, created_at) VALUES (?, ?, ?)",
                (cleaned, due_utc, now),
            )
            rid = cur.lastrowid
        local_disp = due_at.astimezone().strftime("%d %b %I:%M %p")
        return True, f"Captain, reminder #{rid} set ho gaya ({local_disp}): {cleaned}"

    def pop_due_reminders(self) -> list[ReminderRecord]:
        now_iso = datetime.now(timezone.utc).isoformat()
        due: list[ReminderRecord] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, message, due_at_iso FROM reminders WHERE delivered_at IS NULL AND due_at_iso <= ?",
                (now_iso,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE reminders SET delivered_at = ? WHERE id = ?",
                    (now_iso, row["id"]),
                )
                due.append(
                    ReminderRecord(
                        id=int(row["id"]),
                        message=str(row["message"]),
                        due_at=str(row["due_at_iso"]),
                    )
                )
        return due

```


## File: `config.py`

```python
"""
DarkShadow Centralized Configuration & Early Environment Loader
===============================================================
Import this module FIRST in entrypoints so `.env` is ALWAYS loaded
before any module reads GEMINI_API_KEY, DARKSHADOW_EDGE_CDP_URL, etc.
100% Free-Tier Friendly Gemini Model Defaults (Zero paid-only models!).
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None, override=False, **_kwargs):
        if not dotenv_path:
            return False
        p = Path(dotenv_path)
        if not p.exists():
            return False
        try:
            for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and (override or k not in os.environ):
                    os.environ[k] = v
            return True
        except Exception:
            return False

APP_DIR = Path(__file__).resolve().parent

# Load .env cleanly once, before any singleton or client initializes
for _env_candidate in (APP_DIR / ".env", APP_DIR.parent / ".env", APP_DIR.parent.parent / ".env"):
    if _env_candidate.exists():
        load_dotenv(_env_candidate, override=False)
load_dotenv(override=False)

# Single unified storage directory (eliminates split-brain memory.db!)
DATA_DIR = Path(os.getenv("DARKSHADOW_DATA_DIR", str(APP_DIR / ".darkshadow"))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DB_PATH = DATA_DIR / "memory.db"
CHECKPOINT_DB_PATH = DATA_DIR / "langgraph_checkpoints.db"
ERROR_LOG_PATH = DATA_DIR / "antigravity_error_log.jsonl"
ACTION_AUDIT_PATH = DATA_DIR / "action_audit.jsonl"
VAULT_DIR = Path(os.getenv("DARKSHADOW_VAULT_DIR", str(Path.home() / "DarkShadow_Vault"))).expanduser().resolve()
VAULT_DB_PATH = DATA_DIR / "knowledge_vault.db"
PLAYBOOKS_PATH = DATA_DIR / "playbooks.json"
SECURITY_LOCK_PATH = DATA_DIR / "security_lock.json"

# 100% Free-Tier Friendly Gemini Models (NO paid-only gemini-4-neon/carbon/argon!)
DEFAULT_TEXT_MODEL = "gemini-4-hydrogen"
DEFAULT_FAST_MODEL = "gemini-3.1-flash-lite"
DEFAULT_LIVE_MODEL = "gemini-3.8-live-extended-thinking"
DEFAULT_LIVE_FALLBACK_MODEL = "gemini-3.8-live"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMS = 768


def get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip()


def get_text_model() -> str:
    return os.getenv("DARKSHADOW_MODEL", DEFAULT_TEXT_MODEL).strip() or DEFAULT_TEXT_MODEL


def get_reasoning_model() -> str:
    return os.getenv("DARKSHADOW_REASONING_MODEL", DEFAULT_TEXT_MODEL).strip() or DEFAULT_TEXT_MODEL


def get_fast_model() -> str:
    return os.getenv("DARKSHADOW_FALLBACK_MODEL", DEFAULT_FAST_MODEL).strip() or DEFAULT_FAST_MODEL


def get_live_model() -> str:
    return os.getenv("DARKSHADOW_LIVE_MODEL", DEFAULT_LIVE_MODEL).strip() or DEFAULT_LIVE_MODEL


def get_cdp_url() -> str:
    """Return live Microsoft Edge CDP endpoint, auto-detecting localhost, ::1, or fallback."""
    import urllib.request
    configured = os.getenv("DARKSHADOW_EDGE_CDP_URL", "").strip()
    candidates = [
        configured,
        "http://localhost:9222",
        "http://[::1]:9222",
        "http://127.0.0.1:9222",
        "http://localhost:9333",
        "http://127.0.0.1:9333",
    ]
    for raw in candidates:
        if not raw:
            continue
        u = raw.rstrip("/")
        try:
            with urllib.request.urlopen(f"{u}/json/version", timeout=0.35) as resp:
                if resp.status == 200:
                    return u
        except Exception:
            continue
    return configured or "http://localhost:9222"


def is_gemini_4_model(model_name: str) -> bool:
    """Gemini 4 models do not accept deprecated sampling params (temperature/top_p/top_k)."""
    return "gemini-4" in (model_name or "").lower()

```


## File: `security_guard.py`

```python
"""
DarkShadow Upgrade: Voice-Lock / Passphrase Security Guard (Ultra-Low RAM)
==========================================================================
Protects sensitive/high-risk actions (WhatsApp sending, PC lock, file deletion,
autonomous HITL approval) using a salted PBKDF2-HMAC-SHA256 passphrase hash.

RAM footprint: <0.2 MB (stdlib hashlib + hmac + json only).
Security properties:
  - Never stores plaintext passphrase (120,000-iteration PBKDF2-SHA256 + 16-byte random salt).
  - Constant-time comparison (`hmac.compare_digest`).
  - Brute-force protection (5 consecutive failures -> 60s lockout).
  - Configurable timed unlock window (default 300s = 5 min) + instant manual lock.
  - Non-intrusive until Captain sets a passphrase (opt-in safety upgrade).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from config import SECURITY_LOCK_PATH

_PBKDF2_ITERATIONS = 120_000
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60.0

_RISKY_ARG_RE = re.compile(
    r"\b(?:delete|remove|erase|rm\s+-rf|format|wipe|shutdown|restart|reboot|uninstall|kill\s+process)\b",
    re.IGNORECASE,
)


class PassphraseSecurityGuard:
    """Thread-safe Passphrase Guard for sensitive DarkShadow tool actions."""

    def __init__(self, store_path: Path | None = None, default_ttl_seconds: int = 300) -> None:
        self._path = Path(store_path) if store_path else SECURITY_LOCK_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._default_ttl = max(30, int(os.getenv("DARKSHADOW_LOCK_TTL_SECONDS", str(default_ttl_seconds))))
        self._unlocked_until: float = 0.0
        self._failed_attempts: int = 0
        self._lockout_until: float = 0.0
        self._config: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"enabled": False, "salt_hex": "", "hash_hex": "", "ttl_seconds": self._default_ttl}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"enabled": False, "salt_hex": "", "hash_hex": "", "ttl_seconds": self._default_ttl}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    @staticmethod
    def _normalize_phrase(phrase: str) -> str:
        # Normalize whitespace & case so voice transcription minor spacing/casing matches reliably
        return re.sub(r"\s+", " ", (phrase or "").strip().lower())

    @classmethod
    def _derive_hash(cls, phrase: str, salt: bytes) -> str:
        norm = cls._normalize_phrase(phrase).encode("utf-8")
        dk = hashlib.pbkdf2_hmac("sha256", norm, salt, _PBKDF2_ITERATIONS)
        return dk.hex()

    def is_enabled(self) -> bool:
        with self._lock:
            return bool(self._config.get("enabled") and self._config.get("hash_hex"))

    def is_unlocked(self) -> bool:
        with self._lock:
            if not (self._config.get("enabled") and self._config.get("hash_hex")):
                return True
            return time.monotonic() < self._unlocked_until

    def set_passphrase(self, new_passphrase: str, current_passphrase: str = "", ttl_seconds: int | None = None) -> dict[str, Any]:
        norm = self._normalize_phrase(new_passphrase)
        if len(norm) < 4:
            return {
                "ok": False,
                "error_code": "WEAK_PASSPHRASE",
                "message": "Passphrase kam se kam 4 characters ka hona chahiye, Captain.",
            }
        with self._lock:
            if self._config.get("enabled") and self._config.get("hash_hex"):
                if not self._verify_locked(current_passphrase):
                    return {
                        "ok": False,
                        "error_code": "AUTH_REQUIRED",
                        "message": "Naya passphrase set karne ke liye purana passphrase verify karna zaroori hai.",
                    }
            salt = secrets.token_bytes(16)
            digest = self._derive_hash(norm, salt)
            ttl = max(30, min(3600, int(ttl_seconds or self._config.get("ttl_seconds", self._default_ttl))))
            self._config = {
                "enabled": True,
                "salt_hex": salt.hex(),
                "hash_hex": digest,
                "ttl_seconds": ttl,
            }
            self._save()
            self._unlocked_until = time.monotonic() + ttl
            self._failed_attempts = 0
            self._lockout_until = 0.0
        return {
            "ok": True,
            "verified_state": "passphrase_enabled",
            "ttl_seconds": ttl,
            "message": f"Captain, Voice/Passphrase Guard active ho gaya (auto-lock {ttl // 60} min mein).",
        }

    def disable(self, current_passphrase: str) -> dict[str, Any]:
        with self._lock:
            if not self._config.get("enabled"):
                return {"ok": True, "message": "Passphrase Guard pehle se disabled hai."}
            if not self._verify_locked(current_passphrase):
                return {
                    "ok": False,
                    "error_code": "INVALID_PASSPHRASE",
                    "message": "Galat passphrase — security guard disable nahi kiya gaya.",
                }
            self._config["enabled"] = False
            self._save()
            self._unlocked_until = 0.0
        return {"ok": True, "verified_state": "passphrase_disabled", "message": "Passphrase Guard disable kar diya gaya hai."}

    def _verify_locked(self, phrase: str) -> bool:
        salt_hex = str(self._config.get("salt_hex") or "")
        expected = str(self._config.get("hash_hex") or "")
        if not salt_hex or not expected:
            return False
        try:
            actual = self._derive_hash(phrase, bytes.fromhex(salt_hex))
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False

    def unlock(self, passphrase: str, ttl_seconds: int | None = None) -> dict[str, Any]:
        with self._lock:
            if not self._config.get("enabled"):
                return {"ok": True, "verified_state": "guard_not_enabled", "message": "Passphrase Guard enabled nahi hai."}
            now = time.monotonic()
            if now < self._lockout_until:
                rem = int(self._lockout_until - now) + 1
                return {
                    "ok": False,
                    "error_code": "LOCKED_OUT",
                    "message": f"Too many wrong attempts! {rem} seconds baad try kijiye.",
                }
            if self._verify_locked(passphrase):
                ttl = max(30, min(3600, int(ttl_seconds or self._config.get("ttl_seconds", self._default_ttl))))
                self._unlocked_until = now + ttl
                self._failed_attempts = 0
                self._lockout_until = 0.0
                return {
                    "ok": True,
                    "verified_state": "unlocked",
                    "ttl_seconds": ttl,
                    "message": f"Identity verified! Sensitive actions agle {ttl // 60} min ke liye unlocked hain, Captain.",
                }
            self._failed_attempts += 1
            if self._failed_attempts >= _MAX_FAILED_ATTEMPTS:
                self._lockout_until = now + _LOCKOUT_SECONDS
                self._failed_attempts = 0
                return {
                    "ok": False,
                    "error_code": "LOCKED_OUT",
                    "message": f"5 galat attempts! Security guard {int(_LOCKOUT_SECONDS)}s ke liye locked hai.",
                }
            rem_tries = _MAX_FAILED_ATTEMPTS - self._failed_attempts
            return {
                "ok": False,
                "error_code": "INVALID_PASSPHRASE",
                "message": f"Galat passphrase. {rem_tries} attempt(s) bache hain.",
            }

    def lock_now(self) -> dict[str, Any]:
        with self._lock:
            self._unlocked_until = 0.0
        return {"ok": True, "verified_state": "locked", "message": "Sensitive actions immediately lock kar diye gaye, Captain."}

    def status(self) -> dict[str, Any]:
        with self._lock:
            enabled = bool(self._config.get("enabled") and self._config.get("hash_hex"))
            rem = max(0, int(self._unlocked_until - time.monotonic())) if enabled else 0
            return {
                "ok": True,
                "enabled": enabled,
                "unlocked": (not enabled) or rem > 0,
                "unlock_remaining_seconds": rem,
                "ttl_seconds": int(self._config.get("ttl_seconds", self._default_ttl)),
            }

    def requires_unlock(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Determine whether a specific tool invocation requires an active unlocked passphrase session."""
        if not self.is_enabled():
            return False
        if self.is_unlocked():
            return False

        action = str(args.get("action") or "").strip().lower()
        if tool_name == "whatsapp_send" and bool(args.get("confirmed")):
            return True
        if tool_name == "app_and_window" and action == "lock_pc" and bool(args.get("confirmed")):
            return True
        if tool_name == "autonomous_agent" and action == "resume_approve":
            return True
        if tool_name == "mcp_hub_action" and action == "call_tool":
            payload = json.dumps(args, ensure_ascii=False)
            if _RISKY_ARG_RE.search(payload):
                return True
        return False

    def check_gate(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        """Returns a blocking response dict if passphrase unlock is required, else None."""
        if self.requires_unlock(tool_name, args):
            return {
                "ok": False,
                "error_code": "PASSPHRASE_LOCKED",
                "needs_passphrase": True,
                "message": (
                    f"Security Lock Active: '{tool_name}' chalane ke liye pehle apna passphrase bol kar "
                    f"ya likh kar unlock kijiye (e.g., 'unlock shadow <passphrase>')."
                ),
            }
        return None


SECURITY_GUARD = PassphraseSecurityGuard()

```


## File: `instant_router.py`

```python
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

```


## File: `knowledge_vault.py`

```python
"""
DarkShadow Upgrade: Personal Knowledge Vault (Ultra-Low RAM Local RAG)
======================================================================
Private local search across Captain's PDFs, Markdown notes, codebases & docs!
RAM-friendly architecture for 16 GB Windows 11 machines:
  - ZERO local ML/embedding models in RAM (no PyTorch, no sentence-transformers!).
  - ZERO heavy background file-watcher threads — uses fast lazy incremental indexing
    (compares file `mtime` + `size`, skips unchanged files in milliseconds!).
  - Powered by built-in SQLite FTS5 BM25 full-text search (0 API calls, <2 MB RAM!).
  - Optional `pypdf` (for PDFs) and `python-docx` (for Word docs) with graceful fallback.
  - Strict Privacy Guard: skips `.env`/key/cert files and filters chunks via
    `contains_sensitive_data()` so passwords/OTPs/cards NEVER enter the vault DB.
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from config import VAULT_DB_PATH, VAULT_DIR
from memory_engine import contains_sensitive_data

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except Exception:
    HAS_PYPDF = False

try:
    import docx  # python-docx
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False

SUPPORTED_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".sql",
    ".html", ".css", ".java", ".cpp", ".c", ".h", ".rs", ".go", ".sh", ".ps1",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".darkshadow"}
SKIP_FILENAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "secrets.json"}
MAX_FILE_BYTES = 8 * 1024 * 1024  # 8 MB cap so huge dumps don't spike RAM


class PersonalKnowledgeVault:
    """Lazy-indexed SQLite FTS5 Personal Knowledge Vault with zero persistent RAM bloat."""

    def __init__(self, vault_dir: Path | None = None, db_path: Path | None = None) -> None:
        self.vault_dir = Path(vault_dir or VAULT_DIR).expanduser().resolve()
        self.db_path = Path(db_path or VAULT_DB_PATH).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vault_files (
                    path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    indexed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vault_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_vault_chunks_path ON vault_chunks(path);
                CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
                    content,
                    filename,
                    path UNINDEXED,
                    chunk_index UNINDEXED,
                    tokenize = 'unicode61'
                );
                """
            )

    @staticmethod
    def _extract_text(file_path: Path) -> str:
        ext = file_path.suffix.lower()
        if ext in SUPPORTED_TEXT_EXTS:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        if ext == ".pdf" and HAS_PYPDF:
            reader = PdfReader(str(file_path))
            pages = []
            for idx, page in enumerate(reader.pages[:120], start=1):
                txt = (page.extract_text() or "").strip()
                if txt:
                    pages.append(f"[Page {idx}] {txt}")
            return "\n\n".join(pages)
        if ext == ".docx" and HAS_DOCX:
            doc = docx.Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return ""

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
        cleaned = re.sub(r"\r\n?", "\n", text).strip()
        if not cleaned:
            return []
        chunks: list[str] = []
        start = 0
        n = len(cleaned)
        while start < n and len(chunks) < 120:
            end = min(n, start + chunk_size)
            # Prefer breaking on paragraph or newline boundary
            if end < n:
                nl = cleaned.rfind("\n", start + chunk_size // 2, end)
                if nl != -1:
                    end = nl
            piece = cleaned[start:end].strip()
            if piece and not contains_sensitive_data(piece):
                chunks.append(piece)
            if end >= n:
                break
            start = max(end - overlap, start + 1)
        return chunks

    def _iter_indexable_files(self, root: Path) -> Iterator[Path]:
        if not root.exists():
            return
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                low = fn.lower()
                if low in SKIP_FILENAMES or low.endswith((".key", ".pem", ".pfx", ".p12")):
                    continue
                p = Path(dirpath) / fn
                ext = p.suffix.lower()
                if ext not in SUPPORTED_TEXT_EXTS and ext not in (".pdf", ".docx"):
                    continue
                try:
                    st = p.stat()
                    if 0 < st.st_size <= MAX_FILE_BYTES:
                        yield p
                except OSError:
                    continue

    def sync_index(self, folder: str | Path | None = None) -> dict[str, Any]:
        """Fast incremental sync: only re-reads new or modified files."""
        root = Path(folder).expanduser().resolve() if folder else self.vault_dir
        root.mkdir(parents=True, exist_ok=True)

        indexed = 0
        skipped = 0
        removed = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock, self._connect() as conn:
            existing = {
                row["path"]: (float(row["mtime"]), int(row["size"]))
                for row in conn.execute("SELECT path, mtime, size FROM vault_files").fetchall()
            }
            seen_paths: set[str] = set()

            for fp in self._iter_indexable_files(root):
                key = str(fp)
                seen_paths.add(key)
                st = fp.stat()
                prev = existing.get(key)
                if prev and abs(prev[0] - st.st_mtime) < 1e-3 and prev[1] == st.st_size:
                    skipped += 1
                    continue

                text = ""
                try:
                    text = self._extract_text(fp)
                except Exception:
                    continue

                chunks = self._chunk_text(text)
                conn.execute("DELETE FROM vault_chunks WHERE path = ?", (key,))
                conn.execute("DELETE FROM vault_fts WHERE path = ?", (key,))
                for idx, ch in enumerate(chunks):
                    conn.execute(
                        "INSERT INTO vault_chunks (path, filename, chunk_index, content) VALUES (?, ?, ?, ?)",
                        (key, fp.name, idx, ch),
                    )
                    conn.execute(
                        "INSERT INTO vault_fts (content, filename, path, chunk_index) VALUES (?, ?, ?, ?)",
                        (ch, fp.name, key, idx),
                    )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO vault_files (path, mtime, size, chunk_count, indexed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (key, float(st.st_mtime), int(st.st_size), len(chunks), now_iso),
                )
                indexed += 1

            # Clean deleted files within the synced root
            root_prefix = str(root)
            for old_path in list(existing.keys()):
                if old_path.startswith(root_prefix) and old_path not in seen_paths:
                    conn.execute("DELETE FROM vault_chunks WHERE path = ?", (old_path,))
                    conn.execute("DELETE FROM vault_fts WHERE path = ?", (old_path,))
                    conn.execute("DELETE FROM vault_files WHERE path = ?", (old_path,))
                    removed += 1

        return {
            "ok": True,
            "verified_state": "vault_synced",
            "vault_dir": str(root),
            "indexed_files": indexed,
            "unchanged_files": skipped,
            "removed_files": removed,
            "pdf_support": HAS_PYPDF,
            "docx_support": HAS_DOCX,
            "message": f"Knowledge Vault sync complete ({indexed} updated, {skipped} unchanged, {removed} removed).",
        }

    @staticmethod
    def _build_fts_query(query: str) -> str:
        tokens = re.findall(r"[a-zA-Z0-9\u0900-\u097f_]{2,}", query or "")
        if not tokens:
            return ""
        # Use OR across unique meaningful tokens for forgiving Hinglish/English recall
        uniq = list(dict.fromkeys(tokens[:10]))
        return " OR ".join(f'"{t}"' for t in uniq)

    def search(self, query: str, limit: int = 5, auto_sync: bool = True) -> dict[str, Any]:
        clean_q = (query or "").strip()
        if not clean_q:
            return {"ok": False, "error_code": "EMPTY_QUERY", "message": "Vault mein search karne ke liye query batayein."}

        if auto_sync and self.vault_dir.exists():
            self.sync_index(self.vault_dir)

        fts_q = self._build_fts_query(clean_q)
        if not fts_q:
            return {"ok": False, "error_code": "INVALID_QUERY", "message": "Valid keywords batayein."}

        lim = max(1, min(10, int(limit or 5)))
        hits: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT filename, path, chunk_index,
                       snippet(vault_fts, 0, '[', ']', ' ... ', 28) AS excerpt,
                       content,
                       bm25(vault_fts) AS rank
                FROM vault_fts
                WHERE vault_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_q, lim),
            ).fetchall()
            for r in rows:
                hits.append(
                    {
                        "filename": r["filename"],
                        "path": r["path"],
                        "chunk_index": int(r["chunk_index"]),
                        "excerpt": str(r["excerpt"] or r["content"][:320]),
                        "content": str(r["content"])[:700],
                    }
                )

        if not hits:
            return {
                "ok": True,
                "verified_state": "vault_no_match",
                "vault_dir": str(self.vault_dir),
                "matches": [],
                "message": f"Vault ({self.vault_dir}) mein '{clean_q}' se related koi note/PDF nahi mila.",
            }

        return {
            "ok": True,
            "verified_state": "vault_matches_found",
            "count": len(hits),
            "matches": hits,
            "message": f"Vault se {len(hits)} matching snippet(s) mil gaye (top: {hits[0]['filename']}).",
        }

    def status(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            file_count = int(conn.execute("SELECT COUNT(*) FROM vault_files").fetchone()[0])
            chunk_count = int(conn.execute("SELECT COUNT(*) FROM vault_chunks").fetchone()[0])
        return {
            "ok": True,
            "vault_dir": str(self.vault_dir),
            "vault_exists": self.vault_dir.exists(),
            "indexed_files": file_count,
            "indexed_chunks": chunk_count,
            "pdf_support": HAS_PYPDF,
            "docx_support": HAS_DOCX,
        }


KNOWLEDGE_VAULT = PersonalKnowledgeVault()

```


## File: `playbook_engine.py`

```python
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

```


## File: `visual_clicker.py`

```python
"""
DarkShadow Upgrade: Set-of-Marks Visual Clicking (Omni-App Control — Zero PyTorch!)
===================================================================================
Solves UIA blindspots (Electron apps, custom canvas buttons, browsers, games) using
a featherweight Set-of-Marks (SoM) pipeline:
  1. Captures monitor via thread-safe `mss` (full virtual screen geometry preserved).
  2. Collects clickable bounding boxes from:
       a) Windows UIA accessibility rectangles (precise native/browser controls), PLUS
       b) Lightweight smart screen grid / UI anchors when UIA finds few elements.
  3. Draws crisp numbered tags `[1]`, `[2]`, `[3]...` directly on an in-memory JPEG copy
     using Pillow (`PIL.ImageDraw`) — ZERO PyTorch/YOLO/OmniParser RAM overhead!
  4. Asks Free-Tier `gemini-4-hydrogen` (fallback `gemini-3.1-flash-lite`) to return ONLY
     the exact tag number JSON `{"tag_id": int, "label": str, "confidence": float}`.
  5. Enforces `check_hard_shields()` BEFORE performing a real Win32 click at the tag center!
"""

from __future__ import annotations

import ctypes
import io
import json
import re
import sys
import time
from typing import Any

from config import get_api_key, get_fast_model, get_text_model
from instant_router import RATE_SHIELD
from windows_tools import check_hard_shields, get_active_window_title

try:
    import mss
    from PIL import Image, ImageDraw
    HAS_CAPTURE = True
except Exception:
    HAS_CAPTURE = False

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except Exception:
    HAS_GENAI = False

try:
    from windows_uia_agent import WINDOWS_UIA_AGENT
    HAS_UIA = True
except Exception:
    HAS_UIA = False


def _win32_click_at(screen_x: int, screen_y: int, double_click: bool = False) -> bool:
    """Click an exact physical screen coordinate on Windows 11 (multi-monitor safe)."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(screen_x), int(screen_y))
        time.sleep(0.05)
        # MOUSEEVENTF_LEFTDOWN = 0x0002, MOUSEEVENTF_LEFTUP = 0x0004
        clicks = 2 if double_click else 1
        for _ in range(clicks):
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            if double_click:
                time.sleep(0.05)
        return True
    except Exception:
        return False


class SetOfMarksVisualClicker:
    """Lightweight Set-of-Marks visual grounding & clicking powered by Free-Tier Gemini."""

    def __init__(self, genai_client: Any = None) -> None:
        self._client = genai_client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key = get_api_key()
        if HAS_GENAI and api_key:
            self._client = genai.Client(api_key=api_key)
        return self._client

    def _collect_candidate_boxes(
        self,
        mon_left: int,
        mon_top: int,
        mon_w: int,
        mon_h: int,
        window_title: str | None = None,
    ) -> list[dict[str, Any]]:
        """Collect interactive boxes from UIA + fallback coarse grid anchors for custom/Electron UIs."""
        boxes: list[dict[str, Any]] = []
        seen_centers: set[tuple[int, int]] = set()

        if HAS_UIA:
            try:
                snap = WINDOWS_UIA_AGENT.inspect_window(window_title=window_title, max_elements=60)
                if snap.get("ok"):
                    for el in getattr(WINDOWS_UIA_AGENT, "_last_elements", {}).values():
                        left, top, right, bottom = getattr(el, "rect", (0, 0, 0, 0))
                        if right <= left or bottom <= top:
                            continue
                        cx = (left + right) // 2
                        cy = (top + bottom) // 2
                        rx = cx - mon_left
                        ry = cy - mon_top
                        if not (4 <= rx <= mon_w - 4 and 4 <= ry <= mon_h - 4):
                            continue
                        bucket = (rx // 18, ry // 18)
                        if bucket in seen_centers:
                            continue
                        seen_centers.add(bucket)
                        hint_str = f"{getattr(el, 'control_type', '')}: {getattr(el, 'name', '')}".strip(": ")[:48]
                        boxes.append(
                            {
                                "rel_x": rx,
                                "rel_y": ry,
                                "screen_x": int(cx),
                                "screen_y": int(cy),
                                "hint": hint_str,
                            }
                        )
            except Exception:
                pass

        # If UIA returned fewer than 12 boxes (e.g., canvas/Electron/game), add lightweight 6x4 visual anchor grid
        if len(boxes) < 12:
            cols, rows = 6, 4
            for r in range(rows):
                for c in range(cols):
                    rx = int((c + 0.5) * mon_w / cols)
                    ry = int((r + 0.5) * mon_h / rows)
                    bucket = (rx // 24, ry // 24)
                    if bucket in seen_centers:
                        continue
                    seen_centers.add(bucket)
                    boxes.append(
                        {
                            "rel_x": rx,
                            "rel_y": ry,
                            "screen_x": mon_left + rx,
                            "screen_y": mon_top + ry,
                            "hint": f"grid({c + 1},{r + 1})",
                        }
                    )

        # Assign 1-based Set-of-Marks tag IDs (cap at 55 so image stays ultra-readable)
        tagged: list[dict[str, Any]] = []
        for idx, b in enumerate(boxes[:55], start=1):
            b["tag_id"] = idx
            tagged.append(b)
        return tagged

    @staticmethod
    def _annotate_image(img: Any, tags: list[dict[str, Any]], max_width: int = 1280) -> bytes:
        """Draw crisp high-contrast numbered Set-of-Marks badges onto a scaled JPEG."""
        w, h = img.size
        scale = min(1.0, max_width / float(max(1, w)))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)))

        draw = ImageDraw.Draw(img)
        for t in tags:
            x = int(t["rel_x"] * scale)
            y = int(t["rel_y"] * scale)
            tid = str(t["tag_id"])
            pad_w = 9 + (6 * len(tid))
            pad_h = 8
            # High-contrast neon cyan badge with black outline & center crosshair dot
            draw.rectangle([x - pad_w, y - pad_h, x + pad_w, y + pad_h], fill=(0, 0, 0), outline=(0, 210, 255), width=2)
            draw.text((x - pad_w + 4, y - pad_h + 2), tid, fill=(255, 255, 0))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return buf.getvalue()

    def visual_click(
        self,
        target_description: str,
        window_title: str | None = None,
        double_click: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        target = (target_description or "").strip()
        if not target:
            return {"ok": False, "error_code": "INVALID_ARGS", "message": "Click karne ke liye target description batayein."}

        shield_msg = check_hard_shields(target, read_only=False)
        if shield_msg:
            return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield_msg}

        if not HAS_CAPTURE:
            return {"ok": False, "error_code": "MISSING_CAPTURE", "message": "mss/Pillow installed nahi hai."}

        client = self._get_client()
        if client is None:
            return {"ok": False, "error_code": "NO_API_KEY", "message": "GEMINI_API_KEY set nahi hai."}

        try:
            with mss.mss() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                shot = sct.grab(mon)
                pil_img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                mon_left, mon_top = int(mon["left"]), int(mon["top"])
                mon_w, mon_h = int(mon["width"]), int(mon["height"])
        except Exception as exc:
            return {"ok": False, "error_code": "CAPTURE_FAILED", "message": f"Screen capture error: {exc}"}

        tags = self._collect_candidate_boxes(mon_left, mon_top, mon_w, mon_h, window_title=window_title)
        if not tags:
            return {"ok": False, "error_code": "NO_TAGS", "message": "Screen par koi clickable tag detect nahi hua."}

        jpeg_bytes = self._annotate_image(pil_img, tags)
        tag_legend = "\n".join(f"[{t['tag_id']}] {t['hint']}" for t in tags[:45])
        active_win = get_active_window_title()

        prompt = (
            f"Active window: '{active_win}'.\n"
            f"Captain wants to click: '{target}'.\n"
            "Look at the numbered cyan-outlined Set-of-Marks badges [1], [2], ... drawn on the screenshot.\n"
            f"Optional UIA hints:\n{tag_legend}\n\n"
            'Respond ONLY with strict JSON: {"tag_id": <int or 0 if not found>, "label": "<what is under that tag>", '
            '"confidence": <0.0 to 1.0>, "reason": "<short reason>"}'
        )

        models_to_try = RATE_SHIELD.choose_models([get_text_model(), get_fast_model()])
        parsed: dict[str, Any] | None = None
        last_err: Exception | None = None

        for model_name in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                        prompt,
                    ],
                )
                raw = (resp.text or "").strip()
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    break
            except Exception as exc:
                last_err = exc
                if RATE_SHIELD.is_quota_error(exc):
                    RATE_SHIELD.mark_rate_limited(model_name, cooldown_seconds=45.0)
                continue

        if not parsed:
            return {
                "ok": False,
                "error_code": "VISION_GROUNDING_FAILED",
                "message": f"Visual target locate nahi ho saka ({type(last_err).__name__ if last_err else 'InvalidJSON'}).",
            }

        tag_id = int(parsed.get("tag_id") or 0)
        label = str(parsed.get("label") or "")
        confidence = float(parsed.get("confidence") or 0.0)

        if tag_id <= 0 or confidence < 0.35:
            return {
                "ok": False,
                "error_code": "TARGET_NOT_FOUND",
                "confidence": confidence,
                "message": f"Screen par '{target}' clearly nahi mila (reason: {parsed.get('reason', 'not visible')}).",
            }

        chosen = next((t for t in tags if t["tag_id"] == tag_id), None)
        if not chosen:
            return {"ok": False, "error_code": "INVALID_TAG_ID", "message": f"Invalid tag ID [{tag_id}] returned."}

        # Second safety check on what Gemini actually saw under that tag!
        shield_label = check_hard_shields(f"{target} {label} {chosen['hint']}", read_only=False)
        if shield_label:
            return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield_label}

        if dry_run:
            return {
                "ok": True,
                "verified_state": "visual_target_located",
                "tag_id": tag_id,
                "label": label,
                "confidence": confidence,
                "screen_x": chosen["screen_x"],
                "screen_y": chosen["screen_y"],
                "message": f"Dry-run: Tag [{tag_id}] '{label}' located at ({chosen['screen_x']}, {chosen['screen_y']}).",
            }

        clicked = _win32_click_at(chosen["screen_x"], chosen["screen_y"], double_click=double_click)
        if not clicked:
            return {"ok": False, "error_code": "CLICK_FAILED", "message": "Win32 click Windows platform par hi supported hai."}

        return {
            "ok": True,
            "verified_state": "visual_clicked",
            "tag_id": tag_id,
            "label": label or chosen["hint"],
            "confidence": confidence,
            "coords": [chosen["screen_x"], chosen["screen_y"]],
            "message": f"Captain, Set-of-Marks tag [{tag_id}] ('{label or target}') par click kar diya.",
        }


VISUAL_CLICKER = SetOfMarksVisualClicker()

```


## File: `focus_sentinel.py`

```python
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

```


## File: `sentinel_monitor.py`

```python
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
    ) -> None:
        self._memory = memory
        self._on_alert = on_proactive_alert
        self._poll = poll_seconds
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

            if HAS_PSUTIL:
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

```


## File: `error_tracker.py`

```python
"""
DarkShadow Antigravity Error Tracker & Action Audit Logger (Thread-Safe + Log Rotation)
======================================================================================
- Thread-safe JSONL writes using threading.Lock (zero corrupted lines across threads)
- Automatic log rotation when log exceeds 5 MB
- Resilient reader that skips malformed lines instead of aborting
- Centralized Action Audit Trail (action_audit.jsonl) for transparency & debugging
"""

from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import ACTION_AUDIT_PATH, ERROR_LOG_PATH

LOG_FILE = ERROR_LOG_PATH
AUDIT_FILE = ACTION_AUDIT_PATH
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB

_ERR_LOCK = threading.Lock()
_AUDIT_LOCK = threading.Lock()


def _rotate_if_large(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size >= MAX_LOG_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            if backup.exists():
                backup.unlink(missing_ok=True)
            path.rename(backup)
    except Exception:
        pass


def log_error(
    category: str,
    error_message: str,
    command_or_context: str = "",
    exception: Exception | None = None,
    suggested_fix: str = "",
    status: str = "PENDING_FIX",
) -> dict[str, Any]:
    """Thread-safe recording of a structured error event to the central error log."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        err_id = f"ERR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{os.urandom(2).hex().upper()}"

        tb_str = ""
        if exception is not None:
            tb_str = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            )

        record = {
            "id": err_id,
            "timestamp": now,
            "status": status,
            "category": category,
            "context": str(command_or_context)[:400],
            "error_message": str(error_message)[:1000],
            "stack_trace": tb_str[-800:] if tb_str else "",
            "suggested_fix": suggested_fix,
        }

        with _ERR_LOCK:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_large(LOG_FILE)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record
    except Exception as exc:
        print(f"[ErrorTracker] Failed to record error: {exc}")
        return {}


def log_action_audit(
    tool_name: str,
    args: dict[str, Any],
    result: dict[str, Any],
    source: str = "voice",
) -> None:
    """Record every tool invocation and outcome to action_audit.jsonl for full observability."""
    try:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "tool": tool_name,
            "args": {k: str(v)[:160] for k, v in (args or {}).items()},
            "ok": bool(result.get("ok", False)),
            "verified_state": result.get("verified_state", ""),
            "error_code": result.get("error_code", ""),
            "message": str(result.get("message", ""))[:250],
        }
        with _AUDIT_LOCK:
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_large(AUDIT_FILE)
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def list_pending_errors(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent pending errors safely (skips any corrupt lines instead of aborting)."""
    if not LOG_FILE.exists():
        return []
    records: list[dict[str, Any]] = []
    with _ERR_LOCK:
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        rec = json.loads(stripped)
                        if isinstance(rec, dict) and rec.get("status") == "PENDING_FIX":
                            records.append(rec)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
    return records[-limit:]


def list_recent_actions(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent audited tool executions."""
    if not AUDIT_FILE.exists():
        return []
    records: list[dict[str, Any]] = []
    with _AUDIT_LOCK:
        try:
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        rec = json.loads(stripped)
                        if isinstance(rec, dict):
                            records.append(rec)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
    return records[-limit:]

```


## File: `mcp_servers.json`

```json
{
  "mcpServers": {
    "playwright": {
      "enabled": true,
      "description": "Stage 1: Official Microsoft Playwright Accessibility-Tree MCP connected to Captain's Edge CDP (port 9222)",
      "command": "npx",
      "args": [
        "-y",
        "@playwright/mcp@latest",
        "--cdp-endpoint",
        "http://localhost:9222"
      ]
    },
    "windows": {
      "enabled": false,
      "description": "Stage 2: CursorTouch/Windows-MCP native Windows 11 OS UI Automation server (set enabled: true after installing uvx)",
      "command": "uvx",
      "args": [
        "windows-mcp"
      ]
    },
    "composio": {
      "enabled": true,
      "description": "Stage 3: Composio MCP server connected to Composio SSE endpoint",
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://mcp.composio.dev/mcp"
      ],
      "env": {
        "COMPOSIO_API_KEY": "ck_sX3svIAkMw3TLp2nyE92"
      }
    },
    "filesystem": {
      "enabled": false,
      "description": "Official MCP Filesystem server (set enabled: true and customize your allowed folder path)",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "C:\\Users\\Public\\Documents"
      ]
    }
  }
}

```


## File: `windows_requirements.txt`

```text
# Core DarkShadow Runtime
google-genai>=1.20.0
python-dotenv>=1.0.1
PySide6>=6.7.0
PySide6-Addons>=6.7.0
numpy>=1.26.4
sounddevice>=0.5.0
SpeechRecognition>=3.10.4
mss>=9.0.1
Pillow>=10.4.0
psutil>=6.0.0
screen-brightness-control>=0.23.0
pyperclip>=1.9.0
pycaw>=20240210
comtypes>=1.4.8

# [A-1, A-2, A-3] Next-Gen Browser & Windows 11 Accessibility Automation
playwright>=1.50.0
browser-use>=0.2.0
langchain-google-genai>=2.1.0
uiautomation>=2.0.20
pywinauto>=0.6.8

# [B-1, B-2] Deep Reasoning & Type-Safe Tool Calling
pydantic>=2.10.0
pydantic-ai>=0.1.0
langgraph>=0.3.0

# [C-All] Super-Human Living Memory (Mem0 + Local Qdrant)
mem0ai>=0.1.80

# [D-1] Official Universal MCP Client SDK
mcp>=1.6.0

# [Stage 03] Composio External SaaS Integrations
composio>=0.33.0
composio-langgraph>=0.33.0

```


## File: `Launch_Edge_Debug.bat`

```bat
@echo off
title DarkShadow - Microsoft Edge CDP Automation Profile
color 0b
echo ===================================================================
echo     DarkShadow - Microsoft Edge CDP (Port 9222) Automation Setup
echo ===================================================================
echo.
echo [1/2] Launching Microsoft Edge with Remote Debugging Port 9222...
start "" msedge --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\DarkShadowEdgeProfile" --no-first-run

timeout /t 2 >nul

echo [2/2] Checking CDP status on http://localhost:9222/json/version...
powershell -Command "try { $v = (Invoke-RestMethod -Uri http://localhost:9222/json/version -TimeoutSec 2); Write-Host '[SUCCESS] CDP Port 9222 Connected!' -ForegroundColor Green; Write-Host ('Browser: ' + $v.Browser); Write-Host 'Keep this Edge window open so DarkShadow can interact with your web tabs!'; } catch { Write-Host '[NOTE] If port did not open, close running Edge windows from Task Manager and re-run this file.' -ForegroundColor Yellow; }"
echo.
pause

```


## File: `run_darkshadow_desktop.bat`

```bat
@echo off
setlocal enabledelayedexpansion
title DarkShadow Desktop AI — Python Co-Pilot
color 0b

echo ==========================================================
echo   DarkShadow Desktop AI (PySide6 WebGL2 + Python)
echo ==========================================================
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in system PATH!
    pause
    exit /b 1
)

echo [✓] Launching DarkShadow Transparent WebGL2 Desktop Overlay...
echo [i] Model: gemini-4-hydrogen (Configured in .env)
echo [i] Tip: Say "Hey Dark Shadow" or right-click the System Tray icon.
echo.

python darkshadow_desktop.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Application exited with code %errorlevel%.
    pause
)

```
