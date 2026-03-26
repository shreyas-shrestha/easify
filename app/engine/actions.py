"""Pipeline results and inject-level actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.policy.policy_model import BehaviorPolicy


class ActionType(Enum):
    REPLACE_WORD = "replace_word"
    REPLACE_PHRASE = "replace_phrase"
    INSERT_TEXT = "insert_text"
    SHOW_PREVIEW = "show_preview"
    NOOP = "noop"


@dataclass(frozen=True)
class EngineAction:
    type: ActionType
    text: Optional[str]
    confidence: float
    source: str


@dataclass(frozen=True)
class LiveResult:
    replacement: Optional[str]
    confidence: float
    source: str
    fuzzy_ratio: float = 1.0


@dataclass(frozen=True)
class CaptureResult:
    text: str
    source: str
    stages_run: list[str]
    latency_ms: dict[str, float]
    cached: bool
    citation_mode: bool


def confidence_for_live_source(source: str, *, fuzzy_ratio: float = 1.0) -> float:
    if source in ("autocorrect", "snippet_exact"):
        return 1.0
    if source == "snippet_fuzzy":
        return float(fuzzy_ratio)
    if source == "cache":
        return 0.9
    if source == "ai":
        return 0.7
    return 0.0


def live_detail_to_result(
    *,
    text: Optional[str],
    source: str,
    fuzzy_ratio: float = 1.0,
) -> LiveResult:
    conf = confidence_for_live_source(source, fuzzy_ratio=fuzzy_ratio)
    return LiveResult(replacement=text, confidence=conf, source=source, fuzzy_ratio=fuzzy_ratio)


def live_result_to_action(result: LiveResult, policy: BehaviorPolicy, *, is_phrase: bool) -> EngineAction:
    if not result.replacement:
        return EngineAction(ActionType.NOOP, None, result.confidence, result.source)
    if result.confidence < policy.thresholds.min_live_confidence:
        return EngineAction(ActionType.NOOP, None, result.confidence, "below_threshold")
    if len(result.replacement) > policy.thresholds.max_replace_len:
        return EngineAction(ActionType.NOOP, None, result.confidence, "too_long")
    if is_phrase:
        return EngineAction(ActionType.REPLACE_PHRASE, result.replacement, result.confidence, result.source)
    return EngineAction(ActionType.REPLACE_WORD, result.replacement, result.confidence, result.source)
