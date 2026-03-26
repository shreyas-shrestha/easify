"""Background worker + inject queue — serializes paste so hooks never recurse."""

from __future__ import annotations

import asyncio
import platform
import re
import threading
import time
import traceback
from collections import deque
from typing import Any, Callable, Optional

import httpx

from app.ai import prompts
from app.ai.factory import build_chat_provider
from app.autocorrect.engine import AutocorrectEngine
from app.cache.store import SqliteExpansionCache
from app.config.settings import Settings
from app.context.focus import (
    get_focused_app_name,
    inject_focus_safe_for_keys,
    layer_warrants_pre_inject_refocus,
    refocus_if_needed_for_inject,
)
from app.engine.l0_compute import FxRateCache
from app.engine.live_word import live_cache_prompt
from app.engine.pending_tail import PendingExpansionTail
from app.engine.pipeline import ExpansionPipeline
from app.engine.tray_controller import TrayController
from app.engine.types import ExpansionJob, LiveEnrichJob, TraySnapshot, UndoFrame
from app.engine.undo_stack import UndoStack
from app.snippets.engine import SnippetEngine
from app.utils import clipboard as cb
from app.utils.expansion_log import append_expansion_record
from app.utils.live_enrich_blocklist import should_skip_live_enrich_token
from app.utils.log import get_logger
from app.utils.metrics import Metrics

LOG = get_logger(__name__)

# Expansion worker: limit tight loops when ``pipeline.expand`` or later stages fail repeatedly.
_CONSUME_BACKOFF_CAP_S = 30.0
_CONSUME_BACKOFF_BASE_S = 0.5
_CONSUME_CIRCUIT_AFTER = 5
_CONSUME_CIRCUIT_EXTRA_S = 12.0
_DEAD_LETTER_MAX = 48

