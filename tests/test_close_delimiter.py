"""Close-delimiter streaming matcher for inline capture."""

from __future__ import annotations

from app.engine.buffer import CloseDelimiterMatcher


def test_close_matcher_emits_submit_on_full_delimiter() -> None:
    m = CloseDelimiterMatcher("//")
    assert m.feed("/") == []
    assert m.feed("/") == [("submit", None)]


def test_close_matcher_flushes_partial_then_appends() -> None:
    m = CloseDelimiterMatcher("//")
    assert m.feed("/") == []
    ev = m.feed("a")
    assert ("append", "/") in ev and ("append", "a") in ev


def test_close_matcher_backspace_on_pending() -> None:
    m = CloseDelimiterMatcher("//")
    m.feed("/")
    assert m.backspace() is True
    assert m.pending == ""
