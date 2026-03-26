"""Select keyboard capture backend (pynput, keyboard, evdev)."""

from __future__ import annotations

import platform
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
            LOG.error(
                "evdev backend failed (%s) — falling back to pynput. "
                "Fix EASIFY_EVDEV_DEVICE, permissions (input group / udev), or install python-evdev.",
                e,
            )
            if platform.system() == "Linux":
                try:
                    from app.context.focus import linux_session_is_wayland

                    if linux_session_is_wayland():
                        LOG.warning(
                            "Wayland: pynput often cannot capture or inject into native Wayland clients; "
                            "evdev is the recommended path once device access works."
                        )
                except Exception:
                    pass
    listener._run_pynput_blocking(stop)
