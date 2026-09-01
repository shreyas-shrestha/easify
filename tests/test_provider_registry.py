from app.ai.factory import build_chat_provider
from app.ai.registry import normalize_provider_id, provider_ids, resolve_provider_selection
from app.config.settings import Settings


def test_provider_registry_exposes_supported_ids() -> None:
    assert provider_ids() == (
        "ollama",
        "openai-compatible",
        "openai",
        "anthropic",
        "openrouter",
        "litellm",
    )


def test_provider_aliases_match_user_facing_names() -> None:
    assert normalize_provider_id("gpt") == "openai"
    assert normalize_provider_id("claude") == "anthropic"
    assert normalize_provider_id("local") == "ollama"
    assert normalize_provider_id("openai_compatible") == "openai-compatible"


def test_private_and_offline_policies_force_ollama(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_PROVIDER", "openai")
    monkeypatch.setenv("EASIFY_AI_ROUTE_POLICY", "private")
    assert resolve_provider_selection(Settings.load()).provider_id == "ollama"

    monkeypatch.setenv("EASIFY_AI_ROUTE_POLICY", "offline")
    assert resolve_provider_selection(Settings.load()).provider_id == "ollama"


def test_best_policy_prefers_anthropic_then_openai_then_ollama(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_ROUTE_POLICY", "best")
    monkeypatch.delenv("EASIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("EASIFY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_provider_selection(Settings.load()).provider_id == "ollama"

    monkeypatch.setenv("EASIFY_OPENAI_API_KEY", "test-openai-key")
    assert resolve_provider_selection(Settings.load()).provider_id == "openai"

    monkeypatch.setenv("EASIFY_ANTHROPIC_API_KEY", "test-anthropic-key")
    assert resolve_provider_selection(Settings.load()).provider_id == "anthropic"


def test_cheap_policy_does_not_select_unconfigured_litellm(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_ROUTE_POLICY", "cheap")
    monkeypatch.delenv("EASIFY_LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("EASIFY_LITELLM_API_KEY", raising=False)
    assert resolve_provider_selection(Settings.load()).provider_id == "ollama"


def test_openrouter_and_litellm_build_openai_compatible_providers(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_PROVIDER", "openrouter")
    monkeypatch.setenv("EASIFY_OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("EASIFY_OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    p = build_chat_provider(Settings.load())
    assert p.name == "openrouter"
    assert p.cache_model_id == "openrouter:anthropic/claude-3.5-sonnet"

    monkeypatch.setenv("EASIFY_AI_PROVIDER", "litellm")
    monkeypatch.setenv("EASIFY_LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
    monkeypatch.setenv("EASIFY_LITELLM_MODEL", "gpt-4o-mini")
    p = build_chat_provider(Settings.load())
    assert p.name == "litellm"
    assert p.cache_model_id == "litellm:gpt-4o-mini"
