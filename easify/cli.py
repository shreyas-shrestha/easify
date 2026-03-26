"""Backward-compatible entry: prefer `app.main:main`."""

from app.main import main

__all__ = ["main"]
