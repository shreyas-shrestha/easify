"""Layer 1 (exact) + Layer 2 (fuzzy) snippet resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process


@dataclass
class SnippetHit:
    layer: int
    key: str
    value: str
    score: float


class SnippetEngine:
    def __init__(self, paths: list[Path], fuzzy_score_cutoff: int = 82, max_keys: int = 5000) -> None:
        self._fuzzy_cutoff = max(50, min(100, fuzzy_score_cutoff))
        self._max_keys = max_keys
        self._store: dict[str, str] = {}
        self._mtime = 0.0
        self._paths = [p for p in paths if p]
        self.reload()

    def reload(self) -> None:
        merged: dict[str, str] = {}
        latest_m = 0.0
        for path in self._paths:
            if not path.is_file():
                continue
            try:
                latest_m = max(latest_m, path.stat().st_mtime)
                merged.update(_load_snippets_file(path))
            except OSError:
                continue
        self._store = merged
        self._mtime = latest_m
        self._keys_list = list(self._store.keys())[: self._max_keys]

    def maybe_reload(self) -> None:
        """Hot-reload if any file changed (cheap stat)."""
        for path in self._paths:
            if path.is_file() and path.stat().st_mtime > self._mtime:
                self.reload()
                return

    def resolve_exact(self, query: str) -> Optional[SnippetHit]:
        self.maybe_reload()
        k = query.strip().lower()
        if not k:
            return None
        v = self._store.get(k)
        if v is None:
            return None
        return SnippetHit(layer=1, key=k, value=v, score=100.0)

    def resolve_fuzzy(self, query: str) -> Optional[SnippetHit]:
        self.maybe_reload()
        k = query.strip().lower()
        if not k or not self._keys_list:
            return None
        match = process.extractOne(
            k,
            self._keys_list,
            scorer=fuzz.WRatio,
            score_cutoff=self._fuzzy_cutoff,
        )
        if match is None:
            return None
        key, score, _ = match
        return SnippetHit(layer=2, key=key, value=self._store[key], score=float(score))

    def resolve_fuzzy_ratio(self, query: str, score_cutoff: int) -> Optional[SnippetHit]:
        """Live-word path: stricter `fuzz.ratio` cutoff (e.g. > 92 → cutoff 93)."""
        self.maybe_reload()
        k = query.strip().lower()
        if not k or not self._keys_list:
            return None
        co = max(50, min(100, int(score_cutoff)))
        match = process.extractOne(
            k,
            self._keys_list,
            scorer=fuzz.ratio,
            score_cutoff=co,
        )
        if match is None:
            return None
        key, score, _ = match
        return SnippetHit(layer=2, key=key, value=self._store[key], score=float(score))


def _load_snippets_file(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "snippets" in data:
        raw = data["snippets"]
    else:
        raw = data
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for kk, vv in raw.items():
        if isinstance(kk, str) and isinstance(vv, str):
            out[kk.strip().lower()] = vv
    return out
