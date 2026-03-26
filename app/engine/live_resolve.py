"""
Deterministic live resolution (word + optional multi-word phrase).

Order matches product contract:
  guards → autocorrect → snippet exact → snippet fuzzy → cache → none
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Optional

from app.engine.guards import is_safe_phrase_tokens, is_safe_word, preserve_case, ratio_exceeds
from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.autocorrect.engine import AutocorrectEngine
    from app.cache.store import SqliteExpansionCache
    from app.snippets.engine import SnippetEngine

LOG = get_logger(__name__)

_LIVE_CACHE_TAG = "easify:live_word:v1"


def live_cache_prompt(word_or_phrase: str) -> str:
    s = re.sub(r"\s+", " ", word_or_phrase.strip().lower())
    return f"{_LIVE_CACHE_TAG}\n{s}"


def _log_perf(stage_ms: Optional[dict[str, float]], name: str, t0: float) -> None:
    if stage_ms is not None:
        stage_ms[name] = (time.perf_counter() - t0) * 1000.0


def resolve_live_word(
    word: str,
    *,
    autocorrect: "AutocorrectEngine",
    snippets: "SnippetEngine",
    cache: "SqliteExpansionCache",
    model: str,
    min_word_len: int = 3,
    fuzzy_enabled: bool = True,
    cache_enabled: bool = True,
    fuzzy_threshold: int = 92,
    stage_ms: Optional[dict[str, float]] = None,
) -> Optional[str]:
    t_all = time.perf_counter()
    if not is_safe_word(word, min_len=min_word_len):
        _log_perf(stage_ms, "guards", t_all)
        return None
    _log_perf(stage_ms, "guards", t_all)

    wl = word.lower()
    t0 = time.perf_counter()
    r = autocorrect.lookup_word(wl)
    if r is None:
        ac_cut = min(100, max(50, int(fuzzy_threshold) + 1))
        r = autocorrect.lookup_word_fuzzy(wl, score_cutoff=ac_cut)
    _log_perf(stage_ms, "autocorrect", t0)
    if r is not None:
        out = preserve_case(word, r)
        if out != word:
            return out

    t0 = time.perf_counter()
    hit = snippets.resolve_exact(wl)
    _log_perf(stage_ms, "snippet_exact", t0)
    if hit is not None and hit.value != word:
        if "\n" in hit.value or len(hit.value) > 2000:
            LOG.debug("skip huge snippet for live word")
            return None
        return hit.value

    if fuzzy_enabled:
        t0 = time.perf_counter()
        cutoff = min(100, max(50, int(fuzzy_threshold) + 1))
        fz = snippets.resolve_fuzzy_ratio(wl, cutoff)
        _log_perf(stage_ms, "snippet_fuzzy", t0)
        if fz is not None and fz.value != word:
            if not ratio_exceeds(wl, fz.key, float(fuzzy_threshold)):
                return None
            if "\n" in fz.value or len(fz.value) > 2000:
                return None
            return fz.value

    if cache_enabled:
        t0 = time.perf_counter()
        ck = live_cache_prompt(wl)
        cached = cache.get(model, ck)
        _log_perf(stage_ms, "cache", t0)
        if cached and cached.strip() and cached.strip() != word:
            return cached.strip()

    return None


def resolve_live_phrase(
    phrase: str,
    *,
    autocorrect: "AutocorrectEngine",
    snippets: "SnippetEngine",
    cache: "SqliteExpansionCache",
    model: str,
    min_word_len: int = 3,
    fuzzy_enabled: bool = True,
    cache_enabled: bool = True,
    fuzzy_threshold: int = 92,
    stage_ms: Optional[dict[str, float]] = None,
) -> Optional[str]:
    """
    Multi-word deterministic path (phrase buffer). Same stage order; autocorrect is per-token dict lookup.
    """
    t_all = time.perf_counter()
    words = phrase.split()
    if not is_safe_phrase_tokens(words, min_len=min_word_len):
        _log_perf(stage_ms, "phrase_guards", t_all)
        return None
    _log_perf(stage_ms, "phrase_guards", t_all)

    t0 = time.perf_counter()
    corrected_tokens: list[str] = []
    changed = False
    for w in words:
        lw = w.lower()
        r = autocorrect.lookup_word(lw)
        if r is None:
            ac_cut = min(100, max(50, int(fuzzy_threshold) + 1))
            r = autocorrect.lookup_word_fuzzy(lw, score_cutoff=ac_cut)
        if r is not None:
            nw = preserve_case(w, r)
            corrected_tokens.append(nw)
            if nw != w:
                changed = True
        else:
            corrected_tokens.append(w)
    _log_perf(stage_ms, "phrase_autocorrect", t0)
    corrected = " ".join(corrected_tokens)
    if changed and corrected != phrase:
        return corrected

    pl = re.sub(r"\s+", " ", phrase.lower().strip())

    t0 = time.perf_counter()
    hit = snippets.resolve_exact(pl)
    _log_perf(stage_ms, "phrase_snippet_exact", t0)
    if hit is not None and hit.value != phrase:
        if "\n" in hit.value or len(hit.value) > 2000:
            return None
        return hit.value

    if fuzzy_enabled:
        t0 = time.perf_counter()
        cutoff = min(100, max(50, int(fuzzy_threshold) + 1))
        fz = snippets.resolve_fuzzy_ratio(pl, cutoff)
        _log_perf(stage_ms, "phrase_snippet_fuzzy", t0)
        if fz is not None and fz.value != phrase:
            if not ratio_exceeds(pl, fz.key, float(fuzzy_threshold)):
                return None
            if "\n" in fz.value or len(fz.value) > 2000:
                return None
            return fz.value

    if cache_enabled:
        t0 = time.perf_counter()
        ck = live_cache_prompt(pl)
        cached = cache.get(model, ck)
        _log_perf(stage_ms, "phrase_cache", t0)
        if cached and cached.strip() and cached.strip() != phrase:
            return cached.strip()

    return None
