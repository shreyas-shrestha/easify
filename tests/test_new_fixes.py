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


def test_currency_normalize_multiword_russian_rubles() -> None:
    from app.engine.l0_compute import _RE_FX, _normalize_currency_aliases

    s = _normalize_currency_aliases("10 Russian rubles to USD")
    assert _RE_FX.match(s) is not None
    assert "RUB" in s and "USD" in s


def test_currency_normalize_dollar_shorthand() -> None:
    from app.engine.l0_compute import _RE_FX, _normalize_currency_aliases

    s = _normalize_currency_aliases("convert $10 to rupees")
    assert _RE_FX.match(s) is not None
    assert "USD" in s and "INR" in s


def test_l0_candidates_find_conversion_in_prose() -> None:
    from app.engine.l0_compute import _l0_query_candidates

    c = _l0_query_candidates("i am writing 10 rubles to USD right now")
    assert any("10 rubles" in x and "USD" in x for x in c)


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
        "what is this song that goes like thank you for the happiest time of my life",
    ]:
        _, system = classify(query)
        assert system != CONVERT, f"should not be CONVERT for {query!r}"


# ── FxRateCache threading.Lock (Python 3.9 safe) ────────────────────────────


def test_fx_cache_lock_is_threading_lock(tmp_path: Path) -> None:
    import threading

    from app.engine.l0_compute import FxRateCache

    fx = FxRateCache(tmp_path / "fx.json")
    assert isinstance(fx._conv_lock, type(threading.Lock()))


