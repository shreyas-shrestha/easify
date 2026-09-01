"""Build L3 ChatProvider from settings."""

from __future__ import annotations

from app.ai.chat_provider import AnthropicChatProvider, ChatProvider, OllamaChatProvider, OpenAIChatProvider
from app.ai.ollama import OllamaClient
from app.ai.registry import resolve_provider_selection
from app.config.settings import Settings


def build_chat_provider(settings: Settings) -> ChatProvider:
    selection = resolve_provider_selection(settings)
    if selection.adapter == "openai-compatible":
        return OpenAIChatProvider(
            api_key=selection.api_key,
            base_url=selection.base_url,
            model=selection.model,
            timeout_s=settings.ollama_timeout_s,
            retries=settings.ollama_retries,
            provider_name=selection.provider_id,
            cache_prefix=selection.provider_id,
            require_api_key=selection.require_api_key,
        )
    if selection.adapter == "anthropic":
        return AnthropicChatProvider(
            api_key=selection.api_key,
            model=selection.model,
            timeout_s=settings.ollama_timeout_s,
            retries=settings.ollama_retries,
        )
    return OllamaChatProvider(
        OllamaClient(
            settings.ollama_url,
            settings.ollama_model,
            timeout_s=settings.ollama_timeout_s,
            retries=settings.ollama_retries,
        )
    )
