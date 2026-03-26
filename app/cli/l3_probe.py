"""Shared L3 backend checks for `doctor`, startup hints, and tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal
from urllib.parse import urlparse, urlunparse

import httpx

from app.config.settings import Settings


def ollama_tags_url(ollama_generate_url: str) -> str:
    u = ollama_generate_url.strip()
    if "/api/generate" in u:
        return u.replace("/api/generate", "/api/tags")
    p = urlparse(u)
    return urlunparse((p.scheme or "http", p.netloc, "/api/tags", "", "", ""))


@dataclass(frozen=True)
class L3BackendIssue:
    level: Literal["fail", "warn"]
    message: str


@dataclass
class L3ProbeOutcome:
    issues: List[L3BackendIssue] = field(default_factory=list)
    ollama_reachable: bool = False
    ollama_tags_url: str = ""


def probe_l3_backend(settings: Settings, *, httpx_timeout: float) -> L3ProbeOutcome:
    """Non-local checks only (keys, Ollama reachability + model list)."""
    out = L3ProbeOutcome()
    prov = (settings.ai_provider or "ollama").strip().lower()

    if prov in ("openai", "gpt"):
        if not (settings.openai_api_key or "").strip():
            out.issues.append(
                L3BackendIssue(
                    "fail",
                    "OpenAI: EASIFY_OPENAI_API_KEY / OPENAI_API_KEY is empty",
                )
            )
        return out

    if prov in ("anthropic", "claude"):
        if not (settings.anthropic_api_key or "").strip():
            out.issues.append(
                L3BackendIssue(
                    "fail",
                    "Anthropic: EASIFY_ANTHROPIC_API_KEY / ANTHROPIC_API_KEY is empty",
                )
            )
        return out

    tags = ollama_tags_url(settings.ollama_url)
    out.ollama_tags_url = tags
    try:
        with httpx.Client(timeout=httpx_timeout) as client:
            r = client.get(tags)
    except httpx.HTTPError as e:
        out.issues.append(
            L3BackendIssue(
                "fail",
                f"Ollama: cannot reach {tags} ({e}) — is `ollama serve` running?",
            )
        )
        return out

    if r.status_code != 200:
        out.issues.append(
            L3BackendIssue(
                "fail",
                f"Ollama: GET {tags} → HTTP {r.status_code}",
            )
        )
        return out

    out.ollama_reachable = True

    try:
        data: Any = r.json()
    except ValueError:
        return out

    names = [str(m["name"]) for m in data.get("models") or [] if isinstance(m, dict) and m.get("name")]
    want = (settings.ollama_model or "").strip().lower()
    if want and not any(n.lower() == want or n.lower().startswith(want + ":") for n in names):
        out.issues.append(
            L3BackendIssue(
                "warn",
                f'Ollama: model "{settings.ollama_model}" not in tags '
                f"(pull with `ollama pull {settings.ollama_model}`)",
            )
        )

    return out


def format_startup_hints(issues: List[L3BackendIssue]) -> List[str]:
    """Turn probe issues into log lines."""
    return [
        f"{issue.message} Run `easify doctor`."
        if issue.level == "fail"
        else f"{issue.message} (see `easify doctor`.)"
        for issue in issues
    ]


def startup_probe_for_run(settings: Settings) -> tuple[L3ProbeOutcome, List[str]]:
    """Single HTTP probe + hint strings for startup (avoid duplicate /api/tags)."""
    t = max(0.5, min(60.0, float(settings.startup_health_timeout_s)))
    outcome = probe_l3_backend(settings, httpx_timeout=t)
    return outcome, format_startup_hints(outcome.issues)


def startup_hint_messages(settings: Settings) -> List[str]:
    """Log-friendly strings for `easify run` (performs one probe)."""
    _, hints = startup_probe_for_run(settings)
    return hints
