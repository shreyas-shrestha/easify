"""Capture-path expansion preview as ``EngineAction`` (single place for confirm UI)."""

from __future__ import annotations

from app.config.settings import Settings
from app.engine.actions import ActionType, EngineAction


async def resolve_capture_preview_async(settings: Settings, text: str) -> EngineAction:
    if not settings.expansion_preview:
        return EngineAction(ActionType.INSERT_TEXT, text, 1.0, "no_preview")
    return EngineAction(ActionType.SHOW_PREVIEW, text, 1.0, "expansion_preview")
