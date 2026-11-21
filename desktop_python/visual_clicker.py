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
