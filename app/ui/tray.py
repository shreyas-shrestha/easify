"""System tray status (pystray + Pillow)."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.engine.service import ExpansionService, TraySnapshot

LOG = get_logger(__name__)

_MAX_TOOLTIP_CHARS = 1800


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


def _format_tooltip(snap: "TraySnapshot", *, hint_after_s: float = 2.0) -> str:
    lines = [
        f"Easify — {snap.status}",
        f"Model: {snap.model}",
        f"Queued: {snap.expansion_queued} expansion | {snap.enrich_queued} enrich",
        f"Undo stack: {snap.undo_depth}",
    ]
    if snap.status == "thinking":
        cap = (snap.thinking_capture or "").strip()
        lines.append(f"Intent: {cap[:180]}" if cap else "Resolving…")
        if snap.thinking_elapsed_s >= max(0.5, hint_after_s):
            lines.append(
                f"Elapsed {snap.thinking_elapsed_s:.1f}s — LLM timeout up to {snap.l3_timeout_s:.0f}s "
                "(EASIFY_OLLAMA_TIMEOUT). If Ollama is down you will get an error after retries / timeout."
            )
        elif snap.thinking_elapsed_s >= 0.5:
            lines.append(f"Elapsed {snap.thinking_elapsed_s:.1f}s…")
    if snap.degraded_hint:
        lines.append(f"Hint: {snap.degraded_hint[:500]}")
    if snap.status == "error" and snap.detail:
        lines.append(f"Summary: {snap.detail[:600]}")
    elif snap.detail:
        lines.append(f"Last expansion: {snap.detail[:600]}")
    if snap.error:
        body = snap.error.strip()
        if len(body) > 1400:
            body = body[:1397] + "…"
        lines.append("Error / traceback:\n" + body)
    out = "\n".join(lines)
    if len(out) > _MAX_TOOLTIP_CHARS:
        return out[: _MAX_TOOLTIP_CHARS - 1] + "…"
    return out


def run_tray_app(
    service: "ExpansionService",
    stop: threading.Event,
    on_quit: Callable[[], None],
    *,
    icon_holder: Optional[list] = None,
) -> None:
    try:
        import pystray
        from pystray import Menu, MenuItem
    except ImportError:
        LOG.warning("install pystray + Pillow for tray: pip install pystray Pillow")
        return

    def copy_last_error(_icon, _item) -> None:
        from app.utils import clipboard as cb

        snap = service.tray_snapshot()
        if snap.error:
            try:
                cb.set_clipboard(snap.error)
                LOG.info("copied tray error to clipboard (%s chars)", len(snap.error))
            except Exception as e:
                LOG.warning("clipboard copy failed: %s", e)

    def dismiss_error(_icon, _item) -> None:
        service.tray_clear_error()

    def _quit(icon, _item) -> None:
        on_quit()
        icon.stop()

    menu = Menu(
        MenuItem("Copy last error (full text)", copy_last_error),
        MenuItem("Dismiss error / reset tray to idle", dismiss_error),
        Menu.SEPARATOR,
        MenuItem("Quit", _quit),
    )
    icon = pystray.Icon("Easify", _icon_image("idle"), title="Easify", menu=menu)
    if icon_holder is not None:
        icon_holder.clear()
        icon_holder.append(icon)

    def poll() -> None:
        last_state = ""
        last_title = ""
        while not stop.is_set():
            snap = service.tray_snapshot()
            if snap.status != last_state:
                last_state = snap.status
                try:
                    icon.icon = _icon_image(snap.status)
                except Exception:
                    pass
            title = _format_tooltip(snap, hint_after_s=service.settings.tray_thinking_hint_after_s)
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
