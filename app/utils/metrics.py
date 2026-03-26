"""Append-only counter persistence — opt-in via EASIFY_METRICS=1."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict

_FLUSH_INTERVAL_SEC = 5.0


class Metrics:
    """Thread-safe counters; flushed to JSON at most every 5 s (or on close())."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {}
        self._dirty = False
        self._last_flush: float = 0.0
        self._load()

    def incr(self, name: str, n: int = 1) -> None:
        if n <= 0:
            return
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + n
            self._dirty = True
            if time.monotonic() - self._last_flush >= _FLUSH_INTERVAL_SEC:
                self._flush_unlocked()

    def flush(self) -> None:
        """Explicit flush — call on shutdown."""
        with self._lock:
            if self._dirty:
                self._flush_unlocked()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self._counts = {}
            return
        if not isinstance(raw, dict):
            return
        c = raw.get("counters")
        if not isinstance(c, dict):
            return
        out: Dict[str, int] = {}
        for k, v in c.items():
            if isinstance(k, str):
                try:
                    out[k] = int(v)
                except (TypeError, ValueError):
                    pass
        self._counts = out

    def _flush_unlocked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"counters": self._counts}
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._path)
        self._last_flush = time.monotonic()
        self._dirty = False
