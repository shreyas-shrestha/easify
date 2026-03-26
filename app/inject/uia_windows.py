"""
Windows UI Automation: focused control ValuePattern string replace.

Optional dependency: uiautomation (see easify[accessibility]).
"""

from __future__ import annotations

from app.utils.log import get_logger

LOG = get_logger(__name__)


def replace_substring_in_focused_element(old: str, new: str) -> bool:
    import uiautomation as auto

    c = auto.GetFocusedControl()
    if c is None:
        LOG.debug("UIA: no focused control")
        return False
    try:
        vp = c.GetValuePattern()
    except Exception as e:
        LOG.debug("UIA: ValuePattern unavailable: %s", e)
        return False
    if vp is None or not getattr(vp, "IsSupported", True):
        return False
    try:
        cur = vp.Value or ""
    except Exception:
        cur = ""
    idx = cur.rfind(old)
    if idx < 0:
        LOG.debug("UIA: capture substring not found (len=%s)", len(cur))
        return False
    updated = cur[:idx] + new + cur[idx + len(old) :]
    if updated == cur:
        return True
    try:
        vp.SetValue(updated)
    except Exception as e:
        LOG.warning("UIA SetValue failed: %s", e)
        return False
    LOG.info("inject accessibility (UIA) replaced len=%s → len=%s", len(old), len(new))
    return True
