"""
Capture expansion stages (contract).

Order (implementation: :class:`app.engine.pipeline.ExpansionPipeline.expand`):

1. L0 compute
2. Autocorrect (phrase)
3. Snippet exact
4. Snippet fuzzy
5. Semantic snippets
6. Cache lookup
7. AI generate
8. Store cache

Async execution and queuing are owned by :class:`app.engine.router.EngineRouter` / :class:`app.engine.service.ExpansionService`.
"""

from __future__ import annotations

import httpx

from app.engine.actions import CaptureResult
from app.engine.expansion_contracts import ExpansionLayer, ExpansionOutcome
from app.engine.pipeline import ExpansionPipeline

CAPTURE_PIPELINE_STAGE_ORDER: tuple[str, ...] = (
    "l0_compute",
    "autocorrect",
    "snippet_exact",
    "snippet_fuzzy",
    "semantic",
    "cache",
    "ai_generate",
    "store_cache",
)


def _capture_cached_from_layer(layer: str) -> bool:
    return layer == ExpansionLayer.L2_CACHE.value or layer == "L2-cache"


def _stages_run_for_layer(layer: str, *, text_non_empty: bool) -> list[str]:
    if not layer or layer == ExpansionLayer.EMPTY.value:
        return []
    if layer.startswith("L0-"):
        return ["l0_compute"]
    if layer == ExpansionLayer.L1_SNIPPET_EXACT.value:
        return ["autocorrect", "snippet_exact"]
    if layer == ExpansionLayer.L2_SNIPPET_FUZZY.value:
        return ["autocorrect", "snippet_exact", "snippet_fuzzy"]
    if layer == ExpansionLayer.L2_SNIPPET_SEMANTIC.value:
        return ["autocorrect", "snippet_exact", "snippet_fuzzy", "semantic"]
    if _capture_cached_from_layer(layer):
        return ["autocorrect", "snippet_exact", "snippet_fuzzy", "semantic", "cache"]
    if layer.startswith("L3-"):
        out = list(CAPTURE_PIPELINE_STAGE_ORDER[:7])
        if text_non_empty:
            out.append("store_cache")
        return out
    return ["autocorrect", "snippet_exact", "snippet_fuzzy", "semantic", "cache", "ai_generate"]


def capture_result_from_outcome(outcome: ExpansionOutcome, *, citation_mode: bool) -> CaptureResult:
    """Map :class:`ExpansionOutcome` to :class:`CaptureResult` (sync helper for tests)."""
    text = outcome.text or ""
    layer = outcome.layer
    return CaptureResult(
        text=text,
        source=layer,
        stages_run=_stages_run_for_layer(layer, text_non_empty=bool(text.strip())),
        latency_ms={"total": round(float(outcome.ms), 4)},
        cached=_capture_cached_from_layer(layer),
        citation_mode=citation_mode,
    )


async def run_capture_expand_async(
    pipeline: ExpansionPipeline,
    capture: str,
    http: httpx.AsyncClient,
    *,
    focused_app: str = "",
    prior_words: str = "",
    clipboard_snippet: str = "",
    citation_mode: bool = False,
) -> CaptureResult:
    """Run full capture :meth:`ExpansionPipeline.expand` and return a :class:`CaptureResult`."""
    outcome = await pipeline.expand(
        capture,
        http,
        focused_app=focused_app,
        prior_words=prior_words,
        clipboard_snippet=clipboard_snippet,
    )
    return capture_result_from_outcome(outcome, citation_mode=citation_mode)
