"""Routes EngineEvent → execution mode → pipeline/service (no text transforms)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from app.engine.actions import ActionType, EngineAction, LiveResult, live_result_to_action
from app.engine.events import (
    CaptureSubmitPayload,
    EngineEvent,
    EngineEventType,
    LivePhrasePayload,
    LiveWordPayload,
)
from app.engine.execution import ExecutionMode
from app.engine.types import ExpansionJob
from app.engine.guards import is_safe_phrase_tokens, is_safe_word
from app.policy.policy_model import BehaviorPolicy
from app.pipelines.deps import LivePipelineDeps
from app.pipelines.live_pipeline import run_live_phrase, run_live_word


class EngineRouter:
    def __init__(
        self,
        *,
        service: "ExpansionService",  # noqa: F821
        build_live_deps: Callable[[BehaviorPolicy], LivePipelineDeps],
        on_live_replace: Callable[[str, str], None],
        schedule_enrich_word: Callable[[str], None],
        schedule_enrich_phrase: Callable[[str], None],
        min_word_len_for_enrich: int,
    ) -> None:
        self._service = service
        self._build_live_deps = build_live_deps
        self._on_live_replace = on_live_replace
        self._schedule_enrich_word = schedule_enrich_word
        self._schedule_enrich_phrase = schedule_enrich_phrase
        self._min_word_len = min_word_len_for_enrich

    def execution_mode_for(self, event: EngineEvent) -> ExecutionMode:
        if event.type in (EngineEventType.LIVE_WORD, EngineEventType.LIVE_PHRASE):
            return ExecutionMode.LIVE_SYNC
        if event.type is EngineEventType.CAPTURE_SUBMIT:
            return ExecutionMode.CAPTURE_ASYNC
        if event.type is EngineEventType.BACKGROUND_ENRICH:
            return ExecutionMode.BACKGROUND
        return ExecutionMode.CAPTURE_SYNC

    def handle_live_sync(self, event: EngineEvent, policy: BehaviorPolicy) -> bool:
        deps = self._build_live_deps(policy)
        if event.type is EngineEventType.LIVE_WORD:
            payload = event.payload
            if not isinstance(payload, LiveWordPayload):
                return False
            res = run_live_word(payload.word, policy, deps)
            act = live_result_to_action(res, policy, is_phrase=False)
            return self._dispatch_live(res, act, old_span=payload.word, raw=payload.word, policy=policy)

        if event.type is EngineEventType.LIVE_PHRASE:
            payload = event.payload
            if not isinstance(payload, LivePhrasePayload):
                return False
            res = run_live_phrase(payload.phrase, policy, deps)
            act = live_result_to_action(res, policy, is_phrase=True)
            return self._dispatch_live(res, act, old_span=payload.phrase, raw=payload.phrase, policy=policy)
        return False

    def _dispatch_live(
        self,
        res: LiveResult,
        act: EngineAction,
        *,
        old_span: str,
        raw: str,
        policy: BehaviorPolicy,
    ) -> bool:
        if act.type in (ActionType.REPLACE_WORD, ActionType.REPLACE_PHRASE) and act.text:
            self._on_live_replace(old_span, act.text)
            return True
        if not policy.live.cache_enrich or not policy.live.cache:
            return False
        if res.replacement:
            return False
        if " " in raw.strip():
            toks = raw.split()
            if is_safe_phrase_tokens(toks, min_len=self._min_word_len):
                self._schedule_enrich_phrase(raw)
        elif is_safe_word(raw, min_len=self._min_word_len):
            self._schedule_enrich_word(raw)
        return False

    def handle_capture_async(self, event: EngineEvent) -> None:
        if event.type is not EngineEventType.CAPTURE_SUBMIT:
            return
        payload = event.payload
        if not isinstance(payload, CaptureSubmitPayload):
            return
        self._service.submit(
            ExpansionJob(
                capture=payload.capture_text,
                delete_count=payload.delete_count,
                prior_words=payload.prior_words,
                undo_restore=payload.undo_restore,
                focused_app_at_submit=payload.focused_app_at_submit,
            )
        )
