"""Open cache store + façade from settings (SQLite stays under :mod:`app.cache`)."""

from __future__ import annotations

from app.cache.service import CacheService
from app.cache.store import SqliteExpansionCache
from app.config.settings import Settings


def open_cache_service(settings: Settings) -> CacheService:
    store = SqliteExpansionCache(settings.cache_db_path, entry_ttl_sec=settings.cache_ttl_sec)
    return CacheService(store)
