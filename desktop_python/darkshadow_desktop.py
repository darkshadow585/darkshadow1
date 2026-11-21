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
from living_memory_v3 import LIVING_MEMORY  # noqa: E402
from mcp_bridge import MCPToolRegistry  # noqa: E402
from mcp_client_hub import MCP_HUB  # noqa: E402
from memory_engine import SemanticMemoryEngine  # noqa: E402
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
        # Parallel initialization: Start voice & background services immediately (<5s voice ready!)
        QTimer.singleShot(100, self._start_background_services)

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
        focus_menu.addAction(self._act("Sync Knowledge Vault", lambda: threading.Thread(target=lambda: __import__("knowledge_vault").KNOWLEDGE_VAULT.sync_index(), daemon=True).start()))
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
        try:
            from reasoning_engine import REASONING_ENGINE
            REASONING_ENGINE.shutdown()
        except Exception:
            pass
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
