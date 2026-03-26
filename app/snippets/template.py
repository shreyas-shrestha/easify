"""Placeholder expansion for snippet bodies: {date}, {clipboard}, {input:…}, etc."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Optional

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([^}]*))?\}")


def _tk_ask(prompt: str) -> str:
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            s = simpledialog.askstring("Easify", prompt or "Value:", parent=root)
        finally:
            root.destroy()
        return (s or "").strip()
    except Exception:
        return ""


def expand_snippet_template(
    text: str,
    *,
    focused_app: str = "",
    clipboard: str = "",
    allow_input_dialog: bool = False,
    input_fn: Optional[Callable[[str], str]] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    Replace ``{name}``, ``{name:arg}`` placeholders. ``{{`` / ``}}`` emit literal braces.

    Supported: ``date`` (optional strftime after ``:``), ``time``, ``datetime``, ``clipboard``,
    ``focused_app``, ``cursor_position`` (empty — not available), ``input`` (blocking dialog if allowed).
    """
    if "{" not in text:
        return text
    raw = text.replace("{{", "\ue000open\ue001").replace("}}", "\ue000close\ue001")
    dt = now or datetime.now()

    def sub(m: re.Match[str]) -> str:
        name = (m.group(1) or "").lower()
        arg = (m.group(2) or "").strip()
        if name == "date":
            fmt = arg if arg else "%Y-%m-%d"
            try:
                return dt.strftime(fmt)
            except ValueError:
                return dt.strftime("%Y-%m-%d")
        if name == "time":
            fmt = arg if arg else "%H:%M:%S"
            try:
                return dt.strftime(fmt)
            except ValueError:
                return dt.strftime("%H:%M:%S")
        if name in ("datetime", "dt"):
            return dt.isoformat(timespec="seconds")
        if name == "clipboard":
            return clipboard
        if name in ("focused_app", "app"):
            return focused_app
        if name in ("cursor_position", "cursor"):
            return ""
        if name in ("input", "prompt"):
            fn = input_fn or (_tk_ask if allow_input_dialog else None)
            if fn is None:
                return ""
            return fn(arg or "Value:")
        return m.group(0)

    out = _PLACEHOLDER.sub(sub, raw)
    return out.replace("\ue000open\ue001", "{").replace("\ue000close\ue001", "}")
