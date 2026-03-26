"""Capture-path expansion preview as ``EngineAction`` (single place for confirm UI)."""

from __future__ import annotations

import asyncio

from app.config.settings import Settings
from app.engine.actions import ActionType, EngineAction


async def resolve_capture_preview_async(settings: Settings, text: str) -> EngineAction:
    if not settings.expansion_preview:
        return EngineAction(ActionType.INSERT_TEXT, text, 1.0, "no_preview")
    from app.ui.preview import confirm_expansion

    ok = await asyncio.to_thread(confirm_expansion, text)
    if not ok:
        return EngineAction(ActionType.NOOP, None, 0.0, "preview_cancelled")
    return EngineAction(ActionType.INSERT_TEXT, text, 1.0, "preview_ok")
