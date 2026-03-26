"""Dependency protocols for testability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.cache.service import CacheService

if TYPE_CHECKING:
    from app.autocorrect.engine import AutocorrectEngine
    from app.engine.actions import LiveResult
    from app.snippets.engine import SnippetEngine


class LivePipelineDeps(Protocol):
    def expand_live_word(self, word: str) -> "LiveResult": ...

    def expand_live_phrase(self, phrase: str) -> "LiveResult": ...


class CapturePipelineDeps(Protocol):
    """Future: inject ExpansionPipeline, CacheService, semantic index for deterministic tests."""

    pass


class DefaultLivePipelineDeps:
    """Wiring for production: wraps resolve_live_word_detail / phrase."""

    def __init__(
        self,
        *,
        autoc: "AutocorrectEngine",
        snippets: "SnippetEngine",
        cache: CacheService,
        model: str,
        min_word_len: int,
        fuzzy_enabled: bool,
        cache_enabled: bool,
        fuzzy_threshold: int,
        perf: bool,
    ) -> None:
        from app.engine.actions import live_detail_to_result
        from app.engine.live_resolve import resolve_live_phrase_detail, resolve_live_word_detail

        self._autoc = autoc
        self._snippets = snippets
        self._cache = cache
        self._model = model
        self._min_word_len = min_word_len
        self._fuzzy_enabled = fuzzy_enabled
        self._cache_enabled = cache_enabled
        self._fuzzy_threshold = fuzzy_threshold
        self._perf = perf
        self._resolve_word_detail = resolve_live_word_detail
        self._resolve_phrase_detail = resolve_live_phrase_detail
        self._to_result = live_detail_to_result

    def expand_live_word(self, word: str) -> "LiveResult":
        stage_ms: dict[str, float] | None = {} if self._perf else None
        d = self._resolve_word_detail(
            word,
            autocorrect=self._autoc,
            snippets=self._snippets,
            cache=self._cache,
            model=self._model,
            min_word_len=self._min_word_len,
            fuzzy_enabled=self._fuzzy_enabled,
            cache_enabled=self._cache_enabled,
            fuzzy_threshold=self._fuzzy_threshold,
            stage_ms=stage_ms,
        )
        return self._to_result(text=d.text, source=d.source, fuzzy_ratio=d.fuzzy_ratio)

    def expand_live_phrase(self, phrase: str) -> "LiveResult":
        stage_ms: dict[str, float] | None = {} if self._perf else None
        d = self._resolve_phrase_detail(
            phrase,
            autocorrect=self._autoc,
            snippets=self._snippets,
            cache=self._cache,
            model=self._model,
            min_word_len=self._min_word_len,
            fuzzy_enabled=self._fuzzy_enabled,
            cache_enabled=self._cache_enabled,
            fuzzy_threshold=self._fuzzy_threshold,
            stage_ms=stage_ms,
        )
        return self._to_result(text=d.text, source=d.source, fuzzy_ratio=d.fuzzy_ratio)
