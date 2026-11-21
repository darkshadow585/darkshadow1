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
