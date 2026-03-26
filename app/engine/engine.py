"""Entry point: context + policy once, then router (thin)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.context.detector import detect_input_context
from app.context.focus import get_focused_app_name_fresh
from app.engine.events import EngineEvent
from app.engine.execution import ExecutionMode
from app.engine.router import EngineRouter
from app.policy.engine import resolve_policy

if TYPE_CHECKING:
    from app.config.settings import Settings


class EasifyEngine:
    def __init__(self, *, settings: "Settings", router: EngineRouter) -> None:
        self._settings = settings
        self._router = router

    def handle_event(self, event: EngineEvent) -> bool:
        focused = (
            get_focused_app_name_fresh()
            if self._settings.pre_inject_refocus
            else ""
        )
        ctx = detect_input_context(event, focused_app_raw=focused)
        policy = resolve_policy(ctx, self._settings)
        mode = self._router.execution_mode_for(event)
        if mode is ExecutionMode.LIVE_SYNC:
            return self._router.handle_live_sync(event, policy)
        if mode is ExecutionMode.CAPTURE_ASYNC:
            self._router.handle_capture_async(event, policy)
            return True
        return False
