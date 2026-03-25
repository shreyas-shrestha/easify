"""JSON snippets + optional fuzzy match (Levenshtein, no extra deps)."""

from __future__ import annotations

import json
import os
from typing import Optional


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins, delete, sub = cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def load_snippets(path: Optional[str]) -> dict[str, str]:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and "snippets" in data:
        raw = data["snippets"]
    else:
        raw = data
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k.strip().lower()] = v
    return out


def resolve_snippet(
    capture: str,
    snippets: dict[str, str],
    fuzzy_max: int,
) -> Optional[str]:
    if not snippets or not capture.strip():
        return None
    key = capture.strip().lower()
    if key in snippets:
        return snippets[key]
    if fuzzy_max <= 0:
        return None
    best: Optional[tuple[int, str]] = None
    for sk, replacement in snippets.items():
        d = _lev(key, sk)
        if d <= fuzzy_max and (best is None or d < best[0]):
            best = (d, replacement)
    return best[1] if best else None
