"""Buffered keystrokes typed after an expansion is queued (parallel tail)."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Callable

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.engine.types import ExpansionJob

LOG = get_logger(__name__)

# Hook for tests / instrumentation (default: stdlib condition wait).
_condition_wait_impl: Callable[[threading.Condition, float], bool] = lambda c, t: c.wait(timeout=t)


class PendingExpansionTail:
    """Keys typed after capture submit, merged when the expansion is injected.

    ``tail``, ``lock``, and ``last_activity_mono`` mirror the legacy surface tests use.
    All mutations and waits use the same ``Condition`` so idle detection is consistent.
    """

    __slots__ = ("job", "tail", "lock", "_cond", "_last_activity_mono")

    def __init__(self, job: ExpansionJob, *, settle_s: float = 0.0) -> None:
        self.job = job
        self.tail: list[str] = []
        # RLock: property setters and Condition share this lock; callers may already hold it (tests).
        self.lock = threading.RLock()
        self._cond = threading.Condition(self.lock)
        self._last_activity_mono = 0.0
        _ = settle_s  # reserved for future per-tail policy; service controls settle timing

    @property
    def last_activity_mono(self) -> float:
        with self._cond:
            return self._last_activity_mono

    @last_activity_mono.setter
    def last_activity_mono(self, v: float) -> None:
        with self._cond:
            self._last_activity_mono = v
            self._cond.notify_all()

    def append_char(self, ch: str) -> None:
        with self._cond:
            if ch == "\b":
                if self.tail:
                    self.tail.pop()
            else:
                self.tail.append(ch)
            self._last_activity_mono = time.monotonic()
            self._cond.notify_all()

    def wait_idle_until(self, *, settle_s: float, deadline_mono: float) -> None:
        """Block until tail is empty, idle for ``settle_s`` since last activity, or ``deadline_mono``."""
        with self._cond:
            while True:
                now = time.monotonic()
                if not self.tail:
                    return
                if settle_s <= 0 or (now - self._last_activity_mono) >= settle_s:
                    return
                if now >= deadline_mono:
                    LOG.debug("inject tail settle: max wait exceeded, injecting anyway")
                    return
                remaining = deadline_mono - now
                idle_at = self._last_activity_mono + settle_s
                wait_for = min(remaining, idle_at - now)
                wait_for = max(0.002, wait_for)
                _condition_wait_impl(self._cond, wait_for)

    def drain_joined(self) -> str:
        with self._cond:
            return "".join(self.tail)
