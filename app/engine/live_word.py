"""
Live typing: cooldown + resolver wrapper.

Core deterministic stages live in `app/engine/live_resolve.py` and guards in `app/engine/guards.py`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from app.cache.service import CacheService
from app.engine.guards import is_safe_word, preserve_case, ratio_exceeds
from app.engine.live_resolve import live_cache_prompt, resolve_live_phrase, resolve_live_word

if TYPE_CHECKING:
    from app.autocorrect.engine import AutocorrectEngine
    from app.snippets.engine import SnippetEngine

__all__ = [
    "LiveFixCooldown",
    "LiveWordResolver",
    "is_safe_word",
    "preserve_case",
    "ratio_exceeds",
    "live_cache_prompt",
    "resolve_live_word",
    "resolve_live_phrase",
]


@dataclass
class LiveWordResolver:
    snippets: "SnippetEngine"
    autocorrect: "AutocorrectEngine"
    cache: CacheService
    model: str
    min_word_len: int = 3
    fuzzy_enabled: bool = True
    cache_enabled: bool = True
    fuzzy_threshold: int = 92
    perf: bool = False

    def resolve(self, word: str) -> Optional[str]:
        stage_ms = {} if self.perf else None
        out = resolve_live_word(
            word,
            autocorrect=self.autocorrect,
            snippets=self.snippets,
            cache=self.cache,
            model=self.model,
            min_word_len=self.min_word_len,
            fuzzy_enabled=self.fuzzy_enabled,
            cache_enabled=self.cache_enabled,
            fuzzy_threshold=self.fuzzy_threshold,
            stage_ms=stage_ms,
        )
        if stage_ms:
            from app.utils.log import get_logger

            get_logger(__name__).info("live_word perf ms: %s", stage_ms)
        return out

    def resolve_phrase(self, phrase: str) -> Optional[str]:
        stage_ms = {} if self.perf else None
        out = resolve_live_phrase(
            phrase,
            autocorrect=self.autocorrect,
            snippets=self.snippets,
            cache=self.cache,
            model=self.model,
            min_word_len=self.min_word_len,
            fuzzy_enabled=self.fuzzy_enabled,
            cache_enabled=self.cache_enabled,
            fuzzy_threshold=self.fuzzy_threshold,
            stage_ms=stage_ms,
        )
        if stage_ms:
            from app.utils.log import get_logger

            get_logger(__name__).info("live_phrase perf ms: %s", stage_ms)
        return out


class LiveFixCooldown:
    def __init__(self, min_interval_s: float) -> None:
        self._min = max(0.0, float(min_interval_s))
        self._last = 0.0

    def can_fix(self) -> bool:
        if self._min <= 0:
            return True
        return time.monotonic() - self._last >= self._min

    def mark(self) -> None:
        self._last = time.monotonic()
