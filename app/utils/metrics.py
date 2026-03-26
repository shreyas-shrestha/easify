"""Append-only counter persistence — opt-in via EASIFY_METRICS=1."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict


class Metrics:
    """Thread-safe counters written to JSON (same directory as cache.db)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {}
        self._load()

    def incr(self, name: str, n: int = 1) -> None:
        if n <= 0:
            return
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + n
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
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
