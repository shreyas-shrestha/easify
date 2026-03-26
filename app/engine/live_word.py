"""
Live word resolution: strict pipeline, no AI — must stay sub‑millisecond.

Order: safety → autocorrect dict → snippet exact → fuzzy snippet (optional) → cache (optional).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from rapidfuzz import fuzz

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.autocorrect.engine import AutocorrectEngine
    from app.cache.store import SqliteExpansionCache
    from app.snippets.engine import SnippetEngine

LOG = get_logger(__name__)

_LIVE_CACHE_TAG = "easify:live_word:v1"


def live_cache_prompt(word: str) -> str:
    return f"{_LIVE_CACHE_TAG}\n{word.strip().lower()}"


def is_safe_word(word: str, *, min_len: int = 3) -> bool:
    """
    Reject noisy / risky tokens so live replace never feels "random".
    `min_len`: reject when len(word) < min_len (default 3 ⇒ same as "≤2 char" rule).
    """
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


def ratio_exceeds(a: str, b: str, threshold: float) -> bool:
    return float(fuzz.ratio(a.lower(), b.lower())) > threshold


def preserve_case(word: str, replacement: str) -> str:
    if word.isupper():
        return replacement.upper()
    if word[:1].isupper() and len(word) > 1 and word[1:].islower():
        return replacement[:1].upper() + replacement[1:] if replacement else replacement
    return replacement


@dataclass
class LiveWordResolver:
    """Heart of live typing: deterministic layers only (explicit order)."""

    snippets: "SnippetEngine"
    autocorrect: "AutocorrectEngine"
    cache: "SqliteExpansionCache"
    model: str
    min_word_len: int = 3
    fuzzy_enabled: bool = True
    cache_enabled: bool = True
    fuzzy_threshold: int = 92

    def resolve(self, word: str) -> Optional[str]:
        return resolve_live_word(
            word,
            autocorrect=self.autocorrect,
            snippets=self.snippets,
            cache=self.cache,
            model=self.model,
            min_word_len=self.min_word_len,
            fuzzy_enabled=self.fuzzy_enabled,
            cache_enabled=self.cache_enabled,
            fuzzy_threshold=self.fuzzy_threshold,
        )


def resolve_live_word(
    word: str,
    *,
    autocorrect: "AutocorrectEngine",
    snippets: "SnippetEngine",
    cache: "SqliteExpansionCache",
    model: str,
    min_word_len: int = 3,
    fuzzy_enabled: bool = True,
    cache_enabled: bool = True,
    fuzzy_threshold: int = 92,
) -> Optional[str]:
    """
    Exact product order — no AI, no network.
    Missing any step → fall through; final None ⇒ do nothing.
    """
    if not is_safe_word(word, min_len=min_word_len):
        return None

    wl = word.lower()

    # 1. Autocorrect dictionary (exact key)
    r = autocorrect.lookup_word(wl)
    if r is not None:
        out = preserve_case(word, r)
        if out != word:
            return out

    # 2. Exact snippet
    hit = snippets.resolve_exact(wl)
    if hit is not None and hit.value != word:
        if "\n" in hit.value or len(hit.value) > 2000:
            LOG.debug("skip huge snippet for live word")
            return None
        return hit.value

    # 3. Fuzzy snippet (high confidence only)
    if fuzzy_enabled:
        cutoff = min(100, max(50, int(fuzzy_threshold) + 1))
        fz = snippets.resolve_fuzzy_ratio(wl, cutoff)
        if fz is not None and fz.value != word:
            if not ratio_exceeds(wl, fz.key, float(fuzzy_threshold)):
                return None
            if "\n" in fz.value or len(fz.value) > 2000:
                return None
            return fz.value

    # 4. Cache lookup
    if cache_enabled:
        ck = live_cache_prompt(wl)
        cached = cache.get(model, ck)
        if cached and cached.strip() and cached.strip() != word:
            return cached.strip()

    return None


class LiveFixCooldown:
    """Minimum gap between live replacements (anti-spam while typing fast)."""

    def __init__(self, min_interval_s: float) -> None:
        self._min = max(0.0, float(min_interval_s))
        self._last = 0.0

    def can_fix(self) -> bool:
        if self._min <= 0:
            return True
        return time.monotonic() - self._last >= self._min

    def mark(self) -> None:
        self._last = time.monotonic()
