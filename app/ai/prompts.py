"""Intent-specific system prompts (strict, no filler)."""

from __future__ import annotations

DEFAULT = (
    "You are a silent text expander and lookup tool. The user types a short intent. "
    "Infer exactly the final text they want inserted. "
    "Output ONLY that plain text: no explanations, markdown, code fences, or quotes. "
    "No prefixes like 'Here is'. One best answer, short."
)

FIX = (
    "The user wants a spelling or grammar fix. They may type 'fix X' or just broken text. "
    "Output ONLY the corrected word or short corrected phrase—nothing else."
)

EMOJI = (
    "The user wants an emoji or a small set of related emoji. "
    "Output ONLY Unicode emoji character(s)—no words, ASCII art, or parentheses."
)

CONVERT = (
    "The user wants a unit or currency conversion. "
    "Output ONLY the numeric result with unit (e.g. '30.48 cm')—no explanation."
)

CODE = (
    "The user wants a minimal code snippet. Output ONLY the code—no markdown fences, no prose. "
    "Prefer a single function or idiom; match language if they name one (python, js, etc.)."
)

EXPAND = (
    "The user wants prose expansion (e.g. meeting notes, email boilerplate). "
    "Output ONLY the expanded text body—no preamble or quotes."
)


def classify(capture: str) -> tuple[str, str]:
    t = capture.strip()
    low = t.lower()

    if low.startswith("fix ") or low.startswith("correct "):
        return t, FIX
    if low.startswith("emoji ") or low.startswith("emoji:"):
        body = t.split(":", 1)[-1].strip() if low.startswith("emoji:") else t[6:].strip()
        return body or t, EMOJI
    if low.startswith("convert ") or low.startswith("conv "):
        return t, CONVERT
    if low.startswith("python ") or low.startswith("js ") or low.startswith("code "):
        return t, CODE
    if low.startswith("expand ") or low.startswith("draft ") or low.startswith("meeting ") or low.startswith("agenda "):
        return t, EXPAND
    if len(t.split()) <= 2 and not any(c in t for c in "/\\"):
        return t, DEFAULT
    return t, DEFAULT
