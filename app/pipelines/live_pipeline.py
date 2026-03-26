"""Strict live path: policy + deps → LiveResult; legacy listener helpers (no AI)."""

from __future__ import annotations

from collections import deque
from typing import Any, Optional

from app.config.settings import Settings
from app.context.detector import detect_input_context
from app.engine.actions import ActionType, LiveResult, live_result_to_action
from app.engine.events import EngineEvent, EngineEventType, LiveWordPayload
from app.engine.guards import is_safe_phrase_tokens, is_safe_word
from app.policy.engine import resolve_policy
from app.policy.policy_model import BehaviorPolicy
from app.pipelines.deps import DefaultLivePipelineDeps, LivePipelineDeps


def run_live_word(word: str, policy: BehaviorPolicy, deps: LivePipelineDeps) -> LiveResult:
    if not (
        policy.live.autocorrect
        or policy.live.snippets
        or policy.live.fuzzy
        or policy.live.cache
    ):
        return LiveResult(None, 0.0, "disabled", 1.0)
    return deps.expand_live_word(word)


def run_live_phrase(phrase: str, policy: BehaviorPolicy, deps: LivePipelineDeps) -> LiveResult:
    if not (
        policy.live.autocorrect
        or policy.live.snippets
        or policy.live.fuzzy
        or policy.live.cache
    ):
        return LiveResult(None, 0.0, "disabled", 1.0)
    return deps.expand_live_phrase(phrase)


def resolve_live_policy_for_listener(settings: Settings, *, focused_app_raw: str) -> BehaviorPolicy:
    """Policy for a live word boundary using current focus (e.g. terminal caps) — sync, cheap."""
    ev = EngineEvent(EngineEventType.LIVE_WORD, LiveWordPayload(word=""))
    ctx = detect_input_context(ev, focused_app_raw=focused_app_raw)
    return resolve_policy(ctx, settings)


def build_live_pipeline_deps(
    service: Any,
    settings: Settings,
    policy: BehaviorPolicy,
) -> DefaultLivePipelineDeps:
    """Shared wiring for v2 router and legacy listener (CacheService only, no SQLite)."""
    return DefaultLivePipelineDeps(
        autoc=service.autocorrect,
        snippets=service.snippets,
        cache=service.cache_service,
        model=service.cache_model_id,
        min_word_len=settings.live_min_word_len,
        fuzzy_enabled=policy.live.fuzzy,
        cache_enabled=policy.live.cache,
        fuzzy_threshold=settings.live_fuzzy_threshold,
        perf=settings.perf,
    )


def legacy_live_replacement_word(
    word: str,
    *,
    service: Any,
    settings: Settings,
    focused_app_raw: str,
) -> Optional[str]:
    """Non-v2 live: same stack as router (confidence + length gates). Returns text to paste or None."""
    policy = resolve_live_policy_for_listener(settings, focused_app_raw=focused_app_raw)
    deps = build_live_pipeline_deps(service, settings, policy)
    res = run_live_word(word, policy, deps)
    act = live_result_to_action(res, policy, is_phrase=False)
    if act.type is ActionType.REPLACE_WORD and act.text:
        return act.text
    return None


def legacy_live_replacement_phrase(
    phrase: str,
    *,
    service: Any,
    settings: Settings,
    focused_app_raw: str,
) -> Optional[str]:
    policy = resolve_live_policy_for_listener(settings, focused_app_raw=focused_app_raw)
    deps = build_live_pipeline_deps(service, settings, policy)
    res = run_live_phrase(phrase, policy, deps)
    act = live_result_to_action(res, policy, is_phrase=True)
    if act.type is ActionType.REPLACE_PHRASE and act.text:
        return act.text
    return None


def maybe_schedule_live_enrich_after_miss(
    word: str,
    phrase_deque: Optional[deque[str]],
    *,
    service: Any,
    settings: Settings,
    min_word_len: int,
) -> None:
    if not settings.live_cache_enrich or not settings.live_cache:
        return
    if phrase_deque is not None and len(phrase_deque) >= 2:
        phrase = " ".join(phrase_deque)
        toks = phrase.split()
        if is_safe_phrase_tokens(toks, min_len=min_word_len):
            service.schedule_live_cache_enrich_phrase(phrase)
    elif is_safe_word(word, min_len=min_word_len):
        service.schedule_live_cache_enrich_word(word)
