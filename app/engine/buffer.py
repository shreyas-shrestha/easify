"""Trigger detection + optional live word buffer (autocorrect hooks)."""

from __future__ import annotations

from dataclasses import dataclass, field
from app.utils.log import get_logger

LOG = get_logger(__name__)


@dataclass
class TriggerState:
    matched: int = 0

    @property
    def in_progress(self) -> bool:
        """True while a partial trigger prefix (e.g. `//`) is being typed."""
        return self.matched > 0

    def try_advance(self, ch: str | None, trigger: str) -> bool:
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


def strip_trailing_close(raw: str, close: str) -> str:
    """If ``raw`` ends with ``close``, return the prefix; otherwise ``raw``."""
    c = (close or "").strip()
    if c and raw.endswith(c):
        return raw[: -len(c)]
    return raw


@dataclass
class CaptureBuffer:
    max_chars: int = 4000
    chars: list[str] = field(default_factory=list)
    _warned_full: bool = field(default=False, repr=False)

    def push(self, ch: str) -> None:
        if len(self.chars) >= self.max_chars:
            if not self._warned_full:
                LOG.warning("capture buffer full (%s chars) — further keys ignored until Enter", self.max_chars)
                self._warned_full = True
            return
        self.chars.append(ch)

    def backspace(self) -> None:
        if self.chars:
            self.chars.pop()

    def text(self) -> str:
        return "".join(self.chars)

    def clear(self) -> None:
        self.chars.clear()
        self._warned_full = False


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
