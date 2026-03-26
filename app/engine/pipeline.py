"""Layered resolution: L1 snippets/autocorrect → L2 fuzzy/cache → L3 Ollama."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.ai import prompts
from app.ai.ollama import OllamaClient
from app.autocorrect.engine import AutocorrectEngine
from app.cache.store import SqliteExpansionCache
from app.snippets.engine import SnippetEngine
from app.utils.log import get_logger

LOG = get_logger(__name__)


@dataclass
class ExpansionOutcome:
    text: str
    layer: str
    ms: float


def _cache_prompt(model: str, user_prompt: str, system: str) -> str:
    return f"{model}\n{system}\n{user_prompt}"


class ExpansionPipeline:
    def __init__(
        self,
        *,
        snippets: SnippetEngine,
        autocorrect: AutocorrectEngine,
        cache: SqliteExpansionCache,
        ollama: OllamaClient,
        verbose: bool = False,
        perf: bool = False,
    ) -> None:
        self.snippets = snippets
        self.autocorrect = autocorrect
        self.cache = cache
        self.ollama = ollama
        self._verbose = verbose
        self._perf = perf

    def _log_perf(self, stage_ms: dict[str, float]) -> None:
        LOG.info("capture deterministic perf (ms): %s", stage_ms)

    def try_deterministic_capture(self, capture: str, t0: float) -> tuple[Optional[ExpansionOutcome], dict[str, float]]:
        """
        Stages: autocorrect phrase → snippet exact → snippet fuzzy → cache.
        Returns (outcome or None, stage timings).
        """
        stage_ms: dict[str, float] = {}

        t = time.perf_counter()
        corrected = self.autocorrect.apply_to_phrase(capture)
        stage_ms["autocorrect_phrase"] = (time.perf_counter() - t) * 1000.0
        if corrected != capture and self._verbose:
            LOG.info("L1 autocorrect adjusted phrase")

        t = time.perf_counter()
        hit = self.snippets.resolve_exact(corrected)
        stage_ms["snippet_exact"] = (time.perf_counter() - t) * 1000.0
        if hit:
            ms = (time.perf_counter() - t0) * 1000.0
            if self._perf:
                self._log_perf(stage_ms)
            if self._verbose:
                LOG.info("L1 snippet exact (%s ms)", round(ms, 2))
            return ExpansionOutcome(hit.value, "L1-snippet-exact", ms), stage_ms

        t = time.perf_counter()
        hit = self.snippets.resolve_fuzzy(corrected)
        stage_ms["snippet_fuzzy"] = (time.perf_counter() - t) * 1000.0
        if hit:
            ms = (time.perf_counter() - t0) * 1000.0
            if self._perf:
                self._log_perf(stage_ms)
            if self._verbose:
                LOG.info("L2 snippet fuzzy score=%s (%s ms)", hit.score, round(ms, 2))
            return ExpansionOutcome(hit.value, "L2-snippet-fuzzy", ms), stage_ms

        user_prompt, system = prompts.classify(corrected)
        ck = _cache_prompt(self.ollama.model, user_prompt, system)

        t = time.perf_counter()
        cached = self.cache.get(self.ollama.model, ck)
        stage_ms["cache"] = (time.perf_counter() - t) * 1000.0
        if cached:
            ms = (time.perf_counter() - t0) * 1000.0
            if self._perf:
                self._log_perf(stage_ms)
            if self._verbose:
                LOG.info("L2 cache hit (%s ms)", round(ms, 2))
            return ExpansionOutcome(cached, "L2-cache", ms), stage_ms

        if self._perf:
            self._log_perf(stage_ms)
        return None, stage_ms

    async def expand(self, capture: str, http: httpx.AsyncClient) -> ExpansionOutcome:
        t0 = time.perf_counter()

        if not capture.strip():
            return ExpansionOutcome("", "empty", (time.perf_counter() - t0) * 1000)

        det, _ = self.try_deterministic_capture(capture, t0)
        if det is not None:
            return det

        corrected = self.autocorrect.apply_to_phrase(capture)
        user_prompt, system = prompts.classify(corrected)
        ck = _cache_prompt(self.ollama.model, user_prompt, system)

        LOG.info("L3 calling Ollama model=%s", self.ollama.model)
        t_ai = time.perf_counter()
        text = await self.ollama.generate(http, user_prompt, system)
        if self._perf:
            LOG.info("L3 ollama generate (ms): %s", round((time.perf_counter() - t_ai) * 1000.0, 3))
        if text:
            self.cache.put(self.ollama.model, ck, text, source="ai")
        ms = (time.perf_counter() - t0) * 1000.0
        if self._verbose:
            LOG.info("L3 ai done (%s ms)", round(ms, 2))
        return ExpansionOutcome(text, "L3-ai", ms)
