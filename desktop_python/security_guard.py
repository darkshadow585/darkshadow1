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