# Tests historically imported the private name; ``PendingExpansionTail`` is the supported type.
_PendingExpansionTail = PendingExpansionTail


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
        self.semantic_index = None
        if settings.semantic_snippets:
            from app.snippets.semantic_index import SnippetSemanticIndex

            self.semantic_index = SnippetSemanticIndex(self.snippets, settings)
        touch = self._on_cache_touch if settings.cache_promote_min_hits > 0 else None
        self.pipeline = ExpansionPipeline(
            snippets=self.snippets,
            autocorrect=self.autocorrect,
            cache=self.cache,
            llm=self.llm,
            fx_cache=self.fx_cache,
            semantic_index=self.semantic_index,
            on_cache_touch=touch,
            snippet_namespace_lenient=settings.snippet_namespace_lenient,
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
        self._enrich_inflight_lock = threading.Lock()
        self._main_thread_runner: Optional[Callable[[Callable[[], None]], None]] = None
        self._enrich_rate_window: deque[float] = deque()
        self._ready = threading.Event()
        self._inject_lock = threading.Lock()
        self._tray = TrayController(settings)
        self._delete_fn: Optional[Callable[[int], None]] = None
        self._paste_fn: Optional[Callable[[str], None]] = None
        self._type_fn: Optional[Callable[[str], None]] = None
        self._cursor_left_fn: Optional[Callable[[int], None]] = None
        self._undo = UndoStack(settings.undo_stack_max)
        self._pending_tails: deque[PendingExpansionTail] = deque()
        self._pending_tail_lock = threading.Lock()
        self._consume_consecutive_failures = 0
        self._expansion_dead_letter: deque[dict[str, Any]] = deque(maxlen=_DEAD_LETTER_MAX)

    @property
    def _undo_lock(self) -> threading.Lock:
        return self._undo.lock

    @property
    def _undo_stack(self) -> deque[UndoFrame]:
        return self._undo.items

    def has_pending_expansion_tail(self) -> bool:
        with self._pending_tail_lock:
            return len(self._pending_tails) > 0

    def append_expansion_tail_char(self, ch: str) -> None:
        """Record a keystroke typed while an expansion is in flight (must match apply order)."""
        with self._pending_tail_lock:
            if not self._pending_tails:
                return
            pe = self._pending_tails[0]
        pe.append_char(ch)

    def _pop_tail_for_job(self, job: ExpansionJob) -> str:
        """Remove head pending tail if it matches job; return concatenated tail text."""
        with self._pending_tail_lock:
            if not self._pending_tails or self._pending_tails[0].job is not job:
                LOG.warning(
                    "expansion tail mismatch (queue desync) — applying without tail buffer fix-up"
                )
                return ""
            pe = self._pending_tails.popleft()
        return pe.drain_joined()

    def _discard_pending_tail(self, job: ExpansionJob) -> None:
        with self._pending_tail_lock:
            if not self._pending_tails:
                return
            if self._pending_tails[0].job is not job:
                LOG.debug("discard tail: job not at queue head")
                return
            self._pending_tails.popleft()

    def _on_cache_touch(self, cache_prompt: str, response: str, hit_count: int, source: str) -> None:
        from app.snippets.promote import maybe_promote_cache_hit

        if maybe_promote_cache_hit(
            user_snippets=self.settings.user_snippets_path(),
            config_dir=self.settings.cache_db_path.parent,
            cache_prompt=cache_prompt,
            response=response,
            hit_count=hit_count,
            source=source,
            min_hits=self.settings.cache_promote_min_hits,
            allowed_sources=self.settings.cache_promote_source_set(),
            max_promoted_keys=self.settings.cache_promote_max_keys,
        ):
            self.snippets.reload()

    def set_undo_frame(self, injected: str, restore: str, *, via_accessibility: bool = False) -> None:
        self._undo.push(
            UndoFrame(injected=injected, restore=restore, via_accessibility=via_accessibility)
        )

    def _undo_apply_frame(self, frame: UndoFrame) -> bool:
        if frame.via_accessibility:
            from app.inject.accessibility import replace_in_focused_field

            def do_ax_undo() -> bool:
                with self._inject_lock:
                    try:
                        ok = replace_in_focused_field(
                            old=frame.injected,
                            new=frame.restore or "",
                            match_last=self.settings.inject_accessibility_match_last,
                            unique_match_only=False,
                        )
                        if ok and self.metrics is not None:
                            self.metrics.incr("undo_expansions")
                        return ok
                    except Exception as e:
                        LOG.warning("accessibility undo failed: %s", e)
                        return False

            if platform.system() == "Darwin" and self._main_thread_runner is not None:
                outcome: list[Optional[bool]] = [None]
                done = threading.Event()

                def _on_main() -> None:
                    try:
                        outcome[0] = do_ax_undo()
                    finally:
                        done.set()

                self._main_thread_runner(_on_main)
                done.wait(timeout=30.0)
                return outcome[0] is True
            return do_ax_undo()
        if self._delete_fn is None:
            return False
        with self._inject_lock:
            try:
                LOG.info("undo expansion delete=%s restore_len=%s", len(frame.injected), len(frame.restore))
                self._delete_fn(len(frame.injected))
                time.sleep(self.settings.after_delete_ms / 1000.0)
                if frame.restore:
                    typed = False
                    if self._type_fn is not None and self.settings.inject_prefer_type:
                        try:
                            self._type_fn(frame.restore)
                            typed = True
                        except Exception as e:
                            LOG.warning("undo type failed: %s", e)
                    if not typed and self._paste_fn is not None:
                        cb.set_clipboard(frame.restore)
                        time.sleep(self.settings.paste_delay_ms / 1000.0)
                        self._paste_fn(frame.restore)
                if self.metrics is not None:
                    self.metrics.incr("undo_expansions")
                return True
            except Exception as e:
                LOG.warning("undo failed: %s", e)
                return False

    def try_undo(self) -> bool:
        frame = self._undo.pop()
        if frame is None:
            return False
        ok = self._undo_apply_frame(frame)
        if not ok:
            self._undo.push(frame)
        return ok

    def set_inject(
        self,
        delete_fn: Callable[[int], None],
        paste_fn: Callable[[str], None],
        type_fn: Optional[Callable[[str], None]] = None,
        cursor_left_fn: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._delete_fn = delete_fn
        self._paste_fn = paste_fn
        self._type_fn = type_fn
        self._cursor_left_fn = cursor_left_fn

    def set_main_thread_runner(self, fn: Optional[Callable[[Callable[[], None]], None]]) -> None:
        """macOS: schedule accessibility / AppKit work on the process main run loop (e.g. libdispatch)."""
        self._main_thread_runner = fn

    def _enrich_try_claim(self, dk: str) -> bool:
        with self._enrich_inflight_lock:
            if dk in self._enrich_inflight:
                return False
            self._enrich_inflight.add(dk)
            return True

    def _enrich_release(self, dk: str) -> None:
        with self._enrich_inflight_lock:
            self._enrich_inflight.discard(dk)

    @property
    def inject_lock(self) -> threading.Lock:
        return self._inject_lock

    def tray_snapshot(self) -> TraySnapshot:
        exp_q = self._queue.qsize() if self._queue is not None else 0
        enr_q = self._enrich_queue.qsize() if self._enrich_queue is not None else 0
        return self._tray.snapshot(
            expansion_queued=exp_q,
            enrich_queued=enr_q,
            undo_depth=self._undo.depth(),
            cache_model_id=self.cache_model_id,
        )

    def tray_set_thinking(self, preview: str = "") -> None:
        self._tray.set_thinking(preview)

    def tray_set_idle(self, last_expansion: str = "") -> None:
        self._tray.set_idle(last_expansion)

    def tray_set_error(self, message: str, *, degraded_hint: str = "") -> None:
        self._tray.set_error(message, degraded_hint=degraded_hint)

    def tray_clear_error(self) -> None:
        """Clear error state from the tray after the user has read or copied the message."""
        self._tray.clear_error()

    def reload_snippets_hot(self) -> None:
        """Reload snippet JSON from disk (daemon hook or snippet UI notify)."""
        self.snippets.reload()
        if self.semantic_index is not None:
            self.semantic_index.invalidate_after_file_change()
        LOG.info("snippets reloaded (hot)")

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
        if should_skip_live_enrich_token(w):
            return
        if not self._enrich_under_rate_cap():
            return
        ck = live_cache_prompt(w)
        model = self.llm.cache_model_id
        if self.cache.get(model, ck):
            return
        dk = f"{model}\x00{ck}"
        if not self._enrich_try_claim(dk):
            return
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
                self._enrich_release(job.dedup_key)

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
        if not self._enrich_try_claim(dk):
            return
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
                self._enrich_release(job.dedup_key)

        fut.add_done_callback(_cb)

    async def _enqueue_live_enrich(self, job: LiveEnrichJob) -> None:
        if self._enrich_queue is None:
            self._enrich_release(job.dedup_key)
            return
        if self._enrich_queue.full():
            self._enrich_release(job.dedup_key)
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
                self._enrich_release(job.dedup_key)

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
        with self._pending_tail_lock:
            self._pending_tails.append(PendingExpansionTail(job))
        asyncio.run_coroutine_threadsafe(self._queue.put(job), self._loop)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _journal_expansion(
        self,
        job: ExpansionJob,
        *,
        layer: str,
        result_text: str,
        ok: bool,
        error: str = "",
        inject: str = "",
    ) -> None:
        append_expansion_record(
            self.settings,
            {
                "capture": (job.capture or "")[:500],
                "layer": layer,
                "ok": ok,
                "result_preview": (result_text or "")[:240],
                "result_len": len(result_text or ""),
                "error": (error or "")[:500],
                "inject": inject,
            },
        )

    async def _consume(self, client: httpx.AsyncClient) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            journal_layer = ""
            journal_text = ""
            try:
                self.tray_set_thinking(job.capture)
                focused = ""
                if self.settings.context_include_focused_app:
                    focused = await asyncio.to_thread(get_focused_app_name)
                clip_snippet = ""
                if self.settings.context_clipboard_for_l3 and self.settings.context_clipboard_max_chars > 0:
                    raw = await asyncio.to_thread(cb.get_clipboard)
                    clip_snippet = prompts.sanitize_clipboard_context(
                        raw, self.settings.context_clipboard_max_chars
                    )
                outcome = await self.pipeline.expand(
                    job.capture,
                    client,
                    focused_app=focused,
                    prior_words=job.prior_words,
                    clipboard_snippet=clip_snippet,
                )
                self._consume_consecutive_failures = 0
                journal_layer = outcome.layer
                journal_text = outcome.text or ""
                if not outcome.text:
                    self._discard_pending_tail(job)
                    LOG.warning("empty expansion result (%s)", outcome.layer)
                    self.tray_set_error(f"empty result ({outcome.layer})")
                    self._journal_expansion(
                        job,
                        layer=outcome.layer,
                        result_text="",
                        ok=False,
                        error="empty expansion",
                    )
                    continue
                prev = outcome.text
                short = prev if len(prev) <= 100 else prev[:97] + "…"
                self.tray_set_idle(short)
                if self.settings.expansion_preview:
                    from app.ui.preview import confirm_expansion

                    ok = await asyncio.to_thread(confirm_expansion, outcome.text)
                    if not ok:
                        self._discard_pending_tail(job)
                        self.tray_set_idle("preview cancelled")
                        self._journal_expansion(
                            job,
                            layer=outcome.layer,
                            result_text=outcome.text,
                            ok=False,
                            error="preview cancelled",
                        )
                        continue
                await self._wait_tail_quiet_async(job)
                inject_kind = await asyncio.to_thread(
                    self._apply_replacement, job, outcome.text, outcome.layer
                )
                self._journal_expansion(
                    job,
                    layer=outcome.layer,
                    result_text=outcome.text,
                    ok=bool(inject_kind),
                    error="" if inject_kind else "inject did not complete",
                    inject=inject_kind,
                )
            except Exception as e:
                self._consume_consecutive_failures += 1
                streak = self._consume_consecutive_failures
                self._discard_pending_tail(job)
                self._journal_expansion(
                    job,
                    layer=journal_layer or "error",
                    result_text=journal_text,
                    ok=False,
                    error=str(e),
                )
                self._expansion_dead_letter.append(
                    {
                        "capture": (job.capture or "")[:240],
                        "error": str(e)[:400],
                        "layer": journal_layer,
                        "streak": streak,
                    }
                )
                lump = f"{e}\n{traceback.format_exc()}"
                hint = ""
                if isinstance(e, httpx.ConnectError):
                    hint = "Cannot reach the LLM HTTP endpoint (connection failed). Is Ollama running and reachable?"
                elif isinstance(e, httpx.ReadTimeout):
                    hint = (
                        f"LLM read timed out after {self.settings.ollama_timeout_s}s. "
                        "Try a smaller prompt or raise EASIFY_OLLAMA_TIMEOUT."
                    )
                elif isinstance(e, httpx.TimeoutException):
                    hint = (
                        f"LLM HTTP request timed out (client limit {self.settings.ollama_timeout_s}s). "
                        "The model may be overloaded or the prompt too large."
                    )
                self.tray_set_error(lump, degraded_hint=hint)
                LOG.exception("expansion failed (consecutive=%s): %s", streak, e)
                extra = _CONSUME_CIRCUIT_EXTRA_S if streak >= _CONSUME_CIRCUIT_AFTER else 0.0
                delay = min(
                    _CONSUME_BACKOFF_CAP_S,
                    _CONSUME_BACKOFF_BASE_S * (2 ** min(streak, 10)),
                ) + extra
                if extra:
                    LOG.error(
                        "expansion worker circuit: %s consecutive failures — added %.0fs pause before next job",
                        streak,
                        extra,
                    )
                LOG.info("expansion worker backoff %.1fs after error (streak=%s)", delay, streak)
                await asyncio.sleep(delay)

    def _wait_tail_quiet(self, job: ExpansionJob) -> None:
        """Wait until parallel tail is idle (condition + deadline) before inject."""
        settle = self.settings.inject_settle_ms / 1000.0
        if settle <= 0:
            return
        max_wait = max(0.05, self.settings.inject_settle_max_wait_ms / 1000.0)
        deadline = time.monotonic() + max_wait
        with self._pending_tail_lock:
            if not self._pending_tails or self._pending_tails[0].job is not job:
                return
            pe = self._pending_tails[0]
        pe.wait_idle_until(settle_s=settle, deadline_mono=deadline)

    async def _wait_tail_quiet_async(self, job: ExpansionJob) -> None:
        """Tail settle on a worker thread so the asyncio loop is not polled for seconds."""
        await asyncio.to_thread(self._wait_tail_quiet, job)

    def _apply_replacement(self, job: ExpansionJob, text: str, layer: str) -> str:
        if self._delete_fn is None or self._paste_fn is None:
            LOG.error("inject not configured")
            self._discard_pending_tail(job)
            return ""
        injected_ok = False
        to_inject = ""
        undo_restore = ""
        via_ax = False
        planned_ax_darwin_main = False
        tail = ""
        n_tail = 0
        synth_undo = ""
        capture_span = ""

        def _keystroke_inject_unlocked() -> None:
            nonlocal injected_ok, to_inject, undo_restore, via_ax
            undo_restore = synth_undo
            via_ax = False
            use_left = (
                n_tail > 0
                and self.settings.inject_tail_via_cursor_left
                and self._cursor_left_fn is not None
            )
            if use_left:
                to_inject = text
                delete_count = job.delete_count
                LOG.info(
                    "inject layer=%s cursor_left=%s delete=%s (parallel tail preserved, not retyped)",
                    layer,
                    n_tail,
                    delete_count,
                )
                self._cursor_left_fn(n_tail)
                time.sleep(self.settings.after_delete_ms / 1000.0)
            else:
                if n_tail > 0 and self.settings.inject_tail_via_cursor_left and self._cursor_left_fn is None:
                    LOG.warning(
                        "inject: parallel tail but no cursor_left_fn — deleting through tail (legacy)"
                    )
                delete_count = job.delete_count + n_tail
                to_inject = f"{text}{tail}"
                LOG.info(
                    "inject layer=%s delete=%s%s",
                    layer,
                    delete_count,
                    f" (capture {job.delete_count} + tail {n_tail})" if tail else "",
                )
            self._delete_fn(delete_count)
            time.sleep(self.settings.after_delete_ms / 1000.0)
            if self._type_fn is not None and self.settings.inject_prefer_type:
                try:
                    self._type_fn(to_inject)
                    injected_ok = True
                except Exception as e:
                    LOG.warning("type inject failed, using clipboard: %s", e)
            if not injected_ok:
                if self.settings.clipboard_restore:
                    prev = cb.get_clipboard()
                    try:
                        cb.set_clipboard(to_inject)
                        time.sleep(self.settings.paste_delay_ms / 1000.0)
                        self._paste_fn(to_inject)
                    finally:

                        def _restore() -> None:
                            time.sleep(0.35)
                            try:
                                cb.set_clipboard(prev)
                            except Exception:
                                pass

                        threading.Thread(target=_restore, daemon=True).start()
                else:
                    cb.set_clipboard(to_inject)
                    time.sleep(self.settings.paste_delay_ms / 1000.0)
                    self._paste_fn(to_inject)
                injected_ok = True

        with self._inject_lock:
            try:
                from app.inject.accessibility import focused_field_appears_secure

                if focused_field_appears_secure():
                    LOG.warning("inject skipped: focused control appears to be a secure/password field")
                    self._discard_pending_tail(job)
                    self.tray_set_error(
                        "Secure or password field — expansion not injected.",
                        degraded_hint="Type the result manually if needed; Easify never injects into password fields.",
                    )
                    return ""
                if self.settings.pre_inject_refocus and layer_warrants_pre_inject_refocus(layer):
                    refocus_if_needed_for_inject(captured_app=job.focused_app_at_submit)
                ok_focus, bad_focus = inject_focus_safe_for_keys(captured_app=job.focused_app_at_submit)
                if not ok_focus:
                    LOG.error("inject aborted: %s", bad_focus)
                    self._discard_pending_tail(job)
                    self.tray_set_error(bad_focus, degraded_hint="Focus safety — no keys or clipboard paste were sent.")
                    return ""
                tail = self._pop_tail_for_job(job)
                n_tail = len(tail)
                synth_undo = f"{job.undo_restore}{tail}"
                capture_span = job.undo_restore

                if self.settings.inject_via_accessibility and capture_span:
                    if platform.system() == "Darwin" and self._main_thread_runner is not None:
                        planned_ax_darwin_main = True
                    else:
                        from app.inject.accessibility import replace_in_focused_field

                        if replace_in_focused_field(
                            old=capture_span,
                            new=text,
                            match_last=self.settings.inject_accessibility_match_last,
                            unique_match_only=self.settings.inject_accessibility_unique_match_only,
                        ):
                            injected_ok = True
                            to_inject = text
                            undo_restore = capture_span
                            via_ax = True
                            LOG.info("inject layer=%s via=accessibility", layer)

                if not injected_ok and not planned_ax_darwin_main:
                    _keystroke_inject_unlocked()
            finally:
                if injected_ok and self.metrics is not None and not planned_ax_darwin_main:
                    self.metrics.incr("capture_injections")

        if planned_ax_darwin_main:
            cap = capture_span
            nv = text
            from app.inject.accessibility import replace_in_focused_field

            def do_ax_forward() -> bool:
                with self._inject_lock:
                    try:
                        ok = replace_in_focused_field(
                            old=cap,
                            new=nv,
                            match_last=self.settings.inject_accessibility_match_last,
                            unique_match_only=self.settings.inject_accessibility_unique_match_only,
                        )
                        if ok:
                            LOG.info("inject layer=%s via=accessibility", layer)
                        return ok
                    except Exception as e:
                        LOG.warning("accessibility inject failed: %s", e)
                        return False

            outcome: list[Optional[bool]] = [None]
            done = threading.Event()

            def _on_main() -> None:
                try:
                    outcome[0] = do_ax_forward()
                finally:
                    done.set()

            assert self._main_thread_runner is not None
            self._main_thread_runner(_on_main)
            if not done.wait(timeout=30.0):
                LOG.warning("accessibility inject timed out waiting for main thread")
            if outcome[0] is True:
                if self.metrics is not None:
                    self.metrics.incr("capture_injections")
                self.set_undo_frame(nv, cap, via_accessibility=True)
                return "accessibility"
            with self._inject_lock:
                try:
                    injected_ok = False
                    _keystroke_inject_unlocked()
                finally:
                    if injected_ok and self.metrics is not None:
                        self.metrics.incr("capture_injections")

        if injected_ok:
            self.set_undo_frame(to_inject, undo_restore, via_accessibility=via_ax)
            return "accessibility" if via_ax else "keystroke"
        return ""

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
            self.cache.peek(m, live_cache_prompt(w.lower()))
            n += 1
        self.snippets.reload()
        self.autocorrect.reload()
        LOG.info("prewarm: SQLite + snippets/autocorrect reload (%s warmup keys)", n)
