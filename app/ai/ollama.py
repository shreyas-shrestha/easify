"""Async Ollama client (httpx). Layer 3 — never blocks the keyboard thread."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from app.utils.log import get_logger

LOG = get_logger(__name__)


def _normalize(text: str) -> str:
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        s = s[1:-1].strip()
    return s


class OllamaClient:
    def __init__(
        self,
        url: str,
        model: str,
        *,
        timeout_s: float = 120.0,
        retries: int = 2,
    ) -> None:
        self.url = url
        self.model = model
        self.timeout_s = timeout_s
        self.retries = retries

    async def generate(self, client: httpx.AsyncClient, user_prompt: str, system: str) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": user_prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": float(
                    os.environ.get("EASIFY_TEMPERATURE")
                    or os.environ.get("OLLAMA_EXPANDER_TEMPERATURE", "0.1")
                )
            },
        }
        delay = 0.4
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = await client.post(
                    self.url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code >= 400:
                    detail = (r.text or "")[:500]
                    raise RuntimeError(f"Ollama HTTP {r.status_code}: {detail or r.reason_phrase}")
                payload = r.json()
                return _normalize(str(payload.get("response", "")))
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as e:
                last_err = e
                LOG.debug("ollama attempt %s failed: %s", attempt, e)
                if attempt < self.retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    raise last_err
        raise RuntimeError(str(last_err))

    async def ping(self, client: httpx.AsyncClient) -> bool:
        try:
            base = self.url.replace("/api/generate", "/api/tags")
            if base == self.url:
                return True
            r = await client.get(base, timeout=5.0)
            return r.status_code < 500
        except httpx.HTTPError:
            return False
