"""Nested behavior caps (derived from Settings + InputContext)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LivePolicyCaps:
    autocorrect: bool
    snippets: bool
    fuzzy: bool
    cache: bool
    cache_enrich: bool


@dataclass
class CapturePolicyCaps:
    snippets: bool
    semantic: bool
    cache: bool
    ai: bool
    citations: bool


@dataclass
class StylePolicy:
    tone: str
    format: str


@dataclass
class ThresholdPolicy:
    min_live_confidence: float
    fuzzy_ratio_floor: int
    max_replace_len: int


@dataclass
class BehaviorPolicy:
    live: LivePolicyCaps
    capture: CapturePolicyCaps
    style: StylePolicy
    thresholds: ThresholdPolicy
