"""The one rounding rule of the system. Every total, screen, export and form goes through these.

Money and hours keep 2 decimals, quantities 3, percentages 1, always half up on the decimal value (Python's own
round() is half even on the binary value, so 2.675 would become 2.67 here and 2,68 in the browser).
A document's total is built from rounded lines: line amount, then their sum, then discount and tax.
frontend/src/api/num.ts is the same rule for the browser; tests/test_numbers.py pins both to the same cases.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

MONEY_DP = 2
QTY_DP = 3
PCT_DP = 1


def _half_up(v: float, dp: int) -> float:
    # 9 decimals first drop the binary noise: 1.1 * 1.15 is 1.2649999999999999 and must count as 1.265
    return float(Decimal(f"{v:.9f}").quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)) + 0.0


def money(v: float) -> float:
    return _half_up(v, MONEY_DP)


hours = money


def qty(v: float) -> float:
    return _half_up(v, QTY_DP)


def pct(v: float) -> float:
    return _half_up(v, PCT_DP)


def ceil_units(v: float) -> int:
    """Whole units needed for v: the same noise guard, so 1000 * 1.1 / 100 is 11 like Excel's ROUNDUP, not 12."""
    return math.ceil(float(f"{v:.9f}"))


def text(v: float, dp: int = QTY_DP) -> str:
    """A number for a message, written like the screens: 1.234.567,89. The :g format turns that into 1.23457e+06."""
    whole, _, frac = f"{_half_up(v, dp):,.{dp}f}".partition(".")
    frac = frac.rstrip("0")
    return whole.replace(",", ".") + (f",{frac}" if frac else "")
