from pathlib import Path

from app.cache.store import SqliteExpansionCache


def test_cache_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    c = SqliteExpansionCache(db)
    assert c.get("m", "hello world") is None
    c.put("m", "hello world", "HELLO")
    assert c.get("m", "hello world") == "HELLO"
