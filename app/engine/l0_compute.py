"""L0 deterministic layer: pint units, safe math, simple date arithmetic, FX (Frankfurter)."""

from __future__ import annotations

import ast
import json
import operator
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

_UREG = None
_UREG_LOCK = threading.Lock()


def _get_ureg():
    global _UREG
    if _UREG is not None:
        return _UREG
    with _UREG_LOCK:
        if _UREG is None:
            import pint as _pint

            _UREG = _pint.UnitRegistry()
    return _UREG


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
_CURRENCY_ALIASES: dict[str, str] = {
    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "eur": "EUR",
    "pound": "GBP",
    "pounds": "GBP",
    "sterling": "GBP",
    "gbp": "GBP",
    "yen": "JPY",
    "jpy": "JPY",
    "yuan": "CNY",
    "renminbi": "CNY",
    "cny": "CNY",
    "franc": "CHF",
    "francs": "CHF",
    "chf": "CHF",
    "rupee": "INR",
    "rupees": "INR",
    "inr": "INR",
    "ruble": "RUB",
    "rubles": "RUB",
    "rub": "RUB",
    "won": "KRW",
    "krw": "KRW",
    "real": "BRL",
    "reais": "BRL",
    "brl": "BRL",
    "peso": "MXN",
    "pesos": "MXN",
    "mxn": "MXN",
    "krona": "SEK",
    "kronor": "SEK",
    "sek": "SEK",
    "krone": "NOK",
    "nok": "NOK",
    "dollar australian": "AUD",
    "aud": "AUD",
    "dollar canadian": "CAD",
    "cad": "CAD",
    "dirham": "AED",
    "aed": "AED",
    "lira": "TRY",
    "try": "TRY",
    "zloty": "PLN",
    "pln": "PLN",
    "forint": "HUF",
    "huf": "HUF",
    "baht": "THB",
    "thb": "THB",
    "ringgit": "MYR",
    "myr": "MYR",
    "shekel": "ILS",
    "shekels": "ILS",
    "ils": "ILS",
    "us dollar": "USD",
    "us dollars": "USD",
    "russian ruble": "RUB",
    "russian rubles": "RUB",
    "russian": "RUB",
    "russia": "RUB",
}


def _sanitize_l0_input(s: str) -> str:
    """Normalize Unicode so Notes/Web $ variants still match FX patterns."""
    t = unicodedata.normalize("NFKC", s).strip()
    t = t.replace("\uFF04", "$").replace("\uFE69", "$")
    return t


_RE_INLINE_CONV = re.compile(
    r"(?P<chunk>\d+(?:\.\d+)?\s+"
    r"(?:[A-Za-z]+\s+){0,3}[A-Za-z]+\s+"
    r"(?:to|into)\s+"
    r"(?:[A-Za-z]+\s+){0,3}[A-Za-z]+)",
    re.I,
)


def _resolve_currency_token(phrase: str) -> str:
    p = " ".join(phrase.strip().split())
    if not p:
        return ""
    pl = p.lower()
    if pl in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[pl]
    words = pl.split()
    if len(words) >= 2:
        tail2 = " ".join(words[-2:])
        if tail2 in _CURRENCY_ALIASES:
            return _CURRENCY_ALIASES[tail2]
    if words:
        last = words[-1]
        lk = last.lower().rstrip("s")
        if lk in _CURRENCY_ALIASES:
            return _CURRENCY_ALIASES[lk]
        if last.lower() in _CURRENCY_ALIASES:
            return _CURRENCY_ALIASES[last.lower()]
    return ""


def _maybe_iso_code(phrase: str) -> str:
    """3-letter ISO if the phrase is exactly letters (e.g. RUB, USD)."""
    p = phrase.strip()
    if len(p) == 3 and p.isalpha():
        return p.upper()
    return ""


def _normalize_currency_aliases(s: str) -> str:
    """Replace natural language currency names with ISO codes for FX regex."""
    # Shorthand: "$10 to rupees" → "10 USD to INR"
    m_d = re.match(
        r"^\s*(?:convert\s+)?\$\s*(?P<amt>[-+]?(?:\d*\.\d+|\d+))\s+(?:to|into)\s+(?P<to_raw>.+?)\s*$",
        s.strip(),
        re.I,
    )
    if m_d:
        amt_str = m_d.group("amt")
        to_raw = m_d.group("to_raw").strip()
        tc = _resolve_currency_token(to_raw) or _maybe_iso_code(to_raw)
        if len(tc) == 3:
            return f"{amt_str} USD to {tc}"

    m = re.match(
        r"^\s*(?:convert\s+)?(?P<amt>[-+]?(?:\d*\.\d+|\d+))\s+"
        r"(?P<from_raw>.+?)\s+(?:to|into)\s+(?P<to_raw>.+?)\s*$",
        s.strip(),
        re.I,
    )
    if not m:
        return s
    amt_str = m.group("amt")
    from_raw = m.group("from_raw").strip()
    to_raw = m.group("to_raw").strip()
    fc = _resolve_currency_token(from_raw)
    tc = _resolve_currency_token(to_raw)
    if not fc and not tc:
        return s
    fc = fc or _maybe_iso_code(from_raw)
    tc = tc or _maybe_iso_code(to_raw)
    if len(fc) != 3 or len(tc) != 3:
        return s
    return f"{amt_str} {fc} to {tc}"


