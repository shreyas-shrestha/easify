"""Clipboard read/write + optional save/restore around paste."""

from __future__ import annotations

import platform
import subprocess
from typing import Optional

import pyperclip


def _pbpaste() -> Optional[str]:
    if platform.system() != "Darwin":
        return None
    try:
        r = subprocess.run(
            ["/usr/bin/pbpaste"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        return r.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def get_clipboard() -> str:
    if platform.system() == "Darwin":
        p = _pbpaste()
        if p is not None:
            return p
    try:
        return pyperclip.paste() or ""
    except Exception:
        return ""


def set_clipboard(text: str) -> None:
    if platform.system() == "Darwin":
        try:
            subprocess.run(["/usr/bin/pbcopy"], input=text.encode("utf-8"), check=True, timeout=10)
            return
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    pyperclip.copy(text)
