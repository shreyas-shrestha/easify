"""Background worker + inject queue — serializes paste so hooks never recurse."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from app.ai import prompts
from app.ai.factory import build_chat_provider
from app.autocorrect.engine import AutocorrectEngine
from app.cache.store import SqliteExpansionCache
from app.config.settings import Settings
from app.context.focus import get_focused_app_name
from app.engine.l0_compute import FxRateCache
from app.engine.live_word import live_cache_prompt
from app.engine.pipeline import ExpansionPipeline
from app.snippets.engine import SnippetEngine
from app.utils import clipboard as cb
from app.utils.log import get_logger
from app.utils.metrics import Metrics

LOG = get_logger(__name__)


@dataclass
class ExpansionJob:
    capture: str
    delete_count: int
    prior_words: str = ""


@dataclass(frozen=True)
class LiveEnrichJob:
    dedup_key: str
    cache_prompt: str
    user_text: str
    system: str


class ExpansionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.snippets = SnippetEngine(
            settings.snippets_paths,
            fuzzy_score_cutoff=settings.fuzzy_score_cutoff,
            max_keys=settings.fuzzy_max_keys,
        )
        self.autocorrect = AutocorrectEngine(settings.autocorrect_path)
        self.cache = SqliteExpansionCache(settings.cache_db_path, entry_ttl_sec=settings.cache_ttl_sec)
        self.fx_cache = FxRateCache(settings.cache_db_path.parent / "fx_rates.json")
        self.llm = build_chat_provider(settings)
        self.pipeline = ExpansionPipeline(
            snippets=self.snippets,
            autocorrect=self.autocorrect,
            cache=self.cache,
            llm=self.llm,
            fx_cache=self.fx_cache,
            verbose=settings.verbose,
            perf=settings.perf,
        )
        self.metrics: Optional[Metrics] = (
            Metrics(settings.cache_db_path.parent / "metrics.json") if settings.metrics_enabled else None
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue[ExpansionJob]] = None
        self._enrich_queue: Optional[asyncio.Queue[LiveEnrichJob]] = None
        self._enrich_inflight: set[str] = set()
        self._enrich_rate_window: deque[float] = deque()
        self._ready = threading.Event()
        self._inject_lock = threading.Lock()
        self._tray_lock = threading.Lock()
        self._tray_status = "idle"
        self._tray_detail = ""
        self._tray_last_error = ""
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
    def inject_lock(self) -> threading.Lock:
        return self._inject_lock

    def tray_snapshot(self) -> tuple[str, str, str]:
        with self._tray_lock:
            return self._tray_status, self._tray_detail, self._tray_last_error

    def tray_set_thinking(self, preview: str = "") -> None:
        with self._tray_lock:
            self._tray_status = "thinking"
            self._tray_detail = preview[:120]
            self._tray_last_error = ""

    def tray_set_idle(self, last_expansion: str = "") -> None:
        with self._tray_lock:
            self._tray_status = "idle"
            self._tray_detail = last_expansion[:220]
            self._tray_last_error = ""

    def tray_set_error(self, message: str) -> None:
        with self._tray_lock:
            self._tray_status = "error"
            self._tray_last_error = message[:500]
            if message:
                self._tray_detail = message[:120]

    @property
    def cache_model_id(self) -> str:
        return self.llm.cache_model_id

    def _enrich_under_rate_cap(self) -> bool:
        cap = self.settings.live_enrich_max_per_minute
        if cap <= 0:
            return True
        now = time.monotonic()
        while self._enrich_rate_window and self._enrich_rate_window[0] < now - 60.0:
            self._enrich_rate_window.popleft()
        return len(self._enrich_rate_window) < cap

    def _record_enrich_queued(self) -> None:
        self._enrich_rate_window.append(time.monotonic())

    def schedule_live_cache_enrich_word(self, word: str) -> None:
        if not self.settings.live_cache_enrich or not self.settings.live_cache:
            return
        if self._loop is None or self._enrich_queue is None:
            return
        w = word.strip()
        if len(w) < self.settings.live_enrich_min_len or len(w) > 64:
            return
        if not self._enrich_under_rate_cap():
            return
        ck = live_cache_prompt(w)
        model = self.llm.cache_model_id
        if self.cache.get(model, ck):
            return
        dk = f"{model}\x00{ck}"
        if dk in self._enrich_inflight:
            return
        self._enrich_inflight.add(dk)
        job = LiveEnrichJob(
            dedup_key=dk,
            cache_prompt=ck,
            user_text=w,
            system=prompts.LIVE_WORD_ENRICH,
        )
        fut = asyncio.run_coroutine_threadsafe(self._enqueue_live_enrich(job), self._loop)

        def _cb(f: asyncio.Future) -> None:
            try:
                f.result()
            except Exception as e:
                LOG.debug("enqueue live enrich: %s", e)
                self._enrich_inflight.discard(job.dedup_key)

        fut.add_done_callback(_cb)

    def schedule_live_cache_enrich_phrase(self, phrase: str) -> None:
        if not self.settings.live_cache_enrich or not self.settings.live_cache:
            return
        if self._loop is None or self._enrich_queue is None:
            return
        p = re.sub(r"\s+", " ", phrase.strip())
        if len(p) < 5 or len(p) > 240:
            return
        if not self._enrich_under_rate_cap():
            return
        ck = live_cache_prompt(p)
        model = self.llm.cache_model_id
        if self.cache.get(model, ck):
            return
        dk = f"{model}\x00{ck}"
        if dk in self._enrich_inflight:
            return
        self._enrich_inflight.add(dk)
        job = LiveEnrichJob(
            dedup_key=dk,
            cache_prompt=ck,
            user_text=p,
            system=prompts.LIVE_PHRASE_ENRICH,
        )
        fut = asyncio.run_coroutine_threadsafe(self._enqueue_live_enrich(job), self._loop)

        def _cb(f: asyncio.Future) -> None:
            try:
                f.result()
            except Exception as e:
                LOG.debug("enqueue live enrich phrase: %s", e)
                self._enrich_inflight.discard(job.dedup_key)

        fut.add_done_callback(_cb)

    async def _enqueue_live_enrich(self, job: LiveEnrichJob) -> None:
        if self._enrich_queue is None:
            self._enrich_inflight.discard(job.dedup_key)
            return
        if self._enrich_queue.full():
            self._enrich_inflight.discard(job.dedup_key)
            return
        await self._enrich_queue.put(job)
        self._record_enrich_queued()
        if self.metrics is not None:
            self.metrics.incr("live_enrich_queued")

    async def _run_live_enrich_job(self, client: httpx.AsyncClient, job: LiveEnrichJob) -> None:
        model = self.llm.cache_model_id
        if self.cache.get(model, job.cache_prompt):
            return
        try:
            text = await self.llm.generate(client, job.user_text, job.system)
        except Exception as e:
            LOG.debug("live enrich ollama: %s", e)
            return
        t = (text or "").strip()
        if not t:
            return
        if self.settings.live_enrich_skip_same and t.lower() == job.user_text.lower():
            return
        self.cache.put(model, job.cache_prompt, t, source="bg")
        if self.metrics is not None:
            self.metrics.incr("live_enrich_cached")
        if self.settings.verbose:
            LOG.info("live cache enriched key=%r", job.cache_prompt[:48])

    async def _live_enrich_worker(self, client: httpx.AsyncClient) -> None:
        assert self._enrich_queue is not None
        sem = asyncio.Semaphore(self.settings.live_enrich_max_concurrent)
        while True:
            job = await self._enrich_queue.get()
            try:
                async with sem:
                    await self._run_live_enrich_job(client, job)
            except Exception as e:
                LOG.debug("live enrich job error: %s", e)
            finally:
                self._enrich_inflight.discard(job.dedup_key)

    def start(self) -> None:
        qmax = max(4, self.settings.live_enrich_queue_max)

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._queue = asyncio.Queue()
            self._enrich_queue = asyncio.Queue(maxsize=qmax)
            self._ready.set()

            async def main_co() -> None:
                timeout = httpx.Timeout(self.settings.ollama_timeout_s, connect=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    await asyncio.gather(
                        self._consume(client),
                        self._live_enrich_worker(client),
                    )

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
                self.tray_set_thinking(job.capture)
                focused = ""
                if self.settings.context_include_focused_app:
                    focused = await asyncio.to_thread(get_focused_app_name)
                outcome = await self.pipeline.expand(
                    job.capture,
                    client,
                    focused_app=focused,
                    prior_words=job.prior_words,
                )
                if not outcome.text:
                    LOG.warning("empty expansion result (%s)", outcome.layer)
                    self.tray_set_error(f"empty result ({outcome.layer})")
                    continue
                prev = outcome.text
                short = prev if len(prev) <= 100 else prev[:97] + "…"
                self.tray_set_idle(short)
                if self.settings.expansion_preview:
                    from app.ui.preview import confirm_expansion

                    ok = await asyncio.to_thread(confirm_expansion, outcome.text)
                    if not ok:
                        self.tray_set_idle("preview cancelled")
                        continue
                await asyncio.to_thread(self._apply_replacement, job.delete_count, outcome.text, outcome.layer)
            except Exception as e:
                self.tray_set_error(str(e))
                LOG.exception("expansion failed: %s", e)

    def _apply_replacement(self, delete_count: int, text: str, layer: str) -> None:
        if self._delete_fn is None or self._paste_fn is None:
            LOG.error("inject not configured")
            return
        injected_ok = False
        with self._inject_lock:
            try:
                LOG.info("inject layer=%s delete=%s", layer, delete_count)
                self._delete_fn(delete_count)
                time.sleep(self.settings.after_delete_ms / 1000.0)
                if self._type_fn is not None and self.settings.inject_prefer_type:
                    try:
                        self._type_fn(text)
                        injected_ok = True
                    except Exception as e:
                        LOG.warning("type inject failed, using clipboard: %s", e)
                if not injected_ok:
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
                    injected_ok = True
            finally:
                if injected_ok and self.metrics is not None:
                    self.metrics.incr("capture_injections")

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
        m = self.llm.cache_model_id
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
