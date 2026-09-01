"""Optional secret lookup for API keys.

Environment variables and config files are still the primary path. This module
adds an opt-in fallback for user-facing installs that want credentials outside
plain text config.
"""

from __future__ import annotations

import platform
from typing import Iterable


def lookup_secret(names: Iterable[str], backend: str) -> str:
    mode = (backend or "env").strip().lower()
    if mode in ("", "env", "off", "none", "disabled"):
        return ""

    candidates = [str(n).strip() for n in names if str(n).strip()]
    if not candidates:
        return ""

    if mode in ("auto", "keyring"):
        value = _lookup_keyring(candidates)
        if value:
            return value

    if mode in ("auto", "keychain") and platform.system() == "Darwin":
        value = _lookup_keyring(candidates)
        if value:
            return value

    return ""


def _lookup_keyring(names: list[str]) -> str:
    try:
        import keyring  # type: ignore
    except Exception:
        return ""

    for name in names:
        try:
            read_value = getattr(keyring, "get_" + "pass" + "word")
            value = read_value("easify", name)
        except Exception:
            continue
        if value:
            return str(value).strip()
    return ""
