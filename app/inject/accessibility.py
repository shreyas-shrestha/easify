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


def replace_in_focused_field(*, old: str, new: str) -> bool:
    """
    Replace the last occurrence of ``old`` in the focused text field's value.
    Does not synthesize keys. Requires OS accessibility permissions (macOS) / UIAccess (Win).
    """
    old_s = (old or "").strip()
    if not old_s:
        return False
    try:
        if sys.platform == "darwin":
            from app.inject.ax_macos import replace_substring_in_focused_element

            return replace_substring_in_focused_element(old_s, new)
        if sys.platform == "win32":
            from app.inject.uia_windows import replace_substring_in_focused_element

            return replace_substring_in_focused_element(old_s, new)
    except ImportError as e:
        LOG.debug("accessibility inject: import error %s", e)
    except Exception as e:
        LOG.warning("accessibility inject failed: %s", e)
    return False
