"""Shared expansion types and optional protocol contracts for pipeline extensions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class ExpansionLayer(str, Enum):
    """Resolved expansion tier / source (``ExpansionOutcome.layer`` stores ``.value``)."""

    EMPTY = "empty"
    L0_UNITS = "L0-units"
    L0_MATH = "L0-math"
    L0_DATE = "L0-date"
    L0_CURRENCY = "L0-currency"
    L1_SNIPPET_EXACT = "L1-snippet-exact"
    L2_SNIPPET_FUZZY = "L2-snippet-fuzzy"
    L2_SNIPPET_SEMANTIC = "L2-snippet-semantic"
    L2_CACHE = "L2-cache"


def l3_layer(provider_name: str) -> str:
    """Dynamic L3 label (provider-specific; not a single enum member)."""
    return f"L3-{(provider_name or '').strip()}"


@dataclass
class ExpansionOutcome:
    text: str
    layer: str
    ms: float


@runtime_checkable
class CacheTouchHandler(Protocol):
    """Called when a cache row is read so callers can promote high-hit entries, etc."""

    def __call__(self, cache_key_prompt: str, text: str, hit_count: int, source: str) -> None: ...
