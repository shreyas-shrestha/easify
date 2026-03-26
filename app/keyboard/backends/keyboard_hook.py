"""Global hooks via the `keyboard` package (optional dependency)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from pynput.keyboard import Controller, Key

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.keyboard.listener import KeyboardListener

LOG = get_logger(__name__)

_SKIP = frozenset(
    {
        "shift",
        "left shift",
        "right shift",
        "ctrl",
        "left ctrl",
        "right ctrl",
        "alt",
        "left alt",
        "right alt",
        "windows",
        "left windows",
        "right windows",
        "command",
        "left command",
        "right command",
        "caps lock",
    }
)


def run_keyboard_hook_blocking(listener: "KeyboardListener", stop: threading.Event) -> None:
    import keyboard

    listener._ctrl = Controller()
    listener._setup_inject(listener._ctrl)

    def on_event(event: keyboard.KeyboardEvent) -> None:
        if stop.is_set() or listener._inject_depth > 0:
            return
        if listener.service.inject_lock.locked():
            return
        if event.event_type != keyboard.KEY_DOWN:
            return
        name = (event.name or "").lower()
        if name in _SKIP:
            return
        if name in ("enter", "return", "numpad enter"):
            listener._on_press(Key.enter)
            return
        if name == "backspace":
            listener._on_press(Key.backspace)
            return
        if name == "space":
            listener._on_press(Key.space)
            return
        if name == "tab":
            listener._on_press(Key.tab)
            return
        if name == "esc":
            listener._on_press(Key.esc)
            return
        if len(name) == 1:
            class _K:
                __slots__ = ("char",)
                char = name

            listener._on_press(_K())
            return
        if name.startswith("numpad ") and len(name) == 8 and name[-1].isdigit():
            class _K2:
                __slots__ = ("char",)
                char = name[-1]

            listener._on_press(_K2())
            return

    hook = keyboard.hook(on_event, suppress=False)
    LOG.info("listening (keyboard package) backend=keyboard")
    while not stop.wait(0.25):
        pass
    try:
        keyboard.unhook(hook)
    except Exception:
        keyboard.unhook_all()
