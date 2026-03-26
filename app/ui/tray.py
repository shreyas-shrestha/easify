"""System tray status (pystray + Pillow)."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Callable

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.engine.service import ExpansionService

LOG = get_logger(__name__)


def _icon_image(state: str):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if state == "thinking":
        fill = (80, 120, 255, 255)
    elif state == "error":
        fill = (220, 60, 60, 255)
    else:
        fill = (40, 180, 90, 255)
    draw.ellipse((8, 8, size - 8, size - 8), fill=fill)
    return img


def run_tray_app(service: "ExpansionService", stop: threading.Event, on_quit: Callable[[], None]) -> None:
    try:
        import pystray
        from pystray import Menu, MenuItem
    except ImportError:
        LOG.warning("install pystray + Pillow for tray: pip install pystray Pillow")
        return

    icon_ref: list = []

    def snapshot_title() -> str:
        st, detail, err = service.tray_snapshot()
        if err and st == "error":
            return f"Easify — error: {err[:100]}"
        if detail:
            return f"Easify — {st}: {detail[:100]}"
        return f"Easify — {st}"

    def _quit(icon, _item) -> None:
        on_quit()
        icon.stop()

    menu = Menu(MenuItem("Quit", _quit))
    icon = pystray.Icon("Easify", _icon_image("idle"), title="Easify", menu=menu)
    icon_ref.append(icon)

    def poll() -> None:
        last_state = ""
        last_title = ""
        while not stop.is_set():
            st, _, _ = service.tray_snapshot()
            if st != last_state:
                last_state = st
                try:
                    icon.icon = _icon_image(st)
                except Exception:
                    pass
            title = snapshot_title()
            if title != last_title:
                last_title = title
                try:
                    icon.title = title
                except Exception:
                    pass
            time.sleep(0.4)
        try:
            icon.stop()
        except Exception:
            pass

    threading.Thread(target=poll, daemon=True).start()
    try:
        icon.run()
    except Exception as e:
        LOG.warning("tray failed: %s", e)
