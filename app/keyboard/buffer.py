"""Buffer-layer helpers: construct EngineEvents from flushed tokens (listener remains key I/O only)."""

from __future__ import annotations

from app.engine.events import EngineEvent, EngineEventType, LivePhrasePayload, LiveWordPayload


def live_word_completed(word: str) -> EngineEvent:
    return EngineEvent(EngineEventType.LIVE_WORD, LiveWordPayload(word=word))


def live_phrase_completed(phrase: str) -> EngineEvent:
    return EngineEvent(EngineEventType.LIVE_PHRASE, LivePhrasePayload(phrase=phrase))
