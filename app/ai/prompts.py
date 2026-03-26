"""Intent-specific system prompts (strict, no filler)."""

from __future__ import annotations

import re

LIVE_WORD_ENRICH = (
    "The user typed a single word in running prose. If it is misspelled or a clear typo, "
    "output ONLY the corrected word. If it is already correct, output the exact same word. "
    "One word only unless a contraction requires two. No quotes, no explanation."
)

LIVE_PHRASE_ENRICH = (
    "The user typed a short phrase in running prose. Fix spelling and obvious grammar only. "
    "Output ONLY the corrected phrase. Keep the same approximate length and token order. "
    "No quotes, no explanation."
)


DEFAULT = (
    "You are a silent text expander and lookup tool. The user types a short intent. "
    "Infer exactly the final text they want inserted. "
    "Output ONLY that plain text: no explanations, markdown, code fences, or quotes. "
    "No prefixes like 'Here is'. One best answer, short. "
    "For lookups (song titles, names, facts): output the minimal correct text only—"
    "typically the title and primary artist when asked for a song. "
    "Do not add prices, royalties, statistics, or other trivia unless the user asked. "
    "If you are unsure, say so briefly instead of guessing wrong artist/title."
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
    "Output ONLY the compact numeric answer with unit or currency code "
    "(e.g. '30.48 cm', '0.11 USD'). "
    "No sentences, explanations, caveats, dates, or exchange-rate commentary. "
    "Never answer in prose."
)

CODE = (
    "The user wants a minimal code snippet. Output ONLY the code—no markdown fences, no prose. "
    "Prefer a single function or idiom; match language if they name one (python, js, etc.)."
)

EXPAND = (
    "The user wants prose expansion (e.g. meeting notes, email boilerplate). "
    "Output ONLY the expanded text body—no preamble or quotes."
)

# "what is this song…" must NOT match—only quantity-style "what is 5 ft", "what is $10", etc.
_RE_CONVERT_HINT = re.compile(
    r"""
    (?:
      \b(?:convert|turn|change)\b
      | \bwhat(?:'s|s|)\s+is\s+(?:\d|[\$€£])
      | \b(?:how\s+(?:many|much|far))\b
      | \d+\s*(?:km|mi|ft|lbs?|kg|g|oz|m|cm|mm|in|yd|
                 mph|kph|celsius|fahrenheit|kelvin|
                 litre|liter|gallon|pint|quart|cup|
                 tbsp|tsp|acre|hectare|watt|volt|amp|
                 byte|kb|mb|gb|tb)\b
      | \b(?:to|into|in)\s+(?:km|mi|ft|lbs?|kg|g|oz|m|cm|mm|in|yd|
                               mph|kph|celsius|fahrenheit|kelvin|
                               metre|meter|litre|liter|gallon|pint|
                               quart|byte|kilobyte|megabyte|gigabyte)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def attach_context(
    base_system: str,
    *,
    focused_app: str = "",
    prior_words: str = "",
) -> str:
    """Append environment context for L3 (does not affect intent classify() routing)."""
    parts = [base_system.rstrip()]
    app = (focused_app or "").strip()
    prior = re.sub(r"\s+", " ", (prior_words or "").strip())
    if app and app != "unknown":
        parts.append(
            'Context: the user\'s focused application is "'
            + app[:200]
            + '". Adjust tone and formatting when relevant.'
        )
    if prior:
        parts.append(
            "Context: words typed immediately before this request (may be incomplete): " + prior[:500]
        )
    return "\n\n".join(parts).strip()


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
    if _RE_CONVERT_HINT.search(low):
        return t, CONVERT
    if len(t.split()) <= 2 and not any(c in t for c in "/\\"):
        return t, DEFAULT
    return t, DEFAULT
