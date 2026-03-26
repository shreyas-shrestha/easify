"""Focus name compatibility for inject (token-based; no 'Code' ⊂ 'Xcode' false positive)."""

from __future__ import annotations

import pytest

from app.context.focus import _focus_names_compatible_for_inject, inject_focus_safe_for_keys


@pytest.mark.parametrize(
    ("captured", "now", "ok"),
    [
        ("Code", "Xcode", False),
        ("Code", "Visual Studio Code", True),
        ("Chrome", "Google Chrome", True),
        ("github", "GitHub Desktop", True),
        ("Sublime Text", "sublime", True),
        ("Same", "Same", True),
    ],
)
def test_focus_names_compatible(captured: str, now: str, ok: bool) -> None:
    assert _focus_names_compatible_for_inject(captured, now) is ok


def test_inject_focus_safe_code_vs_xcode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.context.focus.get_focused_app_name_fresh", lambda **k: "Xcode")
    good, msg = inject_focus_safe_for_keys(captured_app="Code")
    assert good is False
    assert "Wrong window" in msg


def test_inject_focus_safe_chrome_subset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.context.focus.get_focused_app_name_fresh", lambda **k: "Google Chrome")
    good, msg = inject_focus_safe_for_keys(captured_app="Chrome")
    assert good is True
    assert msg == ""
