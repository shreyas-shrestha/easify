"""Legacy live path helpers (listener → live_pipeline, no LiveWordResolver)."""

from __future__ import annotations

from pathlib import Path

from app.autocorrect.engine import AutocorrectEngine
from app.cache.service import CacheService
from app.cache.store import SqliteExpansionCache
from app.config.settings import Settings
from app.engine.service import ExpansionService
from app.pipelines.live_pipeline import legacy_live_replacement_word
from app.snippets.engine import SnippetEngine


def test_legacy_live_replacement_word_autocorrect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_TRAY", "0")
    ac_path = tmp_path / "ac.json"
    ac_path.write_text('{"corrections": {"teh": "the"}}', encoding="utf-8")
    s_path = tmp_path / "s.json"
    s_path.write_text("{}", encoding="utf-8")

    db = tmp_path / "c.db"
    svc = ExpansionService(
        Settings.load(),
    )
    # Point service at our tmp autocorrect + snippets for isolation
    svc.autocorrect = AutocorrectEngine(ac_path)
    svc.snippets = SnippetEngine([s_path])
    svc.cache_service = CacheService(SqliteExpansionCache(db))

    out = legacy_live_replacement_word(
        "teh",
        service=svc,
        settings=svc.settings,
        focused_app_raw="Notes",
    )
    assert out == "the"
