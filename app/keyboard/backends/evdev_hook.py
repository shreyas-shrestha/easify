"""Linux evdev keyboard capture (requires read access to /dev/input/event*)."""

from __future__ import annotations

import select
import threading
from typing import TYPE_CHECKING

from pynput.keyboard import Controller, Key

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.keyboard.listener import KeyboardListener

LOG = get_logger(__name__)


def run_evdev_blocking(listener: "KeyboardListener", stop: threading.Event) -> None:
    from evdev import InputDevice, ecodes

    path = (listener.settings.evdev_device or "").strip()
    if not path:
        LOG.error(
            "evdev: EASIFY_EVDEV_DEVICE is empty — set to a keyboard device "
            "(e.g. /dev/input/event3 from `libinput list-devices`). This backend does not fall back in-process."
        )
        raise RuntimeError("EASIFY_EVDEV_DEVICE required for backend=evdev")

    try:
        device = InputDevice(path)
    except PermissionError as e:
        LOG.error(
            "evdev: permission denied opening %s (%s). Add your user to the 'input' group "
            "(sudo usermod -aG input $USER; log out and back in) or use a udev rule to grant access.",
            path,
            e,
        )
        raise RuntimeError(f"evdev permission denied: {path}") from e
    letters = {getattr(ecodes, f"KEY_{c}"): c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    listener._ctrl = Controller()
    listener._setup_inject(listener._ctrl)
    fd = device.fd
    LOG.info("listening (evdev) %s", path)

    def inject_key(key_obj: object) -> None:
        listener._on_press(key_obj)

    while not stop.is_set():
        try:
            r, _, _ = select.select([fd], [], [], 0.25)
            if not r:
                continue
            for ev in device.read():
                if stop.is_set():
                    break
                if ev.type != ecodes.EV_KEY:
                    continue
                if ev.value != 1:
                    continue
                c = ev.code
                if c == ecodes.KEY_SPACE:
                    inject_key(Key.space)
                elif c == ecodes.KEY_ENTER:
                    inject_key(Key.enter)
                elif c == ecodes.KEY_BACKSPACE:
                    inject_key(Key.backspace)
                elif c == ecodes.KEY_TAB:
                    inject_key(Key.tab)
                elif c in letters:

                    class _K:
                        __slots__ = ("char",)
                        char = letters[c]

                    inject_key(_K())
        except OSError as e:
            LOG.error("evdev read failed: %s", e)
            break
    try:
        device.close()
    except OSError:
        pass
