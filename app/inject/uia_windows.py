"""
Windows UI Automation: focused control ValuePattern string replace.

Optional dependency: uiautomation (see easify[accessibility]).
"""

from __future__ import annotations

from app.utils.log import get_logger

LOG = get_logger(__name__)


def focused_control_is_password_field() -> bool:
    """True if the focused control or an ancestor is flagged as a password field."""
    import uiautomation as auto

    c = auto.GetFocusedControl()
    if c is None:
        return False
    cur = c
    for _ in range(10):
        if cur is None:
            break
        try:
            if bool(getattr(cur, "IsPassword", False)):
                return True
        except Exception:
            pass
        try:
            ct = (cur.ControlTypeName or "").lower()
            if "password" in ct:
                return True
        except Exception:
            pass
        try:
            cur = cur.GetParentControl()
        except Exception:
            break
    return False


def replace_substring_in_focused_element(
    old: str,
    new: str,
    *,
    match_last: bool = True,
    unique_match_only: bool = True,
) -> bool:
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
    n = cur.count(old)
    if unique_match_only and n != 1:
        LOG.info(
            "UIA: substring occurs %s times in focused field (unique_match_only) — skipping accessibility inject",
            n,
        )
        return False
    idx = cur.rfind(old) if match_last else cur.find(old)
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
