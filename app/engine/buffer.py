"""Trigger detection + optional live word buffer (autocorrect hooks)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TriggerState:
    matched: int = 0

    @property
    def in_progress(self) -> bool:
        """True while a partial trigger prefix (e.g. `//`) is being typed."""
        return self.matched > 0

    def try_advance(self, ch: Optional[str], trigger: str) -> bool:
        """Returns True when trigger sequence completes."""
        if ch is None or not trigger:
            return False
        next_i = self.matched
        if next_i < len(trigger) and ch == trigger[next_i]:
            self.matched += 1
            if self.matched >= len(trigger):
                self.matched = 0
                return True
            return False
        if ch == trigger[0]:
            self.matched = 1
            if self.matched >= len(trigger):
                self.matched = 0
                return True
            return False
        self.matched = 0
        return False

    def reset(self) -> None:
        self.matched = 0


@dataclass
class CaptureBuffer:
    chars: list[str] = field(default_factory=list)

    def push(self, ch: str) -> None:
        self.chars.append(ch)

    def backspace(self) -> None:
        if self.chars:
            self.chars.pop()

    def text(self) -> str:
        return "".join(self.chars)

    def clear(self) -> None:
        self.chars.clear()


@dataclass
class LiveWordBuffer:
    """Builds current word for optional live autocorrect on boundary keys."""

    word: str = ""

    def on_char(self, ch: str) -> None:
        if ch.isalnum() or ch in "-_'":
            self.word += ch
        else:
            self.word = ""

    def take_word(self) -> str:
        w, self.word = self.word, ""
        return w
