"""Tray / status bar state isolated from worker and inject logic."""

from __future__ import annotations

import threading
import time

from app.config.settings import Settings
from app.engine.types import TraySnapshot


class TrayController:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._status = "idle"
        self._detail = ""
        self._last_success_detail = ""
        self._last_error = ""
        self._degraded_hint = ""
        self._thinking_started_mono: float = 0.0
        self._thinking_capture: str = ""

    def set_thinking(self, preview: str = "") -> None:
        with self._lock:
            self._status = "thinking"
            self._detail = preview[:220]
            self._thinking_capture = preview[:220]
            self._thinking_started_mono = time.monotonic()
            self._last_error = ""
            self._degraded_hint = ""

    def set_idle(self, last_expansion: str = "") -> None:
        with self._lock:
            self._status = "idle"
            self._detail = last_expansion[:220]
            self._last_success_detail = self._detail
            self._last_error = ""
            self._degraded_hint = ""
            self._thinking_started_mono = 0.0
            self._thinking_capture = ""

    def set_error(self, message: str, *, degraded_hint: str = "") -> None:
        with self._lock:
            self._status = "error"
            self._last_error = (message or "")[:8000]
            self._detail = (message or "")[:500]
            self._degraded_hint = (degraded_hint or "")[:500]
            self._thinking_started_mono = 0.0
            self._thinking_capture = ""

    def clear_error(self) -> None:
        with self._lock:
            if self._status != "error":
                return
            self._status = "idle"
            self._last_error = ""
            self._degraded_hint = ""
            self._detail = self._last_success_detail

    def snapshot(
        self,
        *,
        expansion_queued: int,
        enrich_queued: int,
        undo_depth: int,
        cache_model_id: str,
    ) -> TraySnapshot:
        now = time.monotonic()
        with self._lock:
            st = self._status
            det = self._detail
            err = self._last_error
            deg = self._degraded_hint
            t0 = self._thinking_started_mono
            cap_prev = self._thinking_capture
        elapsed = (now - t0) if (st == "thinking" and t0 > 0) else 0.0
        return TraySnapshot(
            status=st,
            detail=det,
            error=err,
            model=cache_model_id,
            expansion_queued=expansion_queued,
            enrich_queued=enrich_queued,
            undo_depth=undo_depth,
            thinking_elapsed_s=elapsed,
            thinking_capture=cap_prev,
            l3_timeout_s=float(self._settings.ollama_timeout_s),
            degraded_hint=deg,
        )
