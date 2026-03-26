"""Safety guards and small text helpers shared by live + capture paths."""

from __future__ import annotations

from rapidfuzz import fuzz


def is_safe_word(word: str, *, min_len: int = 3) -> bool:
    if not word:
        return False
    if len(word) < int(min_len):
        return False
    if word.isupper():
        return False
    if word[0].isupper():
        return False
    if any(c.isdigit() for c in word):
        return False
    if "_" in word or "." in word or "/" in word:
        return False
    if word.startswith("http"):
        return False
    return True


def is_safe_phrase_tokens(words: list[str], *, min_len: int = 3) -> bool:
    """Every token must pass the same live guards (no surprise phrase fixes)."""
    if len(words) < 2:
        return False
    return all(is_safe_word(w, min_len=min_len) for w in words)


def preserve_case(word: str, replacement: str) -> str:
    if word.isupper():
        return replacement.upper()
    if word[:1].isupper() and len(word) > 1 and word[1:].islower():
        return replacement[:1].upper() + replacement[1:] if replacement else replacement
    return replacement


def ratio_exceeds(a: str, b: str, threshold: float) -> bool:
    return float(fuzz.ratio(a.lower(), b.lower())) > threshold
