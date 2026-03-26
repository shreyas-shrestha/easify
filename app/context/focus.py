"""Best-effort foreground application name (macOS / Windows / Linux)."""

from __future__ import annotations

import platform
import re
import subprocess
import threading
import time

from app.utils.log import get_logger

LOG = get_logger(__name__)

_focus_lock = threading.Lock()
_focus_cache_at: float = 0.0
_focus_cache_val: str = ""
_FOCUS_TTL_SEC = 0.5


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


def get_focused_app_name(ttl_sec: float = _FOCUS_TTL_SEC) -> str:
    """Short label for LLM context; never raises. Cached briefly to avoid slow AppleScript."""
    global _focus_cache_at, _focus_cache_val
    now = time.monotonic()
    with _focus_lock:
        if _focus_cache_val and (now - _focus_cache_at) < max(0.0, ttl_sec):
            return _focus_cache_val
    try:
        s = platform.system()
        if s == "Darwin":
            label = _macos_frontmost()
        elif s == "Windows":
            label = _windows_frontmost()
        elif s == "Linux":
            label = _linux_frontmost()
        else:
            label = "unknown"
    except Exception as e:
        LOG.debug("focus detection: %s", e)
        label = "unknown"
    with _focus_lock:
        _focus_cache_at = time.monotonic()
        _focus_cache_val = label or "unknown"
    return _focus_cache_val


def get_focused_app_name_fresh(*, cmd_timeout: float = 1.25) -> str:
    """Uncached frontmost app — use when injecting so we know where capture was typed."""
    try:
        s = platform.system()
        if s == "Darwin":
            script = (
                'tell application "System Events" to get name of first application process '
                "whose frontmost is true"
            )
            out = _run_cmd(["/usr/bin/osascript", "-e", script], timeout=cmd_timeout)
            return (out or "unknown").strip() or "unknown"
        return get_focused_app_name(ttl_sec=0)
    except Exception as e:
        LOG.debug("fresh focus detection: %s", e)
        return "unknown"


def activate_application(name: str, *, cmd_timeout: float = 2.5) -> bool:
    """Raise target app (macOS). Best-effort for Windows/Linux."""
    app = (name or "").strip()
    if not app or app == "unknown":
        return False
    s = platform.system()
    if s == "Darwin":
        safe = app.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "{safe}" to activate'
        try:
            r = subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=cmd_timeout,
                check=False,
            )
            if r.returncode != 0 and (r.stderr or "").strip():
                LOG.debug("activate %r: %s", app, (r.stderr or "").strip()[:200])
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            LOG.debug("activate %r failed: %s", app, e)
            return False
    if s == "Windows":
        try:
            import ctypes

            u = ctypes.windll.user32  # type: ignore[attr-defined]
            hwnd = u.FindWindowW(None, app[:512])  # fragile by title
            if hwnd:
                u.ShowWindow(hwnd, 9)
                u.SetForegroundWindow(hwnd)
                return True
        except Exception as e:
            LOG.debug("Windows activate: %s", e)
        return False
    return False


def layer_warrants_pre_inject_refocus(layer: str) -> bool:
    """Refocus is only worth the AppleScript cost after L3 (user may have switched app while waiting)."""
    ly = (layer or "").strip()
    return ly.startswith("L3-")


def refocus_if_needed_for_inject(*, captured_app: str, cmd_timeout: float = 1.25) -> None:
    """If the user switched away while the worker ran, bring the capture app forward before inject."""
    cap = (captured_app or "").strip()
    if not cap or cap == "unknown":
        return
    now = get_focused_app_name_fresh(cmd_timeout=cmd_timeout)
    if now == cap:
        return
    LOG.info("inject refocus → %r (frontmost was %r)", cap, now)
    activate_application(cap, cmd_timeout=2.5)
    time.sleep(0.12)
