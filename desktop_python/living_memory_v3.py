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
