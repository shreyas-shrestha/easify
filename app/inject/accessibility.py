"""Dispatch native accessibility text swap (macOS AX, Windows UIA)."""

from __future__ import annotations

import sys
from typing import Optional

from app.utils.log import get_logger

LOG = get_logger(__name__)


def accessibility_deps_hint() -> Optional[str]:
    """One-line install hint for the current OS, or None if unknown."""
    if sys.platform == "darwin":
        return "pip install 'easify[accessibility]' or pyobjc-framework-ApplicationServices"
    if sys.platform == "win32":
        return "pip install 'easify[accessibility]' or uiautomation"
    return None


def focused_field_appears_secure() -> bool:
    """Best-effort: password / secure text fields must not receive live fixes or expansions."""
    try:
        if sys.platform == "darwin":
            from app.inject.ax_macos import focused_element_is_password_field

            return focused_element_is_password_field()
        if sys.platform == "win32":
            from app.inject.uia_windows import focused_control_is_password_field

            return focused_control_is_password_field()
    except ImportError as e:
        LOG.debug("secure field probe unavailable: %s", e)
    except Exception as e:
        LOG.debug("secure field probe failed: %s", e)
    return False


def replace_in_focused_field(
    *,
    old: str,
    new: str,
    match_last: bool = True,
    unique_match_only: bool = True,
) -> bool:
    """
    Replace ``old`` with ``new`` in the focused text field (``match_last``: rfind vs find).
    ``unique_match_only``: require exactly one occurrence of ``old`` in the field (avoids wrong pane).
    Does not synthesize keys. Requires OS accessibility permissions (macOS) / UIAccess (Win).
    """
    old_s = old or ""
    if not old_s:
        return False
    try:
        if sys.platform == "darwin":
            from app.inject.ax_macos import replace_substring_in_focused_element

            return replace_substring_in_focused_element(
                old_s, new, match_last=match_last, unique_match_only=unique_match_only
            )
        if sys.platform == "win32":
            from app.inject.uia_windows import replace_substring_in_focused_element

            return replace_substring_in_focused_element(
                old_s, new, match_last=match_last, unique_match_only=unique_match_only
            )
    except ImportError as e:
        LOG.debug("accessibility inject: import error %s", e)
    except Exception as e:
        LOG.warning("accessibility inject failed: %s", e)
    return False
