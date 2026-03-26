"""Background worker + inject queue — serializes paste so hooks never recurse."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from app.cache.store import SqliteExpansionCache
from app.config.settings import Settings
from app.engine.pipeline import ExpansionPipeline
from app.ai.ollama import OllamaClient
from app.autocorrect.engine import AutocorrectEngine
from app.snippets.engine import SnippetEngine
from app.utils import clipboard as cb
from app.utils.log import get_logger

LOG = get_logger(__name__)


@dataclass
class ExpansionJob:
    capture: str
    delete_count: int


class ExpansionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.snippets = SnippetEngine(
            settings.snippets_paths,
            fuzzy_score_cutoff=settings.fuzzy_score_cutoff,
            max_keys=settings.fuzzy_max_keys,
        )
        self.autocorrect = AutocorrectEngine(settings.autocorrect_path)
        self.cache = SqliteExpansionCache(settings.cache_db_path)
        self.ollama = OllamaClient(
            settings.ollama_url,
            settings.ollama_model,
            timeout_s=settings.ollama_timeout_s,
            retries=settings.ollama_retries,
        )
        self.pipeline = ExpansionPipeline(
            snippets=self.snippets,
            autocorrect=self.autocorrect,
            cache=self.cache,
            ollama=self.ollama,
            verbose=settings.verbose,
            perf=settings.perf,
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue[ExpansionJob]] = None
        self._ready = threading.Event()
        self._inject_busy = threading.Event()
        self._delete_fn: Optional[Callable[[int], None]] = None
        self._paste_fn: Optional[Callable[[str], None]] = None
        self._type_fn: Optional[Callable[[str], None]] = None

    def set_inject(
        self,
        delete_fn: Callable[[int], None],
        paste_fn: Callable[[str], None],
        type_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._delete_fn = delete_fn
        self._paste_fn = paste_fn
        self._type_fn = type_fn

    @property
    def inject_busy(self) -> threading.Event:
        return self._inject_busy

    def start(self) -> None:
        box: list[Any] = []

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._queue = asyncio.Queue()
            box.append(self._queue)
            self._ready.set()

            async def main_co() -> None:
                timeout = httpx.Timeout(self.settings.ollama_timeout_s, connect=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    await self._consume(client)

            loop.run_until_complete(main_co())

        self._thread = threading.Thread(target=runner, daemon=True, name="easify-async")
        self._thread.start()
        if not self._ready.wait(timeout=20.0):
            raise RuntimeError("Easify async worker failed to start")

    def submit(self, job: ExpansionJob) -> None:
        if self._loop is None or self._queue is None:
            LOG.error("worker not ready")
            return
        asyncio.run_coroutine_threadsafe(self._queue.put(job), self._loop)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _consume(self, client: httpx.AsyncClient) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            try:
                outcome = await self.pipeline.expand(job.capture, client)
                if not outcome.text:
                    LOG.warning("empty expansion result (%s)", outcome.layer)
                    continue
                await asyncio.to_thread(self._apply_replacement, job.delete_count, outcome.text, outcome.layer)
            except Exception as e:
                LOG.exception("expansion failed: %s", e)

    def _apply_replacement(self, delete_count: int, text: str, layer: str) -> None:
        if self._delete_fn is None or self._paste_fn is None:
            LOG.error("inject not configured")
            return
        self._inject_busy.set()
        try:
            LOG.info("inject layer=%s delete=%s", layer, delete_count)
            self._delete_fn(delete_count)
            time.sleep(self.settings.after_delete_ms / 1000.0)
            if self._type_fn is not None and self.settings.inject_prefer_type:
                try:
                    self._type_fn(text)
                    return
                except Exception as e:
                    LOG.warning("type inject failed, using clipboard: %s", e)
            if self.settings.clipboard_restore:
                prev = cb.get_clipboard()
                try:
                    cb.set_clipboard(text)
                    time.sleep(self.settings.paste_delay_ms / 1000.0)
                    self._paste_fn(text)
                finally:

                    def _restore() -> None:
                        time.sleep(0.35)
                        try:
                            cb.set_clipboard(prev)
                        except Exception:
                            pass

                    threading.Thread(target=_restore, daemon=True).start()
            else:
                cb.set_clipboard(text)
                time.sleep(self.settings.paste_delay_ms / 1000.0)
                self._paste_fn(text)
        finally:
            self._inject_busy.clear()

    def preload_cache_metadata(self) -> None:
        """Log cache stats + optional warmup file listing (no automatic LLM fan-out)."""
        st = self.cache.stats()
        LOG.info("cache entries=%s total_hits=%s", st["entries"], st["total_hits"])
        p = self.settings.warmup_prompts_path
        if p and p.is_file():
            LOG.info("warmup list present: %s", p)

    def prewarm_cache(self) -> None:
        """Load SQLite hot paths + touch live-cache keys from warmup list — no AI."""
        import json

        from app.engine.live_word import live_cache_prompt

        p = self.settings.warmup_prompts_path
        if not p or not p.is_file():
            LOG.info("prewarm: no warmup list at %s", p)
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            LOG.warning("prewarm: read failed: %s", e)
            return
        if not isinstance(raw, list):
            return
        m = self.settings.ollama_model
        n = 0
        for item in raw:
            if not isinstance(item, str):
                continue
            w = item.strip()
            if not w:
                continue
            _ = self.cache.get(m, live_cache_prompt(w.lower()))
            n += 1
        self.snippets.reload()
        self.autocorrect.reload()
        LOG.info("prewarm: SQLite + snippets/autocorrect reload (%s warmup keys)", n)
