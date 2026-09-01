"""Provider registry and route-policy resolution for L3 chat backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    display_name: str
    adapter: str
    base_url_attr: Optional[str]
    api_key_attr: Optional[str]
    model_attr: str
    require_api_key: bool


@dataclass(frozen=True)
class ProviderSelection:
    provider_id: str
    display_name: str
    adapter: str
    base_url: str
    api_key: str
    model: str
    require_api_key: bool


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec("ollama", "Ollama", "ollama", "ollama_url", None, "ollama_model", False),
    ProviderSpec(
        "openai-compatible",
        "OpenAI-compatible",
        "openai-compatible",
        "openai_compatible_base_url",
        "openai_compatible_api_key",
        "openai_compatible_model",
        False,
    ),
    ProviderSpec("openai", "OpenAI", "openai-compatible", "openai_base_url", "openai_api_key", "openai_model", True),
    ProviderSpec("anthropic", "Anthropic", "anthropic", None, "anthropic_api_key", "anthropic_model", True),
    ProviderSpec(
        "openrouter",
        "OpenRouter",
        "openai-compatible",
        "openrouter_base_url",
        "openrouter_api_key",
        "openrouter_model",
        True,
    ),
    ProviderSpec(
        "litellm",
        "LiteLLM",
        "openai-compatible",
        "litellm_base_url",
        "litellm_api_key",
        "litellm_model",
        False,
    ),
)

_PROVIDER_BY_ID = {p.provider_id: p for p in PROVIDERS}
_ALIASES = {
    "": "ollama",
    "local": "ollama",
    "private": "ollama",
    "offline": "ollama",
    "gpt": "openai",
    "chatgpt": "openai",
    "claude": "anthropic",
    "anthropic": "anthropic",
    "openai_compatible": "openai-compatible",
    "openai-compatible": "openai-compatible",
    "compatible": "openai-compatible",
    "router": "openrouter",
    "open-router": "openrouter",
    "lite-llm": "litellm",
    "litellm": "litellm",
}

_POLICY_ALIASES = {
    "local": "private",
    "private": "private",
    "offline": "private",
    "fast": "fast",
    "best": "best",
    "cheap": "cheap",
    "code": "code",
}


def provider_ids() -> tuple[str, ...]:
    return tuple(p.provider_id for p in PROVIDERS)


def normalize_provider_id(value: str) -> str:
    key = (value or "").strip().lower().replace("_", "-")
    return _ALIASES.get(key, key)


def normalize_route_policy(value: str) -> str:
    key = (value or "").strip().lower().replace("_", "-")
    return _POLICY_ALIASES.get(key, "")


def resolve_provider_selection(settings: Any) -> ProviderSelection:
    provider_id = _resolve_provider_id(settings)
    spec = _PROVIDER_BY_ID.get(provider_id) or _PROVIDER_BY_ID["ollama"]
    return ProviderSelection(
        provider_id=spec.provider_id,
        display_name=spec.display_name,
        adapter=spec.adapter,
        base_url=_attr(settings, spec.base_url_attr),
        api_key=_attr(settings, spec.api_key_attr),
        model=_attr(settings, spec.model_attr),
        require_api_key=spec.require_api_key,
    )


def _resolve_provider_id(settings: Any) -> str:
    policy = normalize_route_policy(getattr(settings, "ai_route_policy", ""))
    if policy:
        return _provider_for_policy(settings, policy)
    return normalize_provider_id(getattr(settings, "ai_provider", "ollama"))


def _provider_for_policy(settings: Any, policy: str) -> str:
    if policy == "private":
        return "ollama"
    if policy == "fast":
        return _first_available(settings, ("openai", "litellm", "openai-compatible", "ollama"))
    if policy == "best":
        return _first_available(settings, ("anthropic", "openai", "openrouter", "ollama"))
    if policy == "cheap":
        return _first_available(settings, ("litellm", "openai-compatible", "openrouter", "ollama"))
    if policy == "code":
        return _first_available(settings, ("anthropic", "openai", "openrouter", "ollama"))
    return normalize_provider_id(getattr(settings, "ai_provider", "ollama"))


def _first_available(settings: Any, candidates: tuple[str, ...]) -> str:
    for provider_id in candidates:
        if _is_available(settings, provider_id):
            return provider_id
    return "ollama"


def _is_available(settings: Any, provider_id: str) -> bool:
    spec = _PROVIDER_BY_ID[provider_id]
    if provider_id == "ollama":
        return True
    api_key = _attr(settings, spec.api_key_attr)
    base_url = _attr(settings, spec.base_url_attr)
    if spec.require_api_key and not api_key:
        return False
    if spec.base_url_attr and not base_url:
        return False
    return True


def _attr(settings: Any, name: Optional[str]) -> str:
    if not name:
        return ""
    return str(getattr(settings, name, "") or "").strip()
