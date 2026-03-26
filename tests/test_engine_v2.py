"""Smoke tests for EASIFY_ENGINE_V2 scaffolding (context, policy, live detail, router)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.context.detector import detect_input_context
from app.context.input_context import ActivationKind, AppKind, IntentKind, TextKind
from app.engine.events import EngineEvent, EngineEventType, LiveWordPayload
from app.engine.live_resolve import LiveWordDetail, resolve_live_word_detail
from app.policy.engine import resolve_policy


def test_detect_live_word_context():
    ctx = detect_input_context(
        EngineEvent(EngineEventType.LIVE_WORD, LiveWordPayload(word="hello")),
        focused_app_raw="iTerm2",
    )
    assert ctx.activation is ActivationKind.LIVE_SPACE
    assert ctx.text_kind is TextKind.WORD
    assert ctx.app is AppKind.TERMINAL


def test_resolve_policy_terminal_disables_live():
    from app.config.settings import Settings
    from app.context.input_context import InputContext

    settings = Settings.load()
    ctx = InputContext(
        app=AppKind.TERMINAL,
        activation=ActivationKind.LIVE_SPACE,
        text_kind=TextKind.WORD,
        intent=IntentKind.UNKNOWN,
    )
    pol = resolve_policy(ctx, settings)
    assert pol.live.cache is False
    assert pol.live.snippets is False


def test_resolve_live_word_detail_source(monkeypatch: pytest.MonkeyPatch):
    """Detail path reports source for fuzzy confidence."""
    snippets = MagicMock()
    snippets.resolve_exact.return_value = None
    fz = MagicMock()
    fz.value = "receipt"
    fz.key = "recieve"
    snippets.resolve_fuzzy_ratio.return_value = fz
    ac = MagicMock()
    ac.lookup_word.return_value = None
    ac.lookup_word_fuzzy.return_value = None
    cache = MagicMock()
    cache.get.return_value = None

    monkeypatch.setattr(
        "app.engine.live_resolve.ratio_exceeds",
        lambda a, b, t: True,
    )

    d = resolve_live_word_detail(
        "recieve",
        autocorrect=ac,
        snippets=snippets,
        cache=cache,
        model="m",
        fuzzy_enabled=True,
        cache_enabled=False,
        fuzzy_threshold=50,
    )
    assert isinstance(d, LiveWordDetail)
    assert d.source == "snippet_fuzzy"
    assert d.text == "receipt"
    assert 0.0 <= d.fuzzy_ratio <= 1.0


def test_settings_preset_input_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_PRESET", "input_engine")
    monkeypatch.delenv("EASIFY_ENGINE_V2", raising=False)
    from app.config.settings import Settings

    s = Settings.load()
    assert s.engine_v2 is True


def test_settings_preset_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_PRESET", "minimal")
    from app.config.settings import Settings

    s = Settings.load()
    assert s.semantic_snippets is False
    assert s.live_cache_enrich is False


def test_cache_service_facade(tmp_path) -> None:
    from app.cache.service import CacheService
    from app.cache.store import SqliteExpansionCache

    db = tmp_path / "t.db"
    store = SqliteExpansionCache(db)
    cs = CacheService(store)
    cs.store_ai_result("model-a", "prompt-x", "answer", source="ai")
    assert cs.lookup_live("model-a", "prompt-x") == "answer"
    text, hits, src = cs.lookup_capture("model-a", "prompt-x")
    assert text == "answer"
    assert hits >= 1
    assert src == "ai"
    store.close()
