"""Shared expansion types and optional protocol contracts for pipeline extensions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ExpansionOutcome:
    text: str
    layer: str
    ms: float


@runtime_checkable
class CacheTouchHandler(Protocol):
    """Called when a cache row is read so callers can promote high-hit entries, etc."""

    def __call__(self, cache_key_prompt: str, text: str, hit_count: int, source: str) -> None: ...
