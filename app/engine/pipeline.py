"""Layered resolution: L0 compute → L1 snippets/autocorrect → L2 fuzzy/cache → L3 LLM."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

import httpx

from app.ai import prompts
from app.ai.chat_provider import ChatProvider
from app.autocorrect.engine import AutocorrectEngine
from app.cache.store import SqliteExpansionCache
from app.engine.expansion_contracts import CacheTouchHandler, ExpansionLayer, ExpansionOutcome, l3_layer
from app.engine.l0_compute import FxRateCache, try_l0_async
from app.snippets.engine import SnippetEngine
from app.snippets.template import expand_snippet_template
from app.utils import clipboard as cb
from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.snippets.semantic_index import SnippetSemanticIndex

LOG = get_logger(__name__)


def _cache_prompt(model: str, normalized_prompt: str, system: str) -> str:
    return f"{model}\n{system}\n{normalized_prompt}"


class ExpansionPipeline:
    def __init__(
        self,
        *,
        snippets: SnippetEngine,
        autocorrect: AutocorrectEngine,
        cache: SqliteExpansionCache,
        llm: ChatProvider,
        fx_cache: FxRateCache,
        semantic_index: Optional["SnippetSemanticIndex"] = None,
        on_cache_touch: Optional[CacheTouchHandler] = None,
        snippet_namespace_lenient: bool = False,
        verbose: bool = False,
        perf: bool = False,
    ) -> None:
        self.snippets = snippets
        self.autocorrect = autocorrect
        self.cache = cache
        self.llm = llm
        self.fx_cache = fx_cache
        self.semantic_index = semantic_index
        self.on_cache_touch = on_cache_touch
        self._snippet_namespace_lenient = snippet_namespace_lenient
        self._verbose = verbose
        self._perf = perf

    def _notify_cache_touch(self, cache_key_prompt: str, text: str, hit_count: int, source: str) -> None:
        if self.on_cache_touch is not None and text:
            self.on_cache_touch(cache_key_prompt, text, hit_count, source)

    def _log_perf(self, stage_ms: dict[str, float]) -> None:
        LOG.info("capture deterministic perf (ms): %s", stage_ms)

    @staticmethod
    def _outcome_is_snippet_with_placeholders(outcome: ExpansionOutcome) -> bool:
        return "snippet" in outcome.layer and "{" in outcome.text

    def _finalize_snippet_value_sync(self, outcome: ExpansionOutcome, *, focused_app: str) -> ExpansionOutcome:
        if not self._outcome_is_snippet_with_placeholders(outcome):
            return outcome
        clip = cb.get_clipboard() if "{clipboard" in outcome.text else ""
        text = expand_snippet_template(
            outcome.text,
            focused_app=focused_app,
            clipboard=clip,
            allow_input_dialog=False,
        )
        return ExpansionOutcome(text, outcome.layer, outcome.ms)

    async def _finalize_snippet_value_async(
        self,
        outcome: ExpansionOutcome,
        *,
        focused_app: str,
        clipboard_hint: str,
    ) -> ExpansionOutcome:
        if not self._outcome_is_snippet_with_placeholders(outcome):
            return outcome
        clip = clipboard_hint
        if "{clipboard" in outcome.text and not clip:
            clip = await asyncio.to_thread(cb.get_clipboard)

        def run() -> str:
            return expand_snippet_template(
                outcome.text,
                focused_app=focused_app,
                clipboard=clip,
                allow_input_dialog=True,
            )

        text = await asyncio.to_thread(run)
        return ExpansionOutcome(text, outcome.layer, outcome.ms)

    def _try_exact_and_fuzzy_snippets(
        self,
        capture: str,
        t0: float,
        *,
        focused_app: str,
        namespace_lenient: bool,
        stage_ms: dict[str, float],
    ) -> tuple[Optional[ExpansionOutcome], str]:
        """Autocorrect + L1 exact + L2 fuzzy. Returns (hit or None, corrected phrase)."""
        t = time.perf_counter()
        corrected = self.autocorrect.apply_to_phrase(capture)
        stage_ms["autocorrect_phrase"] = (time.perf_counter() - t) * 1000.0
        if corrected != capture and self._verbose:
            LOG.info("L1 autocorrect adjusted phrase")

        t2 = time.perf_counter()
        hit = self.snippets.resolve_exact(
            corrected, focused_app=focused_app, namespace_lenient=namespace_lenient
        )
        stage_ms["snippet_exact"] = (time.perf_counter() - t2) * 1000.0
        if hit:
            ms = (time.perf_counter() - t0) * 1000.0
            if self._perf:
                self._log_perf(stage_ms)
            if self._verbose:
                LOG.info("L1 snippet exact (%s ms)", round(ms, 2))
            return ExpansionOutcome(hit.value, ExpansionLayer.L1_SNIPPET_EXACT.value, ms), corrected

        t3 = time.perf_counter()
        hit = self.snippets.resolve_fuzzy(
            corrected, focused_app=focused_app, namespace_lenient=namespace_lenient
        )
        stage_ms["snippet_fuzzy"] = (time.perf_counter() - t3) * 1000.0
        if hit:
            ms = (time.perf_counter() - t0) * 1000.0
            if self._perf:
                self._log_perf(stage_ms)
            if self._verbose:
                LOG.info("L2 snippet fuzzy score=%s (%s ms)", hit.score, round(ms, 2))
            return ExpansionOutcome(hit.value, ExpansionLayer.L2_SNIPPET_FUZZY.value, ms), corrected

        return None, corrected

    def _try_context_free_cache(
        self,
        corrected: str,
        t0: float,
        stage_ms: dict[str, float],
    ) -> Optional[ExpansionOutcome]:
        user_prompt, system = prompts.classify(corrected)
        ck = _cache_prompt(self.llm.cache_model_id, user_prompt, system)
        t = time.perf_counter()
        cached, hit_count, src = self.cache.lookup(self.llm.cache_model_id, ck)
        stage_ms["cache"] = (time.perf_counter() - t) * 1000.0
        if cached:
            self._notify_cache_touch(ck, cached, hit_count, src)
            ms = (time.perf_counter() - t0) * 1000.0
            if self._perf:
                self._log_perf(stage_ms)
            if self._verbose:
                LOG.info("L2 cache hit (%s ms)", round(ms, 2))
            return ExpansionOutcome(cached, "L2-cache", ms)
        if self._perf:
            self._log_perf(stage_ms)
        return None

    async def _expand_l0(self, capture: str, http: httpx.AsyncClient, t0: float) -> Optional[ExpansionOutcome]:
        t_l0 = time.perf_counter()
        l0 = await try_l0_async(capture, http, self.fx_cache)
        if not l0:
            return None
        text, layer = l0
        ms = (time.perf_counter() - t0) * 1000.0
        if self._perf:
            LOG.info("L0 compute (ms): %s", round((time.perf_counter() - t_l0) * 1000.0, 3))
        if self._verbose:
            LOG.info("%s (%s ms)", layer, round(ms, 2))
        return ExpansionOutcome(text, layer, ms)

    async def _expand_semantic_match(
        self,
        corrected: str,
        t0: float,
        *,
        focused_app: str,
        clipboard_snippet: str,
        stage_ms: dict[str, float],
    ) -> Optional[ExpansionOutcome]:
        if self.semantic_index is None:
            return None
        await asyncio.to_thread(self.semantic_index.prepare_sync)
        t_sem = time.perf_counter()
        hit = await asyncio.to_thread(self.semantic_index.find_best, corrected, focused_app)
        stage_ms["snippet_semantic"] = (time.perf_counter() - t_sem) * 1000.0
        if not hit:
            return None
        ms = (time.perf_counter() - t0) * 1000.0
        if self._perf:
            self._log_perf(stage_ms)
        if self._verbose:
            LOG.info("L2 snippet semantic score=%s (%s ms)", hit.score, round(ms, 2))
        sem = ExpansionOutcome(hit.value, ExpansionLayer.L2_SNIPPET_SEMANTIC.value, ms)
        return await self._finalize_snippet_value_async(
            sem, focused_app=focused_app, clipboard_hint=clipboard_snippet
        )

    async def _expand_contextual_cache_hit(
        self,
        *,
        corrected: str,
        t0: float,
        focused_app: str,
        prior_words: str,
        clipboard_snippet: str,
    ) -> Optional[ExpansionOutcome]:
        user_prompt, base_system = prompts.classify(corrected)
        system_full = prompts.attach_context(
            base_system,
            focused_app=focused_app,
            prior_words=prior_words,
            clipboard_snippet=clipboard_snippet,
        )
        ck = _cache_prompt(self.llm.cache_model_id, user_prompt, system_full)
        cached, hit_count, src = self.cache.lookup(self.llm.cache_model_id, ck)
        if not cached:
            return None
        self._notify_cache_touch(ck, cached, hit_count, src)
        ms = (time.perf_counter() - t0) * 1000.0
        if self._verbose:
            LOG.info("L2 cache hit (contextual) (%s ms)", round(ms, 2))
        return ExpansionOutcome(cached, ExpansionLayer.L2_CACHE.value, ms)

    async def _expand_l3_generate(
        self,
        *,
        corrected: str,
        http: httpx.AsyncClient,
        t0: float,
        focused_app: str,
        prior_words: str,
        clipboard_snippet: str,
    ) -> ExpansionOutcome:
        user_prompt, base_system = prompts.classify(corrected)
        system_full = prompts.attach_context(
            base_system,
            focused_app=focused_app,
            prior_words=prior_words,
            clipboard_snippet=clipboard_snippet,
        )
        ck = _cache_prompt(self.llm.cache_model_id, user_prompt, system_full)
        mid = self.llm.cache_model_id
        LOG.info("L3 %s generate model=%s", self.llm.name, mid)
        t_ai = time.perf_counter()
        text = await self.llm.generate(http, user_prompt, system_full)
        if self._perf:
            LOG.info("L3 generate (ms): %s", round((time.perf_counter() - t_ai) * 1000.0, 3))
        layer = l3_layer(self.llm.name)
        if text:
            self.cache.put(self.llm.cache_model_id, ck, text, source="ai")
        ms = (time.perf_counter() - t0) * 1000.0
        if self._verbose:
            LOG.info("L3 done (%s ms)", round(ms, 2))
        return ExpansionOutcome(text, layer, ms)

    def try_deterministic_capture(
        self,
        capture: str,
        t0: float,
        *,
        focused_app: str = "",
        namespace_lenient: bool = False,
    ) -> tuple[Optional[ExpansionOutcome], dict[str, float]]:
        """
        Stages: autocorrect → exact → fuzzy → (semantic in :meth:`expand` via thread pool) → cache.
        Use this from sync tests; full resolution including semantic happens in :meth:`expand`.
        """
        stage_ms: dict[str, float] = {}
        det, corrected = self._try_exact_and_fuzzy_snippets(
            capture, t0, focused_app=focused_app, namespace_lenient=namespace_lenient, stage_ms=stage_ms
        )
        if det is not None:
            return self._finalize_snippet_value_sync(det, focused_app=focused_app), stage_ms
        if self.semantic_index is not None:
            t = time.perf_counter()
            hit = self.semantic_index.find_best(corrected, focused_app)
            stage_ms["snippet_semantic"] = (time.perf_counter() - t) * 1000.0
            if hit:
                ms = (time.perf_counter() - t0) * 1000.0
                if self._perf:
                    self._log_perf(stage_ms)
                if self._verbose:
                    LOG.info("L2 snippet semantic score=%s (%s ms)", hit.score, round(ms, 2))
                sem = ExpansionOutcome(hit.value, ExpansionLayer.L2_SNIPPET_SEMANTIC.value, ms)
                return self._finalize_snippet_value_sync(sem, focused_app=focused_app), stage_ms
        c = self._try_context_free_cache(corrected, t0, stage_ms)
        return c, stage_ms

    async def expand(
        self,
        capture: str,
        http: httpx.AsyncClient,
        *,
        focused_app: str = "",
        prior_words: str = "",
        clipboard_snippet: str = "",
    ) -> ExpansionOutcome:
        t0 = time.perf_counter()
        if not capture.strip():
            return ExpansionOutcome("", ExpansionLayer.EMPTY.value, (time.perf_counter() - t0) * 1000)

        l0 = await self._expand_l0(capture, http, t0)
        if l0 is not None:
            return l0

        stage_ms: dict[str, float] = {}
        det, corrected = self._try_exact_and_fuzzy_snippets(
            capture,
            t0,
            focused_app=focused_app,
            namespace_lenient=self._snippet_namespace_lenient,
            stage_ms=stage_ms,
        )
        if det is not None:
            return await self._finalize_snippet_value_async(
                det, focused_app=focused_app, clipboard_hint=clipboard_snippet
            )

        sem_out = await self._expand_semantic_match(
            corrected,
            t0,
            focused_app=focused_app,
            clipboard_snippet=clipboard_snippet,
            stage_ms=stage_ms,
        )
        if sem_out is not None:
            return sem_out

        cache_hit = self._try_context_free_cache(corrected, t0, stage_ms)
        if cache_hit is not None:
            return cache_hit

        ctx_hit = await self._expand_contextual_cache_hit(
            corrected=corrected,
            t0=t0,
            focused_app=focused_app,
            prior_words=prior_words,
            clipboard_snippet=clipboard_snippet,
        )
        if ctx_hit is not None:
            return ctx_hit

        return await self._expand_l3_generate(
            corrected=corrected,
            http=http,
            t0=t0,
            focused_app=focused_app,
            prior_words=prior_words,
            clipboard_snippet=clipboard_snippet,
        )
