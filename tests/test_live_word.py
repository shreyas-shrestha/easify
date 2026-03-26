from pathlib import Path

from app.autocorrect.engine import AutocorrectEngine
from app.cache.store import SqliteExpansionCache
from app.engine.live_word import LiveWordResolver, is_safe_word, live_cache_prompt, resolve_live_word
from app.snippets.engine import SnippetEngine


def test_is_safe_word_default_min_len() -> None:
    assert is_safe_word("teh") is True
    assert is_safe_word("ab") is False
    assert is_safe_word("The") is False
    assert is_safe_word("HTTP") is False
    assert is_safe_word("https") is False
    assert is_safe_word("foo_bar") is False
    assert is_safe_word("a1b") is False
    assert is_safe_word("path/file") is False


def test_is_safe_word_min_len_override() -> None:
    assert is_safe_word("ab", min_len=2) is True
    assert is_safe_word("a", min_len=2) is False


def test_live_resolve_dict(tmp_path: Path) -> None:
    ac_path = tmp_path / "ac.json"
    ac_path.write_text('{"corrections": {"teh": "the"}}', encoding="utf-8")
    ac = AutocorrectEngine(ac_path)
    p = tmp_path / "s.json"
    p.write_text("{}", encoding="utf-8")
    sn = SnippetEngine([p])
    cache = SqliteExpansionCache(tmp_path / "c.db")
    r = LiveWordResolver(sn, ac, cache, "m", fuzzy_threshold=92)
    assert r.resolve("teh") == "the"


def test_resolve_cache_without_fuzzy(tmp_path: Path) -> None:
    ac_path = tmp_path / "ac.json"
    ac_path.write_text("{}", encoding="utf-8")
    ac = AutocorrectEngine(ac_path)
    p = tmp_path / "s.json"
    p.write_text("{}", encoding="utf-8")
    sn = SnippetEngine([p])
    cache = SqliteExpansionCache(tmp_path / "c.db")
    cache.put("m", live_cache_prompt("custom"), "CUSTOM")
    assert (
        resolve_live_word(
            "custom",
            autocorrect=ac,
            snippets=sn,
            cache=cache,
            model="m",
            fuzzy_enabled=False,
        )
        == "CUSTOM"
    )
