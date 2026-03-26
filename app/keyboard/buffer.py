"""Buffer-layer helpers: construct EngineEvents from flushed tokens (listener remains key I/O only)."""

from __future__ import annotations

from app.engine.events import (
    CaptureSubmitPayload,
    EngineEvent,
    EngineEventType,
    LivePhrasePayload,
    LiveWordPayload,
)


def live_word_completed(word: str) -> EngineEvent:
    return EngineEvent(EngineEventType.LIVE_WORD, LiveWordPayload(word=word))


def live_phrase_completed(phrase: str) -> EngineEvent:
    return EngineEvent(EngineEventType.LIVE_PHRASE, LivePhrasePayload(phrase=phrase))


def capture_submit(
    *,
    capture_text: str,
    delete_count: int,
    undo_restore: str,
    prior_words: str,
    focused_app_at_submit: str,
) -> EngineEvent:
    return EngineEvent(
        EngineEventType.CAPTURE_SUBMIT,
        CaptureSubmitPayload(
            capture_text=capture_text,
            delete_count=delete_count,
            undo_restore=undo_restore,
            prior_words=prior_words,
            focused_app_at_submit=focused_app_at_submit,
        ),
    )
