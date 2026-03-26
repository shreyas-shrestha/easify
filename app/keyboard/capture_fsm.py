"""Capture-mode FSM: prefix //, double-space, Esc/Enter/close delimiter (buffer-owned state)."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from pynput.keyboard import Key

from app.engine.buffer import CaptureBuffer, TriggerState
from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.config.settings import Settings

LOG = get_logger(__name__)

_STATE_IDLE, _STATE_CAPTURING = "idle", "capturing"


class CapturingKeyKind(Enum):
    CANCEL = auto()
    CONSUMED = auto()
    SUBMIT = auto()


class PrefixTriggerResult(Enum):
    NO_MATCH = auto()
    ENTERED_CAPTURE = auto()
    SUPPRESSED_URL = auto()


@dataclass
class CapturingKeyResult:
    kind: CapturingKeyKind
    raw_buf: str = ""
    from_prefix: bool = False
    entered_with_newline: bool = False


class CaptureInputSession:
    """Owns capture buffer + trigger + idle/capturing state + double-space arming."""

    def __init__(
        self,
        settings: "Settings",
        capture: CaptureBuffer,
        trigger_state: TriggerState,
        recent_chars: deque[str],
    ) -> None:
        self._settings = settings
        self._capture = capture
        self._trigger = trigger_state
        self._recent = recent_chars
        self._state = _STATE_IDLE
        self._capture_from_prefix = False
        self._dbl_armed = False
        self._dbl_last_mono = 0.0

    @property
    def capture_from_prefix(self) -> bool:
        return self._capture_from_prefix

    def is_capturing(self) -> bool:
        return self._state == _STATE_CAPTURING

    def record_idle_char(self, ch: Optional[str]) -> None:
        if self._state == _STATE_IDLE and ch is not None and len(ch) == 1:
            self._recent.append(ch)

    def suppress_capture_for_url_scheme(self, trigger: str) -> bool:
        if trigger != "//":
            return False
        s = "".join(self._recent)
        if len(s) < 2 or not s.endswith("//"):
            return False
        pre = s[:-2]
        return pre.endswith(("http:", "https:", "file:", "ftp:"))

    def trigger_in_progress(self) -> bool:
        return self._trigger.in_progress

    def enter_from_prefix(self) -> None:
        self._state = _STATE_CAPTURING
        self._capture_from_prefix = True
        self._capture.clear()
        self._trigger.reset()

    def enter_from_double_space(self) -> None:
        self._state = _STATE_CAPTURING
        self._capture_from_prefix = False
        self._capture.clear()
        self._trigger.reset()
        self._dbl_armed = False

    def cancel(self) -> None:
        self._capture.clear()
        self._trigger.reset()
        self._capture_from_prefix = False
        self._state = _STATE_IDLE
        LOG.info("capture cancelled (Esc) — not submitted")

    def drain_for_submit(self) -> tuple[str, bool]:
        raw = self._capture.text()
        fp = self._capture_from_prefix
        self._state = _STATE_IDLE
        self._capture.clear()
        self._trigger.reset()
        self._capture_from_prefix = False
        return raw, fp

    def handle_capturing_key(self, key: object, ch: Optional[str], *, debug: bool) -> CapturingKeyResult:
        if key == Key.esc:
            self.cancel()
            return CapturingKeyResult(CapturingKeyKind.CANCEL)
        if key in (Key.enter, getattr(Key, "kp_enter", Key.enter)):
            raw, fp = self.drain_for_submit()
            return CapturingKeyResult(
                CapturingKeyKind.SUBMIT,
                raw_buf=raw,
                from_prefix=fp,
                entered_with_newline=True,
            )
        if ch == "\b":
            self._capture.backspace()
            return CapturingKeyResult(CapturingKeyKind.CONSUMED)
        if ch is not None and ch != "\n":
            self._capture.push(ch)
            close = self._settings.capture_close.strip()
            if close and self._capture.text().endswith(close):
                for _ in range(len(close)):
                    self._capture.backspace()
                raw, fp = self.drain_for_submit()
                return CapturingKeyResult(
                    CapturingKeyKind.SUBMIT,
                    raw_buf=raw,
                    from_prefix=fp,
                    entered_with_newline=False,
                )
            if debug and len(self._capture.chars) <= 80:
                LOG.debug("capture %r", self._capture.text())
            return CapturingKeyResult(CapturingKeyKind.CONSUMED)
        return CapturingKeyResult(CapturingKeyKind.CONSUMED)

    def try_prefix_trigger(self, ch: Optional[str], *, trigger: str, use_prefix: bool) -> PrefixTriggerResult:
        if not use_prefix or not trigger:
            return PrefixTriggerResult.NO_MATCH
        completed = self._trigger.try_advance(ch, trigger)
        if not completed:
            return PrefixTriggerResult.NO_MATCH
        if self.suppress_capture_for_url_scheme(trigger):
            return PrefixTriggerResult.SUPPRESSED_URL
        self.enter_from_prefix()
        return PrefixTriggerResult.ENTERED_CAPTURE

    def on_non_space_while_idle(self, ch: Optional[str]) -> None:
        if ch != " " and self._state == _STATE_IDLE:
            self._dbl_armed = False

    def try_double_space_open_capture(self, ch: Optional[str]) -> bool:
        """Second space within window: return True so listener deletes two spaces then ``enter_from_double_space``."""
        if self._state != _STATE_IDLE or ch != " " or not self._settings.double_space_activation:
            return False
        now = time.monotonic()
        win = self._settings.double_space_window_ms / 1000.0
        if self._dbl_armed and (now - self._dbl_last_mono) > win:
            self._dbl_armed = False
        if self._dbl_armed and (now - self._dbl_last_mono) <= win:
            return True
        self._dbl_armed = True
        self._dbl_last_mono = now
        return False
