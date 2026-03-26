"""Map frontmost app labels to AppKind (heuristic, lightweight)."""

from __future__ import annotations

from app.context.input_context import AppKind


def classify_app_kind(raw: str) -> AppKind:
    s = (raw or "").lower()
    if not s or s == "unknown":
        return AppKind.UNKNOWN

    if any(x in s for x in ("terminal", "iterm", "kitty", "ghostty", "alacritty", "wezterm", "hyper")):
        return AppKind.TERMINAL
    if any(x in s for x in ("code", "cursor", "nvim", "vim", "emacs", "xcode", "pycharm", "intellij", "android studio")):
        return AppKind.IDE
    if any(x in s for x in ("chrome", "firefox", "safari", "arc", "brave", "edge", "vivaldi", "opera")):
        return AppKind.BROWSER
    if any(x in s for x in ("slack", "discord", "messages", "teams", "zoom", "telegram")):
        return AppKind.CHAT
    if any(x in s for x in ("notes", "obsidian", "notion", "bear", "ulysses")):
        return AppKind.NOTES
    if any(x in s for x in ("mail", "outlook", "gmail")):
        return AppKind.EMAIL
    return AppKind.OTHER
