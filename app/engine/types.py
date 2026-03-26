"""Pure data types for expansion jobs, tray state, enrich worker, and undo."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrayAppStatus(str, Enum):
    """Tray icon + snapshot lifecycle (avoid raw string typos)."""

    IDLE = "idle"
    THINKING = "thinking"
    ERROR = "error"


@dataclass
class ExpansionJob:
    capture: str
    delete_count: int
    prior_words: str = ""
    # Re-type after removing injection (e.g. trigger + intent); empty → delete injected text only (palette).
    undo_restore: str = ""
    # macOS process name from System Events when capture was submitted (inject refocus).
    focused_app_at_submit: str = ""


@dataclass
class UndoFrame:
    injected: str
    restore: str
    # True when expansion used OS accessibility string swap (undo uses same path).
    via_accessibility: bool = False


@dataclass(frozen=True)
class TraySnapshot:
    status: TrayAppStatus
    detail: str
    error: str
    model: str
    expansion_queued: int
    enrich_queued: int
    undo_depth: int
    # Monotonic seconds in "thinking" (0 if idle); LLM wall-clock cap for tooltip context.
    thinking_elapsed_s: float
    thinking_capture: str
    l3_timeout_s: float
    degraded_hint: str


@dataclass(frozen=True)
class LiveEnrichJob:
    dedup_key: str
    cache_prompt: str
    user_text: str
    system: str
