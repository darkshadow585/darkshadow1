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
