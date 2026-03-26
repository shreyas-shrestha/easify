"""Dictionary autocorrect: word-boundary safe, O(1) lookups."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


def _split_punct(token: str) -> tuple[str, str, str]:
    i = 0
    j = len(token)
    while i < j and not token[i].isalnum():
        i += 1
    while j > i and not token[j - 1].isalnum():
        j -= 1
    return token[:i], token[i:j], token[j:]


class AutocorrectEngine:
    def __init__(self, path: Optional[Path]) -> None:
        self._path = path
        self._dict: dict[str, str] = {}
        self._keys_tuple: tuple[str, ...] = ()
        if path and path.is_file():
            self.reload()

    def reload(self) -> None:
        self._dict = {}
        self._keys_tuple = ()
        if not self._path or not self._path.is_file():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        raw = data.get("corrections", data) if isinstance(data, dict) else {}
        if not isinstance(raw, dict):
            return
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str):
                self._dict[k.lower()] = v
        self._keys_tuple = tuple(self._dict.keys())

    def lookup_word(self, word: str) -> Optional[str]:
        if not word:
            return None
        return self._dict.get(word.lower())

    def lookup_word_fuzzy(self, word: str, *, score_cutoff: int = 92) -> Optional[str]:
        """Map typo → correction when :func:`rapidfuzz.fuzz.ratio` to some dict key ≥ cutoff."""
        if not word or not self._dict:
            return None
        wl = word.lower()
        if wl in self._dict:
            return self._dict[wl]
        keys = self._keys_tuple
        if not keys:
            return None
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            return None
        lo = min(100, max(50, int(score_cutoff)))
        m = process.extractOne(wl, keys, scorer=fuzz.ratio, score_cutoff=lo)
        if m is None:
            return None
        key, _score, _idx = m
        return self._dict.get(key)

    def apply_to_phrase(self, phrase: str) -> str:
        """Layer-1 token fix for capture text (preserves spacing style roughly)."""
        if not self._dict or not phrase.strip():
            return phrase
        parts = re.split(r"(\s+)", phrase)
        out: list[str] = []
        for p in parts:
            if not p or p.isspace():
                out.append(p)
                continue
            lead, core, trail = _split_punct(p)
            if not core:
                out.append(p)
                continue
            repl = self._dict.get(core.lower())
            if repl is None:
                repl = self.lookup_word_fuzzy(core, score_cutoff=93)
            if repl is not None:
                if core.isupper():
                    repl = repl.upper()
                elif core[:1].isupper():
                    repl = repl[:1].upper() + repl[1:]
                out.append(f"{lead}{repl}{trail}")
            else:
                out.append(p)
        return "".join(out)
