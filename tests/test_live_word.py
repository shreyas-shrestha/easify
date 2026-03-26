from pathlib import Path

import pytest

from app.autocorrect.engine import AutocorrectEngine
from app.cache.service import CacheService
from app.cache.store import SqliteExpansionCache
from app.engine.live_resolve import live_cache_prompt, resolve_live_word
from app.engine.live_word import LiveWordResolver, is_safe_word
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


def test_autocorrect_fuzzy_near_miss(tmp_path: Path) -> None:
    ac_path = tmp_path / "ac.json"
    ac_path.write_text('{"corrections": {"arguement": "argument"}}', encoding="utf-8")
    ac = AutocorrectEngine(ac_path)
    # Value-indexed fuzzy: typo must be close to canonical "argument", not to key "arguement".
    assert ac.lookup_word("argumet") is None
    assert ac.lookup_word_fuzzy("argumet", score_cutoff=90) == "argument"


def test_live_resolve_dict(tmp_path: Path) -> None:
    ac_path = tmp_path / "ac.json"
    ac_path.write_text('{"corrections": {"teh": "the"}}', encoding="utf-8")
    ac = AutocorrectEngine(ac_path)
    p = tmp_path / "s.json"
    p.write_text("{}", encoding="utf-8")
    sn = SnippetEngine([p])
    cache = CacheService(SqliteExpansionCache(tmp_path / "c.db"))
    r = LiveWordResolver(sn, ac, cache, "m", fuzzy_threshold=92)
    assert r.resolve("teh") == "the"


def test_listener_live_resolver_without_autocorrect_when_fuzzy_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_LIVE_AUTOCORRECT", "0")
    monkeypatch.setenv("EASIFY_LIVE_FUZZY", "1")
    monkeypatch.setenv("EASIFY_LIVE_CACHE", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionService
    from app.keyboard.listener import KeyboardListener

    svc = ExpansionService(Settings.load())
    listener = KeyboardListener(
        service=svc,
        settings=svc.settings,
        trigger=svc.settings.trigger,
        enter_backspaces=svc.settings.enter_backspaces,
    )
    assert listener._live_resolver is not None


def test_listener_live_resolver_none_when_all_live_stages_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_LIVE_AUTOCORRECT", "0")
    monkeypatch.setenv("EASIFY_LIVE_FUZZY", "0")
    monkeypatch.setenv("EASIFY_LIVE_CACHE", "0")
    monkeypatch.setenv("EASIFY_LIVE_CACHE_ENRICH", "0")
    monkeypatch.setenv("EASIFY_PHRASE_BUFFER_MAX", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionService
    from app.keyboard.listener import KeyboardListener

    svc = ExpansionService(Settings.load())
    listener = KeyboardListener(
        service=svc,
        settings=svc.settings,
        trigger=svc.settings.trigger,
        enter_backspaces=svc.settings.enter_backspaces,
    )
    assert listener._live_resolver is None


def test_resolve_live_word_autocorrect_fuzzy(tmp_path: Path) -> None:
    ac_path = tmp_path / "ac.json"
    ac_path.write_text('{"corrections": {"arguement": "argument"}}', encoding="utf-8")
    ac = AutocorrectEngine(ac_path)
    p = tmp_path / "s.json"
    p.write_text("{}", encoding="utf-8")
    sn = SnippetEngine([p])
    cache = CacheService(SqliteExpansionCache(tmp_path / "c.db"))
    assert (
        resolve_live_word(
            "argumet",
            autocorrect=ac,
            snippets=sn,
            cache=cache,
            model="m",
            fuzzy_enabled=False,
            cache_enabled=False,
        )
        == "argument"
    )


def test_resolve_cache_without_fuzzy(tmp_path: Path) -> None:
    ac_path = tmp_path / "ac.json"
    ac_path.write_text("{}", encoding="utf-8")
    ac = AutocorrectEngine(ac_path)
    p = tmp_path / "s.json"
    p.write_text("{}", encoding="utf-8")
    sn = SnippetEngine([p])
    cache = CacheService(SqliteExpansionCache(tmp_path / "c.db"))
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
