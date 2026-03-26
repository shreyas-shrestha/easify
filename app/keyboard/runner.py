"""Select keyboard capture backend (pynput, keyboard, evdev)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.keyboard.listener import KeyboardListener

LOG = get_logger(__name__)


def run_keyboard_backend(listener: "KeyboardListener", stop: threading.Event) -> None:
    b = listener.settings.backend.lower().strip()
    if b in ("keyboard", "keyboard_hook"):
        try:
            from app.keyboard.backends.keyboard_hook import run_keyboard_hook_blocking

            run_keyboard_hook_blocking(listener, stop)
            return
        except ImportError:
            LOG.warning("pip install keyboard (optional) for backend=keyboard — falling back to pynput")
    elif b == "evdev":
        try:
            from app.keyboard.backends.evdev_hook import run_evdev_blocking

            run_evdev_blocking(listener, stop)
            return
        except Exception as e:
            LOG.warning("evdev backend failed (%s) — falling back to pynput", e)
    listener._run_pynput_blocking(stop)
