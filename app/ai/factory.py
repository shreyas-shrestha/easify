"""Build L3 ChatProvider from settings."""

from __future__ import annotations

from typing import Union

from app.ai.chat_provider import AnthropicChatProvider, OllamaChatProvider, OpenAIChatProvider
from app.ai.ollama import OllamaClient
from app.config.settings import Settings

ChatProvider = Union[OllamaChatProvider, OpenAIChatProvider, AnthropicChatProvider]


def build_chat_provider(settings: Settings) -> ChatProvider:
    p = (settings.ai_provider or "ollama").strip().lower()
    if p in ("openai", "gpt"):
        return OpenAIChatProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            timeout_s=settings.ollama_timeout_s,
            retries=settings.ollama_retries,
        )
    if p in ("anthropic", "claude"):
        return AnthropicChatProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
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
