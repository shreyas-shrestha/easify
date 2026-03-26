"""Tests for components added in recent iterations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_AUTOCORRECT = REPO_ROOT / "app" / "bundled" / "autocorrect.json"


# ── Metrics batching ────────────────────────────────────────────────────────


def test_metrics_flush_writes_on_explicit_flush(tmp_path: Path) -> None:
    from app.utils.metrics import Metrics

    mp = tmp_path / "m.json"
    m = Metrics(mp)
    m.incr("hits", 3)
    m.flush()
    assert mp.is_file()
    data = json.loads(mp.read_text(encoding="utf-8"))
    assert data["counters"]["hits"] == 3


def test_metrics_multiple_incr_accumulate(tmp_path: Path) -> None:
    from app.utils.metrics import Metrics

    mp = tmp_path / "m2.json"
    m = Metrics(mp)
    m.incr("a", 2)
    m.incr("a", 3)
    m.flush()
    data = json.loads(mp.read_text(encoding="utf-8"))
    assert data["counters"]["a"] == 5


# ── pint singleton ──────────────────────────────────────────────────────────


def test_pint_singleton_same_object() -> None:
    import app.engine.l0_compute as l0

    l0._UREG = None
    r1 = l0._get_ureg()
    r2 = l0._get_ureg()
    assert r1 is r2


def test_try_units_returns_result() -> None:
    from app.engine.l0_compute import try_units

    out = try_units("5 inches to cm")
    assert out is not None
    assert "cm" in out.lower()


# ── Currency alias normalization ─────────────────────────────────────────────


def test_currency_alias_dollars_to_euros() -> None:
    from app.engine.l0_compute import _RE_FX, _normalize_currency_aliases

    s = _normalize_currency_aliases("100 dollars to euros")
    assert _RE_FX.match(s) is not None
    assert "USD" in s
    assert "EUR" in s


def test_currency_alias_pounds_to_dollars() -> None:
    from app.engine.l0_compute import _RE_FX, _normalize_currency_aliases

    s = _normalize_currency_aliases("50 pounds to dollars")
    assert _RE_FX.match(s) is not None


def test_currency_alias_passthrough_iso() -> None:
    from app.engine.l0_compute import _RE_FX, _normalize_currency_aliases

    s = _normalize_currency_aliases("100 USD to EUR")
    assert _RE_FX.match(s) is not None


# ── classify() CONVERT routing ──────────────────────────────────────────────


def test_classify_routes_unit_query_to_convert() -> None:
    from app.ai.prompts import CONVERT, classify

    for query in [
        "what is 10km in miles",
        "turn 5kg into lbs",
        "how many cm is 6 inches",
    ]:
        _, system = classify(query)
        assert system == CONVERT, f"expected CONVERT for {query!r}"


def test_classify_does_not_over_route_to_convert() -> None:
    from app.ai.prompts import CONVERT, classify

    for query in [
        "emoji happy",
        "fix teh sentence",
        "draft weekly update",
    ]:
        _, system = classify(query)
        assert system != CONVERT, f"should not be CONVERT for {query!r}"


# ── FxRateCache threading.Lock (Python 3.9 safe) ────────────────────────────


def test_fx_cache_lock_is_threading_lock(tmp_path: Path) -> None:
    import threading

    from app.engine.l0_compute import FxRateCache

    fx = FxRateCache(tmp_path / "fx.json")
    assert isinstance(fx._conv_lock, type(threading.Lock()))


def test_fx_cache_same_currency_returns_immediately(tmp_path: Path) -> None:
    from app.engine.l0_compute import FxRateCache

    fx = FxRateCache(tmp_path / "fx.json")
    mock_client = MagicMock()

    async def _run():
        return await fx.convert(mock_client, 100.0, "USD", "USD")

    result = asyncio.run(_run())
    assert result == "100 USD"
    mock_client.get.assert_not_called()


# ── live enrich blocklist ────────────────────────────────────────────────────


def test_blocklist_common_words_blocked() -> None:
    from app.utils.live_enrich_blocklist import should_skip_live_enrich_token

    for word in ["the", "and", "monday", "email", "tuesday", "january"]:
        assert should_skip_live_enrich_token(word) is True, f"{word!r} should be blocked"


def test_blocklist_uncommon_words_not_blocked() -> None:
    from app.utils.live_enrich_blocklist import should_skip_live_enrich_token

    for word in ["recieve", "teh", "occurence", "seperate"]:
        assert should_skip_live_enrich_token(word) is False, f"{word!r} should not be blocked"


# ── undo frame lifecycle ─────────────────────────────────────────────────────


def test_undo_frame_set_and_clear() -> None:
    import os

    from app.config.settings import Settings
    from app.engine.service import ExpansionService

    os.environ.setdefault("EASIFY_TRAY", "0")
    s = Settings.load()
    svc = ExpansionService(s)
    svc.set_undo_frame("injected text", "///my intent")
    with svc._undo_lock:
        frame = svc._undo
    assert frame is not None
    assert frame.injected == "injected text"
    assert frame.restore == "///my intent"
    assert svc.try_undo() is False
    with svc._undo_lock:
        assert svc._undo is None


def test_undo_frame_empty_injected_not_stored() -> None:
    import os

    from app.config.settings import Settings
    from app.engine.service import ExpansionService

    os.environ.setdefault("EASIFY_TRAY", "0")
    s = Settings.load()
    svc = ExpansionService(s)
    svc.set_undo_frame("", "restore")
    with svc._undo_lock:
        assert svc._undo is None


# ── double-space no sleep ─────────────────────────────────────────────────────


def test_no_sleep_in_enter_capture_from_double_space() -> None:
    """Verify _enter_capture_from_double_space does not call time.sleep."""
    import inspect

    from app.keyboard import listener as listener_mod

    src = inspect.getsource(listener_mod.KeyboardListener._enter_capture_from_double_space)
    assert "time.sleep" not in src, (
        "_enter_capture_from_double_space must not sleep on the callback thread"
    )


# ── promote max_keys cap ─────────────────────────────────────────────────────


def test_promote_max_keys_enforced(tmp_path: Path) -> None:
    from app.snippets.promote import maybe_promote_cache_hit

    user = tmp_path / "snippets.json"
    user.write_text(
        '{"snippets": {"promoted-aaa": "x", "promoted-bbb": "y"}}',
        encoding="utf-8",
    )
    did = maybe_promote_cache_hit(
        user_snippets=user,
        config_dir=tmp_path,
        cache_prompt="m\ns\nnew phrase here",
        response="result",
        hit_count=10,
        source="ai",
        min_hits=1,
        allowed_sources=frozenset({"ai"}),
        max_promoted_keys=2,
    )
    assert did is False


# ── autocorrect dictionary completeness ──────────────────────────────────────


def test_autocorrect_dictionary_coverage() -> None:
    from app.autocorrect.engine import AutocorrectEngine

    if not BUNDLED_AUTOCORRECT.is_file():
        pytest.skip("bundled autocorrect not present")
    eng = AutocorrectEngine(BUNDLED_AUTOCORRECT)
    must_correct = {
        "recieve": "receive",
        "definately": "definitely",
        "seperate": "separate",
        "occured": "occurred",
        "teh": "the",
        "adn": "and",
        "embarassed": "embarrassed",
        "accomodate": "accommodate",
        "beleive": "believe",
        "freind": "friend",
    }
    for wrong, right in must_correct.items():
        result = eng.lookup_word(wrong)
        assert result == right, f"expected {wrong!r} → {right!r}, got {result!r}"
    assert len(eng._dict) >= 200, f"dictionary too small: {len(eng._dict)} entries"
