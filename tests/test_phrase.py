from pathlib import Path

from app.autocorrect.engine import AutocorrectEngine
from app.cache.store import SqliteExpansionCache
from app.engine.live_resolve import resolve_live_phrase
from app.snippets.engine import SnippetEngine


def test_phrase_snippet_exact(tmp_path: Path) -> None:
    ac = AutocorrectEngine(None)
    p = tmp_path / "s.json"
    p.write_text('{"foo bar": "OK"}', encoding="utf-8")
    sn = SnippetEngine([p])
    cache = SqliteExpansionCache(tmp_path / "c.db")
    assert resolve_live_phrase("foo bar", autocorrect=ac, snippets=sn, cache=cache, model="m") == "OK"


def test_cache_put_source(tmp_path: Path) -> None:
    c = SqliteExpansionCache(tmp_path / "d.db")
    c.put("m", "p", "r", source="ai")
    rows = c.top_keys(10)
    assert len(rows) == 1
    assert rows[0][2] == "ai"
