"""Resolve BehaviorPolicy once per event."""

from __future__ import annotations

from app.config.settings import Settings
from app.context.input_context import AppKind, InputContext, IntentKind
from app.policy.policy_model import (
    BehaviorPolicy,
    CapturePolicyCaps,
    LivePolicyCaps,
    StylePolicy,
    ThresholdPolicy,
)


def resolve_policy(ctx: InputContext, settings: Settings) -> BehaviorPolicy:
    any_live = (
        settings.live_autocorrect
        or settings.live_fuzzy
        or settings.live_cache
        or settings.live_cache_enrich
        or settings.phrase_buffer_max > 0
    )
    if not any_live:
        live = LivePolicyCaps(False, False, False, False, False)
    else:
        live = LivePolicyCaps(
            autocorrect=settings.live_autocorrect,
            snippets=True,
            fuzzy=settings.live_fuzzy,
            cache=settings.live_cache,
            cache_enrich=settings.live_cache_enrich and settings.live_cache,
        )
    if ctx.app is AppKind.TERMINAL:
        live = LivePolicyCaps(False, False, False, False, False)

    capture = CapturePolicyCaps(
        snippets=True,
        semantic=settings.semantic_snippets,
        cache=True,
        ai=True,
        citations=ctx.intent is IntentKind.NOTE,
    )

    style = StylePolicy(tone="neutral", format="plain")

    thresholds = ThresholdPolicy(
        min_live_confidence=0.72,
        fuzzy_ratio_floor=settings.live_fuzzy_threshold,
        max_replace_len=2000,
    )

    return BehaviorPolicy(live=live, capture=capture, style=style, thresholds=thresholds)
