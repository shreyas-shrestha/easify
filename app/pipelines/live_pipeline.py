"""Strict live path: deterministic expansion only (wraps deps → LiveResult)."""

from __future__ import annotations

from app.engine.actions import LiveResult
from app.policy.policy_model import BehaviorPolicy
from app.pipelines.deps import LivePipelineDeps


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
