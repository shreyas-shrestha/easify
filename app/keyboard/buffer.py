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


def compute_capture_submit_metadata(
    *,
    raw_buf: str,
    close: str,
    from_prefix: bool,
    use_prefix_trigger: bool,
    trigger: str,
    enter_backspaces: int,
    entered_with_newline: bool,
) -> tuple[str, int, str] | None:
    """Return ``(run_prompt, delete_count, undo_restore)`` or ``None`` if intent text is empty."""
    had_close_suffix = bool(close and raw_buf.endswith(close))
    raw = raw_buf[: -len(close)] if had_close_suffix else raw_buf
    run_prompt = raw.strip()
    if not run_prompt:
        return None
    if from_prefix and use_prefix_trigger and trigger:
        if close and not entered_with_newline:
            dc = len(trigger) + len(raw) + len(close)
            undo = f"{trigger}{raw}{close}"
        elif close and entered_with_newline and had_close_suffix:
            dc = len(trigger) + len(raw) + len(close) + max(0, enter_backspaces)
            undo = f"{trigger}{raw}{close}"
        else:
            dc = len(trigger) + len(raw) + max(0, enter_backspaces)
            undo = f"{trigger}{raw}"
    else:
        if close and not entered_with_newline:
            dc = len(raw) + len(close)
            undo = f"{raw}{close}"
        elif close and entered_with_newline and had_close_suffix:
            dc = len(raw) + len(close) + max(0, enter_backspaces)
            undo = f"{raw}{close}"
        else:
            dc = len(raw) + max(0, enter_backspaces)
            undo = raw
    return run_prompt, dc, undo


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
