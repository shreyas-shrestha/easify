import pytest

from app.ai import prompts
from app.ai.factory import build_chat_provider
from app.config.settings import Settings


def test_attach_context_includes_app_and_prior() -> None:
    s = prompts.attach_context("BASE", focused_app="Mail", prior_words="dear team")
    assert "BASE" in s
    assert "Mail" in s
    assert "dear team" in s


def test_attach_context_skips_unknown_app() -> None:
    s = prompts.attach_context("BASE", focused_app="unknown", prior_words="")
    assert s == "BASE"


def test_factory_default_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EASIFY_AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = build_chat_provider(Settings.load())
    assert p.name == "ollama"
    assert len(p.cache_model_id) > 0
