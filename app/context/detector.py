"""Build InputContext from engine events (sync, no heavy work)."""

from __future__ import annotations

from app.context.apps import classify_app_kind
from app.context.input_context import ActivationKind, AppKind, InputContext, IntentKind, TextKind
from app.context.intent import classify_intent_from_text
from app.engine.events import CaptureSubmitPayload, EngineEvent, EngineEventType


def detect_input_context(event: EngineEvent, *, focused_app_raw: str) -> InputContext:
    app = classify_app_kind(focused_app_raw)

    if event.type is EngineEventType.LIVE_WORD:
        activation = ActivationKind.LIVE_SPACE
        text_kind = TextKind.WORD
        intent = IntentKind.UNKNOWN
    elif event.type is EngineEventType.LIVE_PHRASE:
        activation = ActivationKind.LIVE_SPACE
        text_kind = TextKind.PHRASE
        intent = IntentKind.UNKNOWN
    elif event.type is EngineEventType.CAPTURE_SUBMIT:
        activation = ActivationKind.CAPTURE
        text_kind = TextKind.SENTENCE
        cap = ""
        if isinstance(event.payload, CaptureSubmitPayload):
            cap = event.payload.capture_text or ""
        intent = classify_intent_from_text(cap)
    elif event.type is EngineEventType.PALETTE_OPEN:
        activation = ActivationKind.PALETTE
        text_kind = TextKind.SENTENCE
        intent = IntentKind.UNKNOWN
    elif event.type is EngineEventType.DOUBLE_SPACE:
        activation = ActivationKind.DOUBLE_SPACE
        text_kind = TextKind.SENTENCE
        intent = IntentKind.UNKNOWN
    else:
        activation = ActivationKind.CAPTURE
        text_kind = TextKind.WORD
        intent = IntentKind.UNKNOWN

    return InputContext(app=app, activation=activation, text_kind=text_kind, intent=intent)
