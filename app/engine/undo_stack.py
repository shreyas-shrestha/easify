"""Bounded LIFO undo stack for expansion injections."""

from __future__ import annotations

import threading
from collections import deque
from typing import Optional

from app.engine.types import UndoFrame


class UndoStack:
    def __init__(self, max_depth: int) -> None:
        self._cap = max(1, max_depth)
        self._items: deque[UndoFrame] = deque()
        self._lock = threading.Lock()

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    @property
    def items(self) -> deque[UndoFrame]:
        return self._items

    def depth(self) -> int:
        with self._lock:
            return len(self._items)

    def push(self, frame: UndoFrame) -> None:
        if not frame.injected:
            return
        with self._lock:
            self._items.append(frame)
            while len(self._items) > self._cap:
                self._items.popleft()

    def pop(self) -> Optional[UndoFrame]:
        with self._lock:
            if not self._items:
                return None
            return self._items.pop()
