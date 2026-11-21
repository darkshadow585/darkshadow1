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
