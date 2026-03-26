"""Close delimiter: suffix detection on capture buffer (no streaming matcher)."""

from __future__ import annotations

from app.engine.buffer import CaptureBuffer, strip_trailing_close


def test_strip_trailing_close() -> None:
    assert strip_trailing_close("hello//", "//") == "hello"
    assert strip_trailing_close("hello", "//") == "hello"


def test_capture_suffix_submit_simulation() -> None:
    """What the listener does: push chars; when text endswith close, pop close then submit body."""
    buf = CaptureBuffer()
    close = "//"
    for ch in "hi//":
        buf.push(ch)
        if ch != "\n" and close and buf.text().endswith(close):
            for _ in range(len(close)):
                buf.backspace()
            break
    assert buf.text() == "hi"
