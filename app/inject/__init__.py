"""Optional OS accessibility text replacement (no synthetic keys when it works)."""

from app.inject.accessibility import accessibility_deps_hint, replace_in_focused_field

__all__ = ["replace_in_focused_field", "accessibility_deps_hint"]
