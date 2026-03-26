"""Stable import path; implementation lives in :mod:`app.service.expansion_service`."""

from __future__ import annotations

from app.engine.pending_tail import PendingExpansionTail
from app.engine.types import ExpansionJob
from app.service.expansion_service import (
    ExpansionService,
    inject_focus_safe_for_keys,
    refocus_if_needed_for_inject,
)

_PendingExpansionTail = PendingExpansionTail

__all__ = [
    "ExpansionService",
    "ExpansionJob",
    "_PendingExpansionTail",
    "inject_focus_safe_for_keys",
    "refocus_if_needed_for_inject",
]
