"""Startup probes — implementation lives in :mod:`app.cli.l3_probe`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.cli.l3_probe import startup_hint_messages

if TYPE_CHECKING:
    from app.config.settings import Settings


def startup_l3_hints(settings: "Settings") -> list[str]:
    return startup_hint_messages(settings)
