"""Execution mode — only EngineRouter / EasifyEngine may branch on these."""

from __future__ import annotations

from enum import Enum


class ExecutionMode(Enum):
    LIVE_SYNC = "live_sync"
    CAPTURE_SYNC = "capture_sync"
    CAPTURE_ASYNC = "capture_async"
    BACKGROUND = "background"
