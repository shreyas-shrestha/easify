"""Stable input classification for policy (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AppKind(Enum):
    UNKNOWN = "unknown"
    BROWSER = "browser"
    IDE = "ide"
    TERMINAL = "terminal"
    CHAT = "chat"
    NOTES = "notes"
    EMAIL = "email"
    OTHER = "other"


class ActivationKind(Enum):
    LIVE_SPACE = "live_space"
    CAPTURE = "capture"
    PALETTE = "palette"
    DOUBLE_SPACE = "double_space"


class TextKind(Enum):
    WORD = "word"
    PHRASE = "phrase"
    SENTENCE = "sentence"


class IntentKind(Enum):
    CHAT = "chat"
    NOTE = "note"
    QUESTION = "question"
    COMMAND = "command"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InputContext:
    app: AppKind
    activation: ActivationKind
    text_kind: TextKind
    intent: IntentKind
