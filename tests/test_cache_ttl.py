"""SQLite cache entry TTL (age from created_at)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.cache.store import SqliteExpansionCache, _cache_key


def test_cache_ttl_fresh_row_hits(tmp_path: Path) -> None:
    c = SqliteExpansionCache(tmp_path / "a.db", entry_ttl_sec=3600)
    c.put("m", "p1", "r1")
    assert c.get("m", "p1") == "r1"


def test_cache_ttl_expires_old_row(tmp_path: Path) -> None:
    db = tmp_path / "b.db"
    c = SqliteExpansionCache(db, entry_ttl_sec=60)
    c.put("model", "my prompt", "answer")
    k = _cache_key("model", "my prompt")
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE ai_cache SET created_at = created_at - 10_000 WHERE key = ?", (k,))
    conn.commit()
    conn.close()
    assert c.get("model", "my prompt") is None


def test_cache_ttl_zero_disabled(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    c = SqliteExpansionCache(db, entry_ttl_sec=0)
    c.put("m", "p", "r")
    k = _cache_key("m", "p")
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE ai_cache SET created_at = created_at - 10_000 WHERE key = ?", (k,))
    conn.commit()
    conn.close()
    assert c.get("m", "p") == "r"
