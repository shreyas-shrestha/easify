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
