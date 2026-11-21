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
    re.compile(r"\bck_[0-9A-Za-z_-]{12,}\b"),
    re.compile(r"\bsntry[a-z]?_[0-9A-Za-z_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}\b"),
    re.compile(r"\btvly-[0-9A-Za-z_-]{16,}\b"),
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
