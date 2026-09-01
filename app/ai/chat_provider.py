"""Unified async chat completion for L3 (Ollama, OpenAI, Anthropic)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol

import httpx

from app.ai import ollama as ollama_mod
from app.ai.ollama import OllamaClient
from app.utils.log import get_logger

LOG = get_logger(__name__)


class ChatProvider(Protocol):
    """Structural type for L3 backends (add providers without updating a Union)."""

    @property
    def name(self) -> str: ...

    @property
    def cache_model_id(self) -> str: ...

    async def generate(self, client: httpx.AsyncClient, user: str, system: str) -> str: ...

    async def ping(self, client: httpx.AsyncClient) -> bool: ...


def _temperature() -> float:
    try:
        return float(
            os.environ.get("EASIFY_TEMPERATURE") or os.environ.get("OLLAMA_EXPANDER_TEMPERATURE", "0.1")
        )
    except ValueError:
        return 0.1


class OllamaChatProvider:
    def __init__(self, inner: OllamaClient) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def cache_model_id(self) -> str:
        return self._inner.model

    async def generate(self, client: httpx.AsyncClient, user: str, system: str) -> str:
        return await self._inner.generate(client, user, system)

    async def ping(self, client: httpx.AsyncClient) -> bool:
        return await self._inner.ping(client)


class OpenAIChatProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float,
        retries: int,
        provider_name: str = "openai",
        cache_prefix: str = "openai",
        require_api_key: bool = True,
    ) -> None:
        self._key = api_key.strip()
        self._base = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_s
        self._retries = retries
        self._provider_name = provider_name
        self._cache_prefix = cache_prefix
        self._require_api_key = require_api_key

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def cache_model_id(self) -> str:
        return f"{self._cache_prefix}:{self._model}"

    async def generate(self, client: httpx.AsyncClient, user: str, system: str) -> str:
        if self._require_api_key and not self._key:
            raise RuntimeError(f"{self._provider_name}: API key is required")
        if not self._base:
            raise RuntimeError(f"{self._provider_name}: base URL is required")
        url = f"{self._base}/chat/completions"
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": _temperature(),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        delay = 0.4
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                r = await client.post(url, json=body, headers=headers)
                if r.status_code >= 400:
                    raise RuntimeError(f"OpenAI HTTP {r.status_code}: {(r.text or '')[:400]}")
                payload = r.json()
                choices = payload.get("choices") or []
                if not choices:
                    raise RuntimeError("OpenAI empty choices")
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                return ollama_mod._normalize(str(content or ""))
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError, RuntimeError, KeyError) as e:
                last = e
                LOG.debug("openai attempt %s failed: %s", attempt, e)
                if attempt < self._retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    raise last
        raise RuntimeError(str(last))

    async def ping(self, client: httpx.AsyncClient) -> bool:
        if self._require_api_key and not self._key:
            return False
        if not self._base:
            return False
        try:
            headers = {"Authorization": f"Bearer {self._key}"} if self._key else None
            r = await client.get(f"{self._base}/models", headers=headers, timeout=5.0)
            return r.status_code < 500
        except httpx.HTTPError:
            return False


class AnthropicChatProvider:
    def __init__(self, *, api_key: str, model: str, timeout_s: float, retries: int) -> None:
        self._key = api_key.strip()
        self._model = model
        self._timeout = timeout_s
        self._retries = retries

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def cache_model_id(self) -> str:
        return f"anthropic:{self._model}"

    async def generate(self, client: httpx.AsyncClient, user: str, system: str) -> str:
        if not self._key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY (or EASIFY_ANTHROPIC_API_KEY) is required for ai_provider=anthropic"
            )
        url = "https://api.anthropic.com/v1/messages"
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "temperature": _temperature(),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self._key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        delay = 0.4
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                r = await client.post(url, json=body, headers=headers)
                if r.status_code >= 400:
                    raise RuntimeError(f"Anthropic HTTP {r.status_code}: {(r.text or '')[:400]}")
                payload = r.json()
                blocks = payload.get("content") or []
                parts = []
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "text":
                        parts.append(str(b.get("text", "")))
                return ollama_mod._normalize("\n".join(parts))
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError, RuntimeError, KeyError) as e:
                last = e
                LOG.debug("anthropic attempt %s failed: %s", attempt, e)
                if attempt < self._retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    raise last
        raise RuntimeError(str(last))

    async def ping(self, client: httpx.AsyncClient) -> bool:
        return bool(self._key)
