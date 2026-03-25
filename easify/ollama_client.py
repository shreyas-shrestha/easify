"""Async Ollama /api/generate with retries."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import aiohttp


def _normalize(text: str) -> str:
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        s = s[1:-1].strip()
    return s


async def generate(
    session: aiohttp.ClientSession,
    url: str,
    model: str,
    user_prompt: str,
    system: str,
    *,
    timeout: float = 120.0,
    retries: int = 2,
) -> str:
    body: dict[str, Any] = {
        "model": model,
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
    for attempt in range(retries + 1):
        try:
            async with session.post(
                url,
                json=body,
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers={"Content-Type": "application/json"},
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
            return _normalize(str(payload.get("response", "")))
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, TypeError, ValueError) as e:
            last_err = e
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise last_err
    raise RuntimeError(str(last_err))
