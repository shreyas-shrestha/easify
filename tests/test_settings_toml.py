"""config.toml merge: env wins over file."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import Settings


@pytest.fixture
def clear_toml_sensitive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "EASIFY_LIVE_AUTOCORRECT",
        "OLLAMA_EXPANDER_LIVE_AUTOCORRECT",
        "EASIFY_METRICS",
        "EASIFY_PHRASE_BUFFER_MAX",
    ):
        monkeypatch.delenv(key, raising=False)


def test_toml_merges_when_env_not_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clear_toml_sensitive_env: None
) -> None:
    p = tmp_path / "cfg.toml"
    p.write_text(
        "live_autocorrect = true\nmetrics = true\nphrase_buffer_max = 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EASIFY_CONFIG", str(p))
    s = Settings.load()
    assert s.live_autocorrect is True
    assert s.metrics_enabled is True
    assert s.phrase_buffer_max == 4


def test_env_beats_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clear_toml_sensitive_env: None
) -> None:
    p = tmp_path / "cfg.toml"
    p.write_text("live_autocorrect = true\n", encoding="utf-8")
    monkeypatch.setenv("EASIFY_CONFIG", str(p))
    monkeypatch.setenv("EASIFY_LIVE_AUTOCORRECT", "0")
    s = Settings.load()
    assert s.live_autocorrect is False


def test_metrics_incr_persists(tmp_path: Path) -> None:
    import json

    from app.utils.metrics import Metrics

    mp = tmp_path / "metrics.json"
    m = Metrics(mp)
    m.incr("live_replacements", 2)
    m.flush()
    data = json.loads(mp.read_text(encoding="utf-8"))
    assert data["counters"]["live_replacements"] == 2


def test_metrics_batch_flush(tmp_path: Path) -> None:
    from app.utils.metrics import Metrics

    mp = tmp_path / "m.json"
    m = Metrics(mp)
    m.incr("x", 1)
    m.flush()
    assert mp.is_file()
