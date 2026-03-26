"""Compatibility re-export while migrating to :mod:`app.service`."""

from __future__ import annotations

from app.engine.service import ExpansionService

__all__ = ["ExpansionService"]
