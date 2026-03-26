"""Unit tests for :mod:`app.keyboard.capture_fsm`."""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

import pytest
from pynput.keyboard import Key

from app.engine.buffer import CaptureBuffer, TriggerState
from app.keyboard.capture_fsm import (
    CaptureInputSession,
    CapturingKeyKind,
    PrefixTriggerResult,
)


@pytest.fixture
def mock_settings() -> MagicMock:
    s = MagicMock()
    s.capture_close = "//"
    s.capture_max_chars = 4000
    s.double_space_activation = True
    s.double_space_window_ms = 500
    return s


def test_double_space_arm_then_open(mock_settings: MagicMock) -> None:
    cap = CaptureBuffer()
    tr = TriggerState()
    recent: deque[str] = deque(maxlen=16)
    sess = CaptureInputSession(mock_settings, cap, tr, recent)
    assert sess.try_double_space_open_capture(" ") is False
    assert sess.try_double_space_open_capture(" ") is True
    assert not sess.is_capturing()


def test_enter_from_double_space(mock_settings: MagicMock) -> None:
    cap = CaptureBuffer()
    sess = CaptureInputSession(mock_settings, cap, TriggerState(), deque(maxlen=16))
    sess.enter_from_double_space()
    assert sess.is_capturing()


def test_prefix_double_slash_enters_capture(mock_settings: MagicMock) -> None:
    sess = CaptureInputSession(mock_settings, CaptureBuffer(), TriggerState(), deque(maxlen=16))
    assert sess.try_prefix_trigger("/", trigger="//", use_prefix=True) == PrefixTriggerResult.NO_MATCH
    assert sess.try_prefix_trigger("/", trigger="//", use_prefix=True) == PrefixTriggerResult.ENTERED_CAPTURE
    assert sess.is_capturing()


def test_prefix_suppressed_for_https_url(mock_settings: MagicMock) -> None:
    recent: deque[str] = deque(maxlen=16)
    for c in "https://":
        recent.append(c)
    sess = CaptureInputSession(mock_settings, CaptureBuffer(), TriggerState(), recent)
    assert sess.try_prefix_trigger("/", trigger="//", use_prefix=True) == PrefixTriggerResult.NO_MATCH
    assert sess.try_prefix_trigger("/", trigger="//", use_prefix=True) == PrefixTriggerResult.SUPPRESSED_URL
    assert not sess.is_capturing()


def test_capturing_submit_on_enter(mock_settings: MagicMock) -> None:
    sess = CaptureInputSession(mock_settings, CaptureBuffer(), TriggerState(), deque(maxlen=16))
    sess.enter_from_prefix()
    sess._capture.push("h")
    sess._capture.push("i")
    res = sess.handle_capturing_key(Key.enter, None, debug=False)
    assert res.kind == CapturingKeyKind.SUBMIT
    assert res.raw_buf == "hi"
    assert res.entered_with_newline is True
    assert not sess.is_capturing()


def test_capturing_esc_cancels(mock_settings: MagicMock) -> None:
    sess = CaptureInputSession(mock_settings, CaptureBuffer(), TriggerState(), deque(maxlen=16))
    sess.enter_from_prefix()
    res = sess.handle_capturing_key(Key.esc, None, debug=False)
    assert res.kind == CapturingKeyKind.CANCEL
    assert not sess.is_capturing()
