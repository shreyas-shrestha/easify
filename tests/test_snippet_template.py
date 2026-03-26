"""Snippet placeholder expansion."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.snippets.template import expand_snippet_template


def test_expand_date_and_escape() -> None:
    dt = datetime(2024, 3, 15, 14, 30, 0)
    s = expand_snippet_template("D {date} {{date}}", now=dt, focused_app="", clipboard="")
    assert "2024-03-15" in s
    assert "{date}" in s


def test_expand_clipboard_and_focused_app() -> None:
    s = expand_snippet_template(
        "{clipboard} in {focused_app}",
        clipboard="x",
        focused_app="Mail",
        now=datetime(2000, 1, 1),
    )
    assert s == "x in Mail"


def test_expand_input_disabled_returns_empty() -> None:
    s = expand_snippet_template("Hi {input:Name}", allow_input_dialog=False)
    assert s == "Hi "


def test_cursor_position_empty() -> None:
    assert expand_snippet_template("x{cursor_position}y", now=datetime(2000, 1, 1)) == "xy"


def test_autocorrect_apply_to_phrase_dedupes_fuzzy(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.autocorrect.engine import AutocorrectEngine

    p = tmp_path / "ac.json"
    p.write_text('{"corrections": {"the": "THE"}}', encoding="utf-8")
    ac = AutocorrectEngine(p)
    calls: list[str] = []

    def traced_fuzzy(word: str, *, score_cutoff: int = 92):
        calls.append(word)
        return None

    monkeypatch.setattr(ac, "lookup_word_fuzzy", traced_fuzzy)
    out = ac.apply_to_phrase("foo foo foo")
    assert out == "foo foo foo"
    assert len(calls) == 1
