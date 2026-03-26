"""
macOS Accessibility (AXUIElement): read focused value, string replace, write back.

Requires pyobjc-framework-ApplicationServices and Accessibility permission for the host app.
Caret/selection behavior is defined by the target app when AXValue is set.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Optional, Tuple

from app.utils.log import get_logger

LOG = get_logger(__name__)

# AXUIElementCopyAttributeValue can block ~5s per call on a hung app; bound wall time per inject.
_AX_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="easify-ax")
_AX_FIND_TOTAL_BUDGET_S = 2.6
_AX_PER_ATTR_MIN_S = 0.08
_AX_PER_ATTR_MAX_S = 0.55

_READ_ATTRS = ("AXValue", "AXTitle")
_WRITE_ATTR = "AXValue"
_MAX_PARENT_HOPS = 6


def _py_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        s = val
    else:
        try:
            s = str(val)
        except Exception:
            return None
    return s if s is not None else None


def _ax_err_ok(err: Any) -> bool:
    if err is None:
        return True
    try:
        return int(err) == 0
    except (TypeError, ValueError):
        return err in (0, "AXErrorSuccess", "kAXErrorSuccess")


def _copy_attr(elem: Any, name: str) -> Tuple[Any, Any]:
    from ApplicationServices import AXUIElementCopyAttributeValue

    try:
        out = AXUIElementCopyAttributeValue(elem, name, None)
    except Exception as e:
        LOG.debug("AXUIElementCopyAttributeValue %s: %s", name, e)
        return -1, None
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], out[1]
    return 0, out


def _copy_attr_timed(elem: Any, name: str, *, deadline: float) -> Tuple[Any, Any]:
    """Run AX read off the inject thread's direct wait so a stuck app cannot block for many seconds."""
    now = time.monotonic()
    if now >= deadline:
        return -1, None
    per = min(_AX_PER_ATTR_MAX_S, max(_AX_PER_ATTR_MIN_S, deadline - now))
    fut = _AX_EXECUTOR.submit(_copy_attr, elem, name)
    try:
        return fut.result(timeout=per)
    except FuturesTimeoutError:
        LOG.warning("AX attribute %r read timed out (%.2fs)", name, per)
        return -1, None


def _set_attr(elem: Any, name: str, value: str) -> bool:
    from ApplicationServices import AXUIElementSetAttributeValue

    try:
        out = AXUIElementSetAttributeValue(elem, name, value)
    except Exception as e:
        LOG.debug("AXUIElementSetAttributeValue %s: %s", name, e)
        return False
    if out is None:
        return True
    if isinstance(out, tuple) and len(out) >= 1:
        return _ax_err_ok(out[0])
    return _ax_err_ok(out)


def _focused_element() -> Optional[Any]:
    from ApplicationServices import AXUIElementCreateSystemWide

    root = AXUIElementCreateSystemWide()
    err, app = _copy_attr(root, "AXFocusedApplication")
    if _ax_err_ok(err) and app is not None:
        err2, focused = _copy_attr(app, "AXFocusedUIElement")
        if _ax_err_ok(err2) and focused is not None:
            return focused
    err3, focused2 = _copy_attr(root, "AXFocusedUIElement")
    if _ax_err_ok(err3) and focused2 is not None:
        return focused2
    return None


def _find_editable_value(elem: Optional[Any]) -> Tuple[Optional[Any], Optional[str]]:
    """Walk up AXParent until AXValue/AXTitle yields non-empty string suitable for replace."""
    deadline = time.monotonic() + _AX_FIND_TOTAL_BUDGET_S
    cur = elem
    for _ in range(_MAX_PARENT_HOPS):
        if cur is None:
            break
        if time.monotonic() >= deadline:
            LOG.warning("AX find editable: total budget (%.1fs) exceeded", _AX_FIND_TOTAL_BUDGET_S)
            break
        for attr in _READ_ATTRS:
            err, val = _copy_attr_timed(cur, attr, deadline=deadline)
            if not _ax_err_ok(err):
                continue
            s = _py_str(val)
            if s is not None:
                return cur, s
        _, parent = _copy_attr_timed(cur, "AXParent", deadline=deadline)
        cur = parent
    return None, None


def focused_element_is_password_field() -> bool:
    """True if the focused control (or a short ancestor chain) is a secure/password text field."""
    focused = _focused_element()
    if focused is None:
        return False
    cur: Any = focused
    for _ in range(_MAX_PARENT_HOPS + 3):
        if cur is None:
            break
        err, sub = _copy_attr(cur, "AXSubrole")
        su = (_py_str(sub) or "").lower()
        if "secure" in su:
            return True
        err2, rd = _copy_attr(cur, "AXRoleDescription")
        rds = (_py_str(rd) or "").lower()
        if "password" in rds:
            return True
        _, parent = _copy_attr(cur, "AXParent")
        cur = parent
    return False


def replace_substring_in_focused_element(
    old: str,
    new: str,
    *,
    match_last: bool = True,
    unique_match_only: bool = True,
) -> bool:
    focused = _focused_element()
    if focused is None:
        LOG.debug("AX: no focused UI element")
        return False
    elem, cur = _find_editable_value(focused)
    if not elem or cur is None:
        LOG.debug("AX: could not read editable value from focus chain")
        return False
    n = cur.count(old)
    if unique_match_only and n != 1:
        LOG.info(
            "AX: substring occurs %s times in focused field (unique_match_only) — skipping accessibility inject",
            n,
        )
        return False
    idx = cur.rfind(old) if match_last else cur.find(old)
    if idx < 0:
        LOG.debug("AX: capture substring not found in field (len=%s)", len(cur))
        return False
    updated = cur[:idx] + new + cur[idx + len(old) :]
    if updated == cur:
        return True
    if not _set_attr(elem, _WRITE_ATTR, updated):
        LOG.debug("AX: SetAttribute %s failed", _WRITE_ATTR)
        return False
    LOG.info("inject accessibility (AX) replaced len=%s → len=%s", len(old), len(new))
    return True
