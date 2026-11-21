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
