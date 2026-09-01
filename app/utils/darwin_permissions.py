"""macOS permission preflights for global keyboard hooks."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PermissionPreflight:
    ok: bool
    message: str = ""


def preflight_input_monitoring() -> PermissionPreflight:
    if platform.system() != "Darwin":
        return PermissionPreflight(True)

    hiservices = _import_hiservices()
    ax_check = getattr(hiservices, "AXIsProcessTrusted", None) if hiservices is not None else None
    if ax_check is not None:
        try:
            ax_allowed = bool(ax_check())
        except Exception:
            ax_allowed = True
        if not ax_allowed:
            return PermissionPreflight(False, _permission_message())

    quartz = _import_quartz()
    checks = []
    for name in ("CGPreflightListenEventAccess", "CGPreflightPostEventAccess"):
        check = getattr(quartz, name, None) if quartz is not None else None
        if check is not None:
            checks.append(check)

    if not checks:
        return PermissionPreflight(True)

    try:
        allowed = all(bool(check()) for check in checks)
    except Exception:
        return PermissionPreflight(True)

    if allowed:
        return PermissionPreflight(True)

    return PermissionPreflight(False, _permission_message())


def _import_quartz() -> Any:
    try:
        import Quartz  # type: ignore
    except Exception:
        return None
    return Quartz


def _import_hiservices() -> Any:
    try:
        import HIServices  # type: ignore
    except Exception:
        return None
    return HIServices


def _permission_message() -> str:
    return (
        "macOS Input Monitoring/Accessibility is not trusted for this Python process. "
        "Grant Input Monitoring and Accessibility to the terminal, Conductor, "
        "or Python process launching Easify, then start Easify again."
    )
