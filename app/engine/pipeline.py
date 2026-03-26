"""Layered resolution: L1 snippets/autocorrect → L2 fuzzy/cache → L3 Ollama."""

from __future__ import annotations

import time
from dataclasses import dataclass

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
    ) -> None:
        self.snippets = snippets
        self.autocorrect = autocorrect
        self.cache = cache
        self.ollama = ollama
        self._verbose = verbose

    async def expand(self, capture: str, http: httpx.AsyncClient) -> ExpansionOutcome:
        t0 = time.perf_counter()

        if not capture.strip():
            return ExpansionOutcome("", "empty", (time.perf_counter() - t0) * 1000)

        corrected = self.autocorrect.apply_to_phrase(capture)
        if corrected != capture and self._verbose:
            LOG.info("L1 autocorrect adjusted phrase")

        hit = self.snippets.resolve_exact(corrected)
        if hit:
            ms = (time.perf_counter() - t0) * 1000
            if self._verbose:
                LOG.info("L1 snippet exact (%s ms)", round(ms, 2))
            return ExpansionOutcome(hit.value, "L1-snippet-exact", ms)

        hit = self.snippets.resolve_fuzzy(corrected)
        if hit:
            ms = (time.perf_counter() - t0) * 1000
            if self._verbose:
                LOG.info("L2 snippet fuzzy score=%s (%s ms)", hit.score, round(ms, 2))
            return ExpansionOutcome(hit.value, "L2-snippet-fuzzy", ms)

        user_prompt, system = prompts.classify(corrected)
        ck = _cache_prompt(self.ollama.model, user_prompt, system)
        cached = self.cache.get(self.ollama.model, ck)
        if cached:
            ms = (time.perf_counter() - t0) * 1000
            if self._verbose:
                LOG.info("L2 cache hit (%s ms)", round(ms, 2))
            return ExpansionOutcome(cached, "L2-cache", ms)

        LOG.info("L3 calling Ollama model=%s", self.ollama.model)
        text = await self.ollama.generate(http, user_prompt, system)
        if text:
            self.cache.put(self.ollama.model, ck, text)
        ms = (time.perf_counter() - t0) * 1000
        if self._verbose:
            LOG.info("L3 ai done (%s ms)", round(ms, 2))
        return ExpansionOutcome(text, "L3-ai", ms)
