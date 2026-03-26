"""Semantic / prompt cache: SQLite, thread-safe, O(1) lookup by hash key."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


def _cache_key(model: str, normalized_prompt: str) -> str:
    h = hashlib.sha256(f"{model}\n{normalized_prompt}".encode("utf-8")).hexdigest()
    return h


class SqliteExpansionCache:
    """Stores generations for instant replay; tracks source for learning."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA table_info(ai_cache)")
        cols = {str(row[1]) for row in cur.fetchall()}
        if "source" not in cols:
            conn.execute("ALTER TABLE ai_cache ADD COLUMN source TEXT DEFAULT 'ai'")

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_cache (
                      key TEXT PRIMARY KEY,
                      prompt TEXT NOT NULL,
                      response TEXT NOT NULL,
                      model TEXT NOT NULL,
                      hit_count INTEGER NOT NULL DEFAULT 1,
                      created_at REAL NOT NULL,
                      last_used REAL NOT NULL
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_cache_last ON ai_cache(last_used);")
                self._migrate(conn)
            finally:
                conn.close()

    def get(self, model: str, prompt: str) -> Optional[str]:
        k = _cache_key(model, prompt.strip())
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT response FROM ai_cache WHERE key = ?", (k,))
                row = cur.fetchone()
                if row:
                    conn.execute(
                        "UPDATE ai_cache SET hit_count = hit_count + 1, last_used = ? WHERE key = ?",
                        (now, k),
                    )
                    return str(row["response"])
            finally:
                conn.close()
        return None

    def put(self, model: str, prompt: str, response: str, *, source: str = "ai") -> None:
        k = _cache_key(model, prompt.strip())
        now = time.time()
        src = (source or "ai").strip()[:32] or "ai"
        with self._lock:
            conn = self._connect()
            try:
                self._migrate(conn)
                conn.execute(
                    """
                    INSERT INTO ai_cache(key, prompt, response, model, hit_count, created_at, last_used, source)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                      response = excluded.response,
                      model = excluded.model,
                      source = excluded.source,
                      hit_count = ai_cache.hit_count + 1,
                      last_used = excluded.last_used
                    """,
                    (k, prompt, response, model, now, now, src),
                )
            finally:
                conn.close()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT COUNT(*) AS n, SUM(hit_count) AS hits FROM ai_cache")
                row = cur.fetchone()
                return {"entries": int(row["n"] or 0), "total_hits": int(row["hits"] or 0)}
            finally:
                conn.close()

    def top_keys(self, limit: int = 100) -> list[tuple[str, int, str]]:
        """For learning / warmup: prompt, hits, source."""
        with self._lock:
            conn = self._connect()
            try:
                self._migrate(conn)
                cur = conn.execute(
                    """
                    SELECT prompt, hit_count,
                      COALESCE(source, 'ai') AS src
                    FROM ai_cache ORDER BY hit_count DESC LIMIT ?
                    """,
                    (limit,),
                )
                return [(str(r["prompt"]), int(r["hit_count"]), str(r["src"])) for r in cur.fetchall()]
            finally:
                conn.close()
