"""Startup notices for pynput GlobalHotKeys — OS/app chords win silently."""

from __future__ import annotations

import re

from app.utils.log import get_logger

LOG = get_logger(__name__)

_CMD_SPACE = re.compile(r"<cmd>\s*\+\s*<space>", re.IGNORECASE)


def _modifiers_in_hotkey(hotkey: str) -> frozenset[str]:
    parts = [p.strip().lower() for p in hotkey.replace(" ", "").split("+") if p.strip()]
    mods: set[str] = set()
    for p in parts:
        if len(p) >= 3 and p[0] == "<" and p[-1] == ">":
            inner = p[1:-1]
            if inner in ("ctrl", "control"):
                mods.add("ctrl")
            elif inner in ("cmd", "alt", "shift"):
                mods.add(inner)
    return frozenset(mods)


def describe_global_hotkey_risks(
    system: str,
    *,
    palette: str,
    undo: str,
) -> list[str]:
    """Human-readable warnings; not exhaustive OS detection."""
    msgs: list[str] = []
    if not any((palette, undo)):
        return msgs

    msgs.append(
        "Global hotkeys (pynput) can be swallowed by the OS or the focused app before Easify sees them. "
        "If a chord stops working, choose another or set EASIFY_PALETTE_HOTKEY_ALT as a second palette binding."
    )

    if system == "Darwin":
        for label, hk in (("Palette", palette), ("Undo", undo)):
            if not hk.strip():
                continue
            mods = _modifiers_in_hotkey(hk)
            if "ctrl" in mods and "shift" in mods:
                msgs.append(
                    f"{label} hotkey {hk!r}: Ctrl+Shift on macOS often clashes with IDE/accessibility "
                    "shortcuts; try Cmd-based chords or PALETTE_HOTKEY_ALT."
                )
            if _CMD_SPACE.search(hk):
                msgs.append(
                    f"{label} hotkey {hk!r}: may conflict with Spotlight or input-source switching (Cmd+Space)."
                )

    return msgs


def log_global_hotkey_notices(
    system: str,
    *,
    palette: str,
    undo: str,
) -> None:
    for m in describe_global_hotkey_risks(system, palette=palette, undo=undo):
        LOG.warning("%s", m)
