"""Formal engine ingress events (buffer → engine)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Union


class EngineEventType(Enum):
    LIVE_WORD = "live_word"
    LIVE_PHRASE = "live_phrase"
    CAPTURE_SUBMIT = "capture_submit"
    CAPTURE_CANCEL = "capture_cancel"
    PALETTE_OPEN = "palette_open"
    DOUBLE_SPACE = "double_space"
    BACKGROUND_ENRICH = "background_enrich"


@dataclass(frozen=True)
class LiveWordPayload:
    word: str


@dataclass(frozen=True)
class LivePhrasePayload:
    phrase: str


@dataclass(frozen=True)
class CaptureSubmitPayload:
    capture_text: str
    delete_count: int
    undo_restore: str
    prior_words: str
    focused_app_at_submit: str


@dataclass(frozen=True)
class LiveEnrichPayload:
    word: str | None = None
    phrase: str | None = None


EnginePayload = Union[
    LiveWordPayload,
    LivePhrasePayload,
    CaptureSubmitPayload,
    LiveEnrichPayload,
    None,
]


@dataclass(frozen=True)
class EngineEvent:
    type: EngineEventType
    payload: Any = None
