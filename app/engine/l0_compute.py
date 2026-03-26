"""L0 deterministic layer: pint units, safe math, simple date arithmetic, FX (Frankfurter)."""

from __future__ import annotations

import ast
import json
import operator
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

_RE_UNIT = re.compile(
    r"^\s*(?:convert\s+)?(?P<qty>[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)\s+"
    r"(?P<fu>[^\s]+)\s+(?:to|into|in)\s+(?P<tu>[^\s]+)\s*$",
    re.I,
)
_RE_FX = re.compile(
    r"^\s*(?:convert\s+)?(?P<amt>[-+]?(?:\d*\.\d+|\d+))\s+"
    r"(?P<fc>[A-Za-z]{3})\s+(?:to|into)\s+(?P<tc>[A-Za-z]{3})\s*$",
    re.I,
)
_RE_DATE_ADD = re.compile(
    r"^\s*(?P<base>today|yesterday|tomorrow|\d{4}-\d{2}-\d{2})\s*\+\s*"
    r"(?P<n>\d+)\s+(?P<u>days?|weeks?|hours?)\s*$",
    re.I,
)

_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def try_units(s: str) -> Optional[str]:
    m = _RE_UNIT.match(s.strip())
    if not m:
        return None
    try:
        import pint

        ureg = pint.UnitRegistry()
        q = float(m.group("qty")) * ureg(m.group("fu"))
        out = q.to(ureg(m.group("tu")))
        mag = out.magnitude
        if isinstance(mag, float):
            if abs(mag - round(mag)) < 1e-9 * max(1.0, abs(mag)):
                mag = int(round(mag))
            else:
                mag = float(f"{mag:.12g}")
        unit_str = f"{out.units:~P}"
        return f"{mag} {unit_str}"
    except Exception:
        return None


def _eval_num(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ValueError("forbidden")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
        return float(_UNOPS[type(node.op)](_eval_num(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return float(_BINOPS[type(node.op)](_eval_num(node.left), _eval_num(node.right)))
    raise ValueError("forbidden")


def try_math(s: str) -> Optional[str]:
    raw = s.strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    if not raw or len(raw) > 200:
        return None
    # Literal percent of a single number: "25%" → 0.25 (not "5 % 2" modulo).
    pct = re.match(
        r"^\s*([-+]?(?:\d*\.\d+|\d+))\s*%+\s*$",
        raw,
    )
    if pct and "%" not in pct.group(1):
        try:
            v = float(pct.group(1)) / 100.0
            if abs(v - round(v)) < 1e-12:
                return str(int(round(v)))
            s_out = f"{v:.12g}"
            return s_out.rstrip("0").rstrip(".") or "0"
        except ValueError:
            return None
    if re.search(r"[a-zA-Z_]", raw):
        return None
    try:
        tree = ast.parse(raw, mode="eval")
        v = _eval_num(tree.body)
        if abs(v - round(v)) < 1e-12:
            return str(int(round(v)))
        s_out = f"{v:.12g}"
        if "e" in s_out.lower():
            return s_out
        return s_out.rstrip("0").rstrip(".") or "0"
    except Exception:
        return None


def try_date_arithmetic(s: str) -> Optional[str]:
    m = _RE_DATE_ADD.match(s.strip())
    if not m:
        return None
    base = m.group("base").lower()
    n = int(m.group("n"))
    unit = m.group("u").lower()
    if base == "today":
        d = date.today()
    elif base == "yesterday":
        d = date.today() - timedelta(days=1)
    elif base == "tomorrow":
        d = date.today() + timedelta(days=1)
    else:
        d = date.fromisoformat(base)
    if unit.startswith("day"):
        d2 = d + timedelta(days=n)
        return d2.isoformat()
    if unit.startswith("week"):
        d2 = d + timedelta(weeks=n)
        return d2.isoformat()
    if unit.startswith("hour"):
        dt = datetime.combine(d, datetime.min.time()) + timedelta(hours=n)
        return dt.isoformat(timespec="minutes")
    return None


@dataclass
class FxRateCache:
    """Caches Frankfurter JSON on disk; refresh after ttl_sec."""

    path: Path
    ttl_sec: int = 86_400
    _mem: Dict[str, Any] = field(default_factory=dict)
    _loaded_at: float = field(default=0.0)

    def __post_init__(self) -> None:
        import asyncio

        self._conv_lock = asyncio.Lock()

    def _load_file(self) -> None:
        if not self.path.is_file():
            self._mem = {}
            return
        try:
            self._mem = json.loads(self.path.read_text(encoding="utf-8"))
            self._loaded_at = time.time()
        except (OSError, json.JSONDecodeError, TypeError):
            self._mem = {}

    async def convert(self, client: httpx.AsyncClient, amount: float, frm: str, to: str) -> Optional[str]:
        async with self._conv_lock:
            frm_u, to_u = frm.upper(), to.upper()
            if frm_u == to_u:
                return f"{amount:g} {to_u}"
            now = time.time()
            if now - self._loaded_at > self.ttl_sec or not self._mem:
                self._load_file()
            base = str(self._mem.get("base", "")).upper()
            rates = self._mem.get("rates") if isinstance(self._mem.get("rates"), dict) else {}
            if now - self._loaded_at <= self.ttl_sec and base == frm_u and to_u in rates:
                rate = float(rates[to_u])
                return f"{amount * rate:.6g} {to_u}"
            url = f"https://api.frankfurter.app/latest?from={frm_u}&to={to_u}"
            try:
                r = await client.get(url, timeout=15.0)
                r.raise_for_status()
                data = r.json()
                rates_new = data.get("rates") or {}
                if to_u not in rates_new:
                    return None
                rate = float(rates_new[to_u])
                out = amount * rate
                self._mem = {"base": frm_u, "rates": rates_new, "date": data.get("date")}
                self._loaded_at = time.time()
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_text(json.dumps(self._mem), encoding="utf-8")
                except OSError:
                    pass
                return f"{out:.6g} {to_u}"
            except Exception:
                return None


async def try_l0_async(capture: str, http: httpx.AsyncClient, fx: FxRateCache) -> Optional[tuple[str, str]]:
    s = capture.strip()
    if not s:
        return None
    u = try_units(s)
    if u:
        return u, "L0-units"
    m = try_math(s)
    if m is not None:
        return m, "L0-math"
    d = try_date_arithmetic(s)
    if d:
        return d, "L0-date"
    fxm = _RE_FX.match(s)
    if fxm:
        out = await fx.convert(http, float(fxm.group("amt")), fxm.group("fc"), fxm.group("tc"))
        if out:
            return out, "L0-currency"
    return None
