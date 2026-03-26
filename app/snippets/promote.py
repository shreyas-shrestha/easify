"""Promote high-traffic cache rows into user snippets.json (Phase 3)."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any, MutableMapping, Set

from app.utils.log import get_logger

LOG = get_logger(__name__)

_PROMOTE_LOCK = threading.Lock()


def user_line_from_cache_prompt(cache_prompt: str) -> str:
    lines = (cache_prompt or "").strip().split("\n")
    return lines[-1].strip() if lines else (cache_prompt or "")[:160]


def promote_slug(user_line: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", user_line.lower()).strip("-")[:48]
    return s or "cache"


def promote_key_for_line(user_line: str) -> str:
    return f"promoted-{promote_slug(user_line)}"


def _dedupe_path(config_dir: Path) -> Path:
    return config_dir / "promoted_snippets.txt"


def _load_promoted_set(path: Path) -> Set[str]:
    if not path.is_file():
        return set()
    out: Set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            h = line.strip()
            if h:
                out.add(h)
    except OSError:
        pass
    return out


def _remember_promoted(path: Path, token: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(token + "\n")
    except OSError as e:
        LOG.debug("promote dedupe write: %s", e)


def count_promoted_snippets(inner: dict[Any, Any]) -> int:
    return sum(
        1
        for k in inner
        if isinstance(k, str) and k.strip().lower().startswith("promoted-")
    )


def _load_snippets_inner(user_snippets: Path) -> MutableMapping[str, Any]:
    """Single read of user snippets dict (values are snippet strings)."""
    if not user_snippets.is_file():
        return {}
    try:
        raw_obj = json.loads(user_snippets.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw_obj, dict) and "snippets" in raw_obj:
        inner = raw_obj["snippets"]
        if isinstance(inner, dict):
            return inner
        return {}
    if isinstance(raw_obj, dict):
        return raw_obj
    return {}


def _atomic_write_snippets(user_snippets: Path, inner: MutableMapping[str, Any]) -> None:
    out_doc: dict[str, object] = {"snippets": dict(inner)}
    user_snippets.parent.mkdir(parents=True, exist_ok=True)
    tmp = user_snippets.with_suffix(".tmp")
    tmp.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(user_snippets)


def append_snippet_to_user_file(user_snippets: Path, key: str, value: str) -> bool:
    """Merge key into JSON file. Returns True if a new key was written."""
    inner = _load_snippets_inner(user_snippets)
    kk = key.strip().lower()
    if not kk:
        return False
    if kk in inner and isinstance(inner[kk], str):
        return False
    inner[kk] = value
    _atomic_write_snippets(user_snippets, inner)
    return True


def maybe_promote_cache_hit(
    *,
    user_snippets: Path,
    config_dir: Path,
    cache_prompt: str,
    response: str,
    hit_count: int,
    source: str,
    min_hits: int,
    allowed_sources: frozenset[str],
    max_promoted_keys: int = 0,
) -> bool:
    if min_hits <= 0 or hit_count < min_hits:
        return False
    src = (source or "").strip().lower()
    if src not in allowed_sources:
        return False
    line = user_line_from_cache_prompt(cache_prompt)
    key = promote_key_for_line(line)
    token = hashlib.sha256(f"{key}\x00{cache_prompt}\x00{response}".encode("utf-8")).hexdigest()
    dedupe = _dedupe_path(config_dir)
    # Lock only coordinates concurrent promoters in this process; another process (snippet UI) may
    # still race — we read once and write atomically to minimize the window.
    with _PROMOTE_LOCK:
        inner = _load_snippets_inner(user_snippets)
        if max_promoted_keys > 0 and count_promoted_snippets(inner) >= max_promoted_keys:
            LOG.warning(
                "cache promotion skipped: promoted snippet cap reached (%s)",
                max_promoted_keys,
            )
            return False
        seen = _load_promoted_set(dedupe)
        if token in seen:
            return False
        kk = key.strip().lower()
        if not kk:
            return False
        if kk in inner and isinstance(inner[kk], str):
            return False
        inner[kk] = response
        _atomic_write_snippets(user_snippets, inner)
        _remember_promoted(dedupe, token)
    LOG.info("promoted cache hit → snippet %r (hits=%s source=%s)", key, hit_count, src)
    return True
