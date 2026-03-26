"""Single cache façade — all reads/writes should migrate here (wraps SQLite store).

Capture/live pipelines use :class:`CacheService` only; SQLite lives in :mod:`app.cache.store`.
"""

from __future__ import annotations

from typing import Any, Optional

from app.cache.store import SqliteExpansionCache


class CacheService:
    """Façade for cache reads/writes. Migrate new code here; internal store stays SqliteExpansionCache."""

    def __init__(self, store: SqliteExpansionCache) -> None:
        self._store = store

    @property
    def store(self) -> SqliteExpansionCache:
        return self._store

    def lookup_capture(self, model: str, prompt: str) -> tuple[Optional[str], int, str]:
        """Full capture-path lookup with hit_count + source."""
        return self._store.lookup(model, prompt)

    def lookup_live(self, model: str, prompt: str) -> Optional[str]:
        """Live path read (updates hit stats like ``get``)."""
        return self._store.get(model, prompt)

    def store_ai_result(self, model: str, prompt: str, response: str, *, source: str = "ai") -> None:
        self._store.put(model, prompt, response, source=source)

    def store_live_enrich(self, model: str, prompt: str, response: str) -> None:
        """Background live-cache enrichment (distinct source for stats/promotion rules)."""
        self._store.put(model, prompt, response, source="bg")

    def lookup(self, model: str, prompt: str) -> tuple[Optional[str], int, str]:
        return self._store.lookup(model, prompt)

    def get(self, model: str, prompt: str) -> Optional[str]:
        return self._store.get(model, prompt)

    def peek(self, model: str, prompt: str) -> Optional[str]:
        return self._store.peek(model, prompt)

    def put(self, model: str, prompt: str, response: str, *, source: str = "ai") -> None:
        self.store_ai_result(model, prompt, response, source=source)

    def top_keys(self, limit: int = 100) -> list[tuple[str, int, str]]:
        return self._store.top_keys(limit)

    def stats(self) -> dict[str, Any]:
        return self._store.stats()

    def close(self) -> None:
        self._store.close()
