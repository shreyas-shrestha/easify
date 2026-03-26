"""Skip live-cache enrich for ultra-common words (saves pointless LLM round-trips)."""

from __future__ import annotations

from pathlib import Path
from typing import FrozenSet, Optional

_BLOCK: Optional[FrozenSet[str]] = None


def _bundled_blocklist_path() -> Path:
    return Path(__file__).resolve().parent.parent / "bundled" / "live_enrich_blocklist.txt"


def live_enrich_blocked_words() -> FrozenSet[str]:
    global _BLOCK
    if _BLOCK is not None:
        return _BLOCK
    words: set[str] = set()
    p = _bundled_blocklist_path()
    if p.is_file():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                w = line.split("#", 1)[0].strip().lower()
                if w:
                    words.add(w)
        except OSError:
            pass
    _BLOCK = frozenset(words)
    return _BLOCK


def should_skip_live_enrich_token(word: str) -> bool:
    w = word.strip().lower()
    if len(w) < 3:
        return True
    return w in live_enrich_blocked_words()