def _l0_query_candidates(s: str) -> list[str]:
    """Try conversions on full text and likely sub-phrases (prose + conversion in one line)."""
    t = s.strip()
    if not t:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        x = x.strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)

    add(t)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if lines:
        add(lines[-1])
    for m in _RE_INLINE_CONV.finditer(t):
        add(m.group("chunk"))
    return out
_RE_DATE_ADD = re.compile(
    r"^\s*(?P<base>today|yesterday|tomorrow|\d{4}-\d{2}-\d{2})\s*\+\s*"
    r"(?P<n>\d+)\s+(?P<u>days?|weeks?|hours?)\s*$",
    re.I,
)
_RE_DATE_IN = re.compile(
    r"^\s*in\s+(?P<n>\d+)\s+(?P<u>days?|weeks?)\s*$",
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
        ureg = _get_ureg()
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
    sin = _RE_DATE_IN.match(s.strip())
    if sin:
        n = int(sin.group("n"))
        unit = sin.group("u").lower()
        d = date.today()
        if unit.startswith("day"):
            return (d + timedelta(days=n)).isoformat()
        if unit.startswith("week"):
            return (d + timedelta(weeks=n)).isoformat()
        return None
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
    """Caches FX JSON on disk; Frankfurter first, then open.er-api.com fallback."""

    path: Path
    ttl_sec: int = 86_400
    _mem: Dict[str, Any] = field(default_factory=dict)
    _loaded_at: float = field(default=0.0)

    def __post_init__(self) -> None:
        self._conv_lock = threading.Lock()

    def _load_file(self) -> None:
        if not self.path.is_file():
            self._mem = {}
            return
        try:
            self._mem = json.loads(self.path.read_text(encoding="utf-8"))
            self._loaded_at = time.time()
        except (OSError, json.JSONDecodeError, TypeError):
            self._mem = {}

    async def _convert_open_er_api(
        self, client: httpx.AsyncClient, amount: float, frm_u: str, to_u: str
    ) -> Optional[tuple[float, dict[str, Any]]]:
        """Returns (converted_amount, meta) or None. Uses /v6/latest/{base} semantics."""
        url = f"https://open.er-api.com/v6/latest/{frm_u}"
        try:
            r = await client.get(url, timeout=12.0)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None
        if (data or {}).get("result") != "success":
            return None
        rates = data.get("rates") if isinstance(data.get("rates"), dict) else {}
        if to_u not in rates:
            return None
        try:
            rate = float(rates[to_u])
        except (TypeError, ValueError):
            return None
        return amount * rate, {
            "base": frm_u,
            "rates": rates,
            "date": data.get("time_last_update_utc") or data.get("time_last_update"),
        }

    async def convert(self, client: httpx.AsyncClient, amount: float, frm: str, to: str) -> Optional[str]:
        with self._conv_lock:
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
                r = await client.get(url, timeout=8.0)
                r.raise_for_status()
                data = r.json()
                rates_new = data.get("rates") or {}
                if to_u not in rates_new:
                    raise ValueError("missing rate")
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
                fb = await self._convert_open_er_api(client, amount, frm_u, to_u)
                if fb is None:
                    return None
                out, meta = fb
                rates_fb = meta.get("rates") if isinstance(meta.get("rates"), dict) else {}
                self._mem = {"base": meta.get("base", frm_u), "rates": rates_fb, "date": meta.get("date")}
                self._loaded_at = time.time()
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_text(json.dumps(self._mem), encoding="utf-8")
                except OSError:
                    pass
                return f"{out:.6g} {to_u}"


async def try_l0_async(capture: str, http: httpx.AsyncClient, fx: FxRateCache) -> Optional[tuple[str, str]]:
    capture = _sanitize_l0_input(capture)
    if not capture:
        return None
    for cand in _l0_query_candidates(capture):
        u = try_units(cand)
        if u:
            return u, "L0-units"
        m = try_math(cand)
        if m is not None:
            return m, "L0-math"
        d = try_date_arithmetic(cand)
        if d:
            return d, "L0-date"
        s_fx = _normalize_currency_aliases(cand)
        fxm = _RE_FX.match(s_fx)
        if fxm:
            out = await fx.convert(http, float(fxm.group("amt")), fxm.group("fc"), fxm.group("tc"))
            if out:
                return out, "L0-currency"
    return None
