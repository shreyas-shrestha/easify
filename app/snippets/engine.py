"""Layer 1 (exact) + Layer 2 (fuzzy) snippet resolution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process


def _focus_blob(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


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

    @property
    def content_version(self) -> float:
        return float(self._mtime)

    def iter_snippets(self) -> dict[str, str]:
        self.maybe_reload()
        return dict(self._store)

    def get_value(self, key: str) -> Optional[str]:
        self.maybe_reload()
        return self._store.get(key.strip().lower())

    def key_visible_for_focus(self, key: str, focus_raw: str, *, lenient: bool) -> bool:
        """Keys with `namespace:rest` only match when focused app name contains `namespace`."""
        k = key.strip().lower()
        if ":" not in k:
            return True
        ns = k.split(":", 1)[0].strip().lower()
        if not ns:
            return True
        blob = _focus_blob(focus_raw)
        if not blob or focus_raw.strip().lower() in ("", "unknown"):
            return bool(lenient)
        if ns in blob.split():
            return True
        return ns in blob or blob.startswith(ns + " ") or (" " + ns + " ") in (" " + blob + " ")

    def maybe_reload(self) -> None:
        """Hot-reload if any file changed (cheap stat)."""
        for path in self._paths:
            if path.is_file() and path.stat().st_mtime > self._mtime:
                self.reload()
                return

    def _visible_keys(self, focused_app: str, namespace_lenient: bool) -> list[str]:
        return [k for k in self._keys_list if self.key_visible_for_focus(k, focused_app, lenient=namespace_lenient)]

    def resolve_exact(
        self, query: str, *, focused_app: str = "", namespace_lenient: bool = False
    ) -> Optional[SnippetHit]:
        self.maybe_reload()
        k = query.strip().lower()
        if not k:
            return None
        if not self.key_visible_for_focus(k, focused_app, lenient=namespace_lenient):
            return None
        v = self._store.get(k)
        if v is None:
            return None
        return SnippetHit(layer=1, key=k, value=v, score=100.0)

    def resolve_fuzzy(
        self, query: str, *, focused_app: str = "", namespace_lenient: bool = False
    ) -> Optional[SnippetHit]:
        self.maybe_reload()
        k = query.strip().lower()
        keys = self._visible_keys(focused_app, namespace_lenient)
        if not k or not keys:
            return None
        match = process.extractOne(
            k,
            keys,
            scorer=fuzz.WRatio,
            score_cutoff=self._fuzzy_cutoff,
        )
        if match is None:
            return None
        key, score, _ = match
        return SnippetHit(layer=2, key=key, value=self._store[key], score=float(score))

    def resolve_fuzzy_ratio(
        self,
        query: str,
        score_cutoff: int,
        *,
        focused_app: str = "",
        namespace_lenient: bool = True,
    ) -> Optional[SnippetHit]:
        """Live-word path: stricter `fuzz.ratio` cutoff (e.g. > 92 → cutoff 93)."""
        self.maybe_reload()
        k = query.strip().lower()
        keys = self._visible_keys(focused_app, namespace_lenient)
        if not k or not keys:
            return None
        co = max(50, min(100, int(score_cutoff)))
        match = process.extractOne(
            k,
            keys,
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
