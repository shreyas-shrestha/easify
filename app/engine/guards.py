"""Safety guards and small text helpers shared by live + capture paths."""

from __future__ import annotations

import unicodedata

from rapidfuzz import fuzz


def text_suggests_ime_mid_composition(word: str) -> bool:
    """
    Best-effort: skip live autocorrect when the token might be mid-IME composition.

    pynput does not expose IME preedit state; Latin composition (e.g. pinyin) cannot be
    detected here. We catch common non-Latin scripts, Jamo blocks, and combining marks.
    """
    if not word:
        return False
    for ch in word:
        if len(ch) != 1:
            return True
        o = ord(ch)
        if 0x1100 <= o <= 0x11FF or 0x302E <= o <= 0x302F:
            return True
        if 0x2E80 <= o <= 0xA4CF or 0xF900 <= o <= 0xFAFF:
            return True
        if 0xAC00 <= o <= 0xD7A3:
            return True
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:
            return True
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF:
            return True
        if 0x0E00 <= o <= 0x0E7F:
            return True
        if 0x0900 <= o <= 0x097F or 0x0980 <= o <= 0x09FF:
            return True
        if 0x0D80 <= o <= 0x0DFF:
            return True
        if 0xA000 <= o <= 0xA48F or 0xA490 <= o <= 0xA4CF:
            return True
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Mc", "Me"):
            return True
    return False


def is_safe_word(word: str, *, min_len: int = 3) -> bool:
    if not word:
        return False
    if text_suggests_ime_mid_composition(word):
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
