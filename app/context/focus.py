"""Best-effort foreground application name (macOS / Windows / Linux)."""

from __future__ import annotations

import platform
import re
import subprocess

from app.utils.log import get_logger

LOG = get_logger(__name__)


def _run_cmd(args: list[str], timeout: float = 0.35) -> str:
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        LOG.debug("focus probe %s: %s", args[:1], e)
        return ""


def _macos_frontmost() -> str:
    script = (
        'tell application "System Events" to get name of first application process '
        'whose frontmost is true'
    )
    out = _run_cmd(["/usr/bin/osascript", "-e", script], timeout=0.5)
    return out or "unknown"


def _windows_frontmost() -> str:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return "unknown"

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "unknown"
    buf_len = 512
    buff = ctypes.create_unicode_buffer(buf_len)
    user32.GetWindowTextW(hwnd, buff, buf_len)
    title = buff.value.strip()
    if title:
        return title[:120]
    return "unknown"


def _linux_frontmost() -> str:
    # Wayland: no standard; X11: try xdotool or xprop
    out = _run_cmd(["xdotool", "getactivewindow", "getwindowname"], timeout=0.35)
    if out:
        return out[:120]
    wid = _run_cmd(["xdotool", "getactivewindow"], timeout=0.35)
    if wid and re.match(r"^[0-9]+$", wid):
        out2 = _run_cmd(["xprop", "-id", wid, "WM_CLASS"], timeout=0.35)
        if out2 and "=" in out2:
            m = re.search(r'"([^"]+)"', out2)
            if m:
                return m.group(1)[:120]
    return "unknown"


def get_focused_app_name() -> str:
    """Short label for LLM context; never raises."""
    try:
        s = platform.system()
        if s == "Darwin":
            return _macos_frontmost()
        if s == "Windows":
            return _windows_frontmost()
        if s == "Linux":
            return _linux_frontmost()
    except Exception as e:
        LOG.debug("focus detection: %s", e)
    return "unknown"