def test_fx_cache_fallback_when_frankfurter_fails(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.engine.l0_compute import FxRateCache

    fx = FxRateCache(tmp_path / "fx.json")

    async def fake_get(url: str, **kwargs: object) -> MagicMock:
        r = MagicMock()
        if "frankfurter" in str(url):
            raise OSError("unreachable")
        r.raise_for_status = lambda: None
        r.json = lambda: {
            "result": "success",
            "rates": {"RUB": 100.0},
            "time_last_update_utc": "Thu, 1 Jan 2026 00:00:00 +0000",
        }
        return r

    client = MagicMock()
    client.get = AsyncMock(side_effect=fake_get)

    async def _run():
        return await fx.convert(client, 10.0, "USD", "RUB")

    out = asyncio.run(_run())
    assert out is not None and "1000" in out and "RUB" in out


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
        assert len(svc._undo_stack) == 1
        frame = svc._undo_stack[-1]
    assert frame.injected == "injected text"
    assert frame.restore == "///my intent"
    assert svc.try_undo() is False
    with svc._undo_lock:
        assert len(svc._undo_stack) == 1
        assert svc._undo_stack[-1].injected == "injected text"


def test_undo_frame_empty_injected_not_stored() -> None:
    import os

    from app.config.settings import Settings
    from app.engine.service import ExpansionService

    os.environ.setdefault("EASIFY_TRAY", "0")
    s = Settings.load()
    svc = ExpansionService(s)
    svc.set_undo_frame("", "restore")
    with svc._undo_lock:
        assert len(svc._undo_stack) == 0


def test_undo_stack_lifo_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionService

    svc = ExpansionService(Settings.load())
    deleted: list[int] = []
    svc.set_inject(lambda n: deleted.append(n), lambda t: None, type_fn=lambda s: None)
    svc.set_undo_frame("first", "r1")
    svc.set_undo_frame("second", "r2")
    assert svc.try_undo() is True
    assert deleted == [len("second")]
    with svc._undo_lock:
        assert len(svc._undo_stack) == 1
        assert svc._undo_stack[-1].injected == "first"
    assert svc.try_undo() is True
    assert deleted == [len("second"), len("first")]
    assert svc.try_undo() is False


def test_tray_clear_error_restores_last_success_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionService

    svc = ExpansionService(Settings.load())
    svc.tray_set_idle("hello world")
    svc.tray_set_error("something broke")
    assert svc.tray_snapshot().status == "error"
    svc.tray_clear_error()
    snap = svc.tray_snapshot()
    assert snap.status == "idle"
    assert snap.error == ""
    assert snap.detail == "hello world"


def test_tray_snapshot_includes_queues_and_undo_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionService

    svc = ExpansionService(Settings.load())
    svc.start()
    svc.set_undo_frame("x", "y")
    svc.set_undo_frame("a", "b")
    snap = svc.tray_snapshot()
    assert snap.model
    assert snap.expansion_queued == 0
    assert snap.undo_depth == 2


def test_undo_stack_drops_oldest_when_over_max(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_UNDO_STACK_MAX", "2")
    from app.config.settings import Settings
    from app.engine.service import ExpansionService

    svc = ExpansionService(Settings.load())
    svc.set_undo_frame("a", "r")
    svc.set_undo_frame("b", "r")
    svc.set_undo_frame("c", "r")
    with svc._undo_lock:
        inj = [f.injected for f in svc._undo_stack]
    assert inj == ["b", "c"]


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


def test_expansion_parallel_tail_extends_delete_and_inject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keystrokes after capture submit are buffered and merged at inject time."""
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_INJECT_SETTLE_MS", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionJob, ExpansionService, _PendingExpansionTail

    svc = ExpansionService(Settings.load())
    deleted: list[int] = []
    typed: list[str] = []
    lefts: list[int] = []

    def delete_n(n: int) -> None:
        deleted.append(n)

    def paste_fn(t: str) -> None:
        typed.append(t)

    def cursor_left_n(n: int) -> None:
        lefts.append(n)

    svc.set_inject(
        delete_n, paste_fn, type_fn=lambda s: typed.append(s), cursor_left_fn=cursor_left_n
    )

    job = ExpansionJob(capture="c", delete_count=10, undo_restore="//c//")
    svc._pending_tails.append(_PendingExpansionTail(job=job))
    with svc._pending_tails[0].lock:
        svc._pending_tails[0].tail.extend(list(" hi"))

    svc._apply_replacement(job, "OUT", "L-test")

    assert lefts == [3]
    assert deleted == [10]
    assert typed == ["OUT"]
    with svc._undo_lock:
        assert len(svc._undo_stack) == 1
        undo = svc._undo_stack[-1]
    assert undo.injected == "OUT"
    assert undo.restore == "//c// hi"


def test_inject_tail_settle_waits_for_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_INJECT_SETTLE_MS", "100")
    monkeypatch.setenv("EASIFY_INJECT_SETTLE_MAX_WAIT_MS", "5000")
    import time

    from app.config.settings import Settings
    from app.engine.service import ExpansionJob, ExpansionService, _PendingExpansionTail

    svc = ExpansionService(Settings.load())
    job = ExpansionJob(capture="c", delete_count=10, undo_restore="//c//")
    pe = _PendingExpansionTail(job=job)
    svc._pending_tails.append(pe)
    with pe.lock:
        pe.tail.append("x")
        pe.last_activity_mono = 1000.0

    clock = [1000.0]

    def fake_mono() -> float:
        return clock[0]

    monkeypatch.setattr(time, "monotonic", fake_mono)
    sleeps: list[float] = []

    def fake_sleep(d: float) -> None:
        sleeps.append(d)
        clock[0] += 0.15

    monkeypatch.setattr(time, "sleep", fake_sleep)
    svc._wait_tail_quiet(job)

    assert sleeps, "expected settle loop to sleep once before idle>=settle"
    with pe.lock:
        assert pe.tail == ["x"]


def test_accessibility_inject_skips_synthetic_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """When AX path succeeds, no delete_fn / type_fn runs."""
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_INJECT_SETTLE_MS", "0")
    monkeypatch.setenv("EASIFY_INJECT_ACCESSIBILITY", "1")
    import app.inject.accessibility as acc

    from app.config.settings import Settings
    from app.engine.service import ExpansionJob, ExpansionService, _PendingExpansionTail

    calls: list[tuple[str, str]] = []

    def fake_replace(*, old: str, new: str, match_last: bool = True) -> bool:
        calls.append((old, new, match_last))
        return True

    monkeypatch.setattr(acc, "replace_in_focused_field", fake_replace)

    svc = ExpansionService(Settings.load())
    deleted: list[int] = []
    typed: list[str] = []

    svc.set_inject(
        lambda n: deleted.append(n),
        lambda t: typed.append(t),
        type_fn=lambda s: typed.append(s),
        cursor_left_fn=lambda n: None,
    )
    job = ExpansionJob(capture="c", delete_count=10, undo_restore="//c//")
    svc._pending_tails.append(_PendingExpansionTail(job=job))
    with svc._pending_tails[0].lock:
        svc._pending_tails[0].tail.extend(list(" tail"))

    svc._apply_replacement(job, "OUT", "L-test")

    assert calls == [("//c//", "OUT", True)]
    assert deleted == []
    assert typed == []
    with svc._undo_lock:
        assert len(svc._undo_stack) == 1
        u = svc._undo_stack[-1]
    assert u.via_accessibility is True
    assert u.injected == "OUT"
    assert u.restore == "//c//"


def test_inject_legacy_delete_through_tail_when_cursor_left_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_INJECT_SETTLE_MS", "0")
    monkeypatch.setenv("EASIFY_INJECT_TAIL_CURSOR_LEFT", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionJob, ExpansionService, _PendingExpansionTail

    svc = ExpansionService(Settings.load())
    deleted: list[int] = []
    typed: list[str] = []

    def delete_n(n: int) -> None:
        deleted.append(n)

    svc.set_inject(delete_n, lambda t: typed.append(t), type_fn=lambda s: typed.append(s))
    job = ExpansionJob(capture="c", delete_count=10, undo_restore="//c//")
    svc._pending_tails.append(_PendingExpansionTail(job=job))
    with svc._pending_tails[0].lock:
        svc._pending_tails[0].tail.extend(list(" hi"))
    svc._apply_replacement(job, "OUT", "L-test")
    assert deleted == [13]
    assert typed == ["OUT hi"]


def test_expansion_tail_discarded_on_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionJob, ExpansionService, _PendingExpansionTail

    svc = ExpansionService(Settings.load())
    job = ExpansionJob(capture="x", delete_count=1, undo_restore="x")
    svc._pending_tails.append(_PendingExpansionTail(job=job))
    svc._discard_pending_tail(job)
    assert not svc.has_pending_expansion_tail()


def test_suppress_capture_for_url_scheme_slash_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    from app.config.settings import Settings
    from app.engine.service import ExpansionService
    from app.keyboard.listener import KeyboardListener

    svc = ExpansionService(Settings.load())
    listener = KeyboardListener(
        service=svc,
        settings=svc.settings,
        trigger="//",
        enter_backspaces=svc.settings.enter_backspaces,
    )
    for scheme in ("https://", "http://", "file://", "ftp://"):
        listener._recent_chars.clear()
        for ch in scheme:
            listener._recent_chars.append(ch)
        assert listener._suppress_capture_for_url_scheme_slash_slash() is True
    listener._recent_chars.clear()
    for ch in "// TODO":
        listener._recent_chars.append(ch)
    assert listener._suppress_capture_for_url_scheme_slash_slash() is False


def test_capture_esc_cancels_without_submit(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    import logging

    from pynput.keyboard import Key

    from app.config.settings import Settings
    from app.engine.service import ExpansionService
    from app.keyboard.listener import KeyboardListener

    caplog.set_level(logging.INFO)
    svc = ExpansionService(Settings.load())
    submitted: list[str] = []

    def capture_submit(job) -> None:
        submitted.append(job.capture)

    monkeypatch.setattr(svc, "submit", capture_submit)

    listener = KeyboardListener(
        service=svc,
        settings=svc.settings,
        trigger="//",
        enter_backspaces=svc.settings.enter_backspaces,
    )
    listener._state = "capturing"
    listener._capture_from_prefix = True
    listener._capture.push("x")
    listener._on_press(Key.esc)
    assert listener._state == "idle"
    assert submitted == []
    assert any("cancelled (Esc)" in r.message for r in caplog.records)


def test_accessibility_substring_index_first_vs_last() -> None:
    """Document rfind vs find behavior used by AX/UIA replace."""
    cur = "left//mid//right//mid//end"
    old = "//mid//"
    assert cur.rfind(old) == len("left//mid//right")
    assert cur.find(old) == len("left")


def test_accessibility_inject_passes_match_last_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    monkeypatch.setenv("EASIFY_INJECT_SETTLE_MS", "0")
    monkeypatch.setenv("EASIFY_INJECT_ACCESSIBILITY", "1")
    monkeypatch.setenv("EASIFY_INJECT_ACCESSIBILITY_MATCH_LAST", "0")
    import app.inject.accessibility as acc

    from app.config.settings import Settings
    from app.engine.service import ExpansionJob, ExpansionService, _PendingExpansionTail

    calls: list[tuple[str, str, bool]] = []

    def fake_replace(*, old: str, new: str, match_last: bool = True) -> bool:
        calls.append((old, new, match_last))
        return True

    monkeypatch.setattr(acc, "replace_in_focused_field", fake_replace)

    svc = ExpansionService(Settings.load())
    assert svc.settings.inject_accessibility_match_last is False
    svc.set_inject(lambda n: None, lambda t: None, type_fn=lambda s: None, cursor_left_fn=lambda n: None)
    job = ExpansionJob(capture="c", delete_count=10, undo_restore="//c//")
    svc._pending_tails.append(_PendingExpansionTail(job=job))
    svc._apply_replacement(job, "OUT", "L-test")
    assert calls == [("//c//", "OUT", False)]
