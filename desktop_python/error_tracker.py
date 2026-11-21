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

HAS_SENTRY = False

def _init_sentry() -> None:
    global HAS_SENTRY
    try:
        import sentry_sdk
        _sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
        if _sentry_dsn:
            sentry_sdk.init(
                dsn=_sentry_dsn,
                traces_sample_rate=1.0,
                release="darkshadow@2.0.0",
            )
            HAS_SENTRY = True
    except Exception:
        HAS_SENTRY = False

threading.Thread(target=_init_sentry, daemon=True, name="sentry-init").start()

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
    """Primary Error Tracker: Dispatches immediately to Sentry APM + persists to central local log."""
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

        # 1. PRIMARY: Dispatch immediately to Sentry Cloud APM
        def _dispatch_sentry() -> None:
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("category", category)
                    scope.set_tag("error_id", err_id)
                    scope.set_tag("status", status)
                    scope.set_tag("app", "darkshadow-desktop")
                    if command_or_context:
                        scope.set_extra("command_or_context", str(command_or_context)[:500])
                    if suggested_fix:
                        scope.set_extra("suggested_fix", str(suggested_fix)[:500])
                    if tb_str:
                        scope.set_extra("stack_trace", tb_str)

                    if exception is not None:
                        sentry_sdk.capture_exception(exception)
                    else:
                        sentry_sdk.capture_message(
                            f"[{category}] {error_message}",
                            level="error" if status != "FIXED" else "info",
                        )
                sentry_sdk.flush(timeout=2.0)
            except Exception as s_err:
                print(f"[Sentry Dispatch Error] {s_err}")

        if HAS_SENTRY:
            threading.Thread(target=_dispatch_sentry, daemon=True, name="sentry-dispatch").start()

        # 2. SECONDARY: Persist to local JSONL log
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
