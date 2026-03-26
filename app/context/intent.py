"""Cheap intent hints from capture text (sync heuristics)."""

from __future__ import annotations

import re

from app.context.input_context import IntentKind


def classify_intent_from_text(text: str) -> IntentKind:
    t = (text or "").strip().lower()
    if not t:
        return IntentKind.UNKNOWN
    if re.search(r"\b(cite|citations|sources|references|bibliography)\b", t):
        return IntentKind.NOTE
    if "?" in t or re.search(r"\b(what|who|when|where|why|how)\b", t):
        return IntentKind.QUESTION
    if re.search(r"\b(fix|convert|calculate|run|open|git )\b", t):
        return IntentKind.COMMAND
    if len(t.split()) <= 6 and not t.endswith("?"):
        return IntentKind.CHAT
    return IntentKind.UNKNOWN
