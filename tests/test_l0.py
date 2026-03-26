"""L0 deterministic compute (no network)."""

from __future__ import annotations

from app.engine.l0_compute import try_date_arithmetic, try_math, try_units


def test_l0_unit_inches_to_cm() -> None:
    out = try_units("5 inches to cm")
    assert out is not None
    assert "cm" in out.lower()


def test_l0_math_add() -> None:
    assert try_math("2 + 2") == "4"


def test_l0_math_modulo_not_percent() -> None:
    assert try_math("5 % 2") == "1"


def test_l0_math_literal_percent() -> None:
    out = try_math("25%")
    assert out == "0.25" or out.startswith("0.25")


def test_l0_date_today_plus_days() -> None:
    out = try_date_arithmetic("today + 1 days")
    assert out is not None
    assert len(out) == 10
