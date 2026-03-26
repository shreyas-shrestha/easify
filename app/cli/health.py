"""Fast startup probes so silent L3 failures are less common."""

from __future__ import annotations

from typing import List

import httpx

from app.cli.doctor import ollama_tags_url
from app.config.settings import Settings


def startup_l3_hints(settings: Settings) -> List[str]:
    """Return human-readable hints (may be empty). Keep each check under a few seconds."""
    out: list[str] = []
    prov = (settings.ai_provider or "ollama").strip().lower()

    if prov in ("openai", "gpt"):
        if not (settings.openai_api_key or "").strip():
            out.append("OpenAI key missing — L3 will fail until you set OPENAI_API_KEY (see `easify doctor`).")
        return out

    if prov in ("anthropic", "claude"):
        if not (settings.anthropic_api_key or "").strip():
            out.append("Anthropic key missing — L3 will fail until you set ANTHROPIC_API_KEY (see `easify doctor`).")
        return out

    tags = ollama_tags_url(settings.ollama_url)
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(tags)
    except httpx.HTTPError as e:
        out.append(
            f"Ollama not reachable at {tags} ({e}). Start `ollama serve` or run `easify doctor`."
        )
        return out

    if r.status_code != 200:
        out.append(
            f"Ollama returned HTTP {r.status_code} for {tags}. Check EASIFY_MODEL / OLLAMA_URL or run `easify doctor`."
        )
        return out

    try:
        data = r.json()
    except ValueError:
        return out

    names = [str(m["name"]) for m in data.get("models") or [] if isinstance(m, dict) and m.get("name")]
    want = (settings.ollama_model or "").strip().lower()
    if want and not any(n.lower() == want or n.lower().startswith(want + ":") for n in names):
        out.append(
            f"Ollama has no model matching {settings.ollama_model!r} — run `ollama pull {settings.ollama_model}` "
            "or run `easify doctor`."
        )

    return out
