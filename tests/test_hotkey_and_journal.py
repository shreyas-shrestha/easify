"""Global hotkey notices and expansion JSONL journal."""

from __future__ import annotations

import json

import pytest

from app.config.settings import Settings
from app.utils.expansion_log import append_expansion_record
from app.utils.hotkey_risks import describe_global_hotkey_risks


def test_hotkey_risks_macos_ctrl_shift() -> None:
    msgs = describe_global_hotkey_risks(
        "Darwin",
        palette="<ctrl>+<shift>+e",
        undo="",
    )
    assert any("Ctrl+Shift" in m for m in msgs)
    assert any("pynput" in m.lower() for m in msgs)


def test_hotkey_risks_cmd_space() -> None:
    msgs = describe_global_hotkey_risks(
        "Darwin",
        palette="<cmd>+<space>",
        undo="",
    )
    assert any("Spotlight" in m or "Cmd+Space" in m for m in msgs)


def test_expansion_log_append(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    logf = tmp_path / "exp.jsonl"
    monkeypatch.setenv("EASIFY_EXPANSION_LOG", "1")
    monkeypatch.setenv("EASIFY_EXPANSION_LOG_PATH", str(logf))
    s = Settings.load()
    assert s.expansion_log_enabled is True
    append_expansion_record(s, {"capture": "x", "layer": "L1", "ok": True})
    lines = logf.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["capture"] == "x"
    assert row["layer"] == "L1"
    assert row["ok"] is True
    assert "ts" in row
