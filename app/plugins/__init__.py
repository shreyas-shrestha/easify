"""
Reserved plugin surface for third-party expanders and corpora.

Example future use: `PluginRegistry.register("acme", AcmeCorpusResolver())`
"""

from __future__ import annotations

from typing import Any, Callable, List


class PluginRegistry:
    _hooks: List[Callable[..., Any]] = []

    @classmethod
    def register(cls, fn: Callable[..., Any]) -> None:
        cls._hooks.append(fn)

    @classmethod
    def all(cls) -> List[Callable[..., Any]]:
        return list(cls._hooks)
