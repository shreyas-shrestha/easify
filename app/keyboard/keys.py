"""Normalize pynput keys to capture characters."""

from __future__ import annotations

from typing import Any, Optional


def pynput_key_char(key: Any) -> Optional[str]:
    from pynput.keyboard import Key

    if key == Key.enter or key == getattr(Key, "kp_enter", Key.enter):
        return "\n"
    if key == Key.backspace:
        return "\b"
    if key == Key.space:
        return " "
    if key == Key.tab:
        return "\t"
    if getattr(key, "char", None) is not None:
        return key.char
    return None


def pynput_skip_key(key: Any, *, capture_active: bool = False) -> bool:
    from pynput.keyboard import Key

    skips = (
        Key.shift, Key.shift_l, Key.shift_r, Key.ctrl, Key.ctrl_l, Key.ctrl_r,
        Key.alt, Key.alt_l, Key.alt_r, Key.cmd, Key.cmd_l, Key.cmd_r,
        Key.caps_lock,
    )
    if not capture_active and key == Key.esc:
        return True
    return key in skips
