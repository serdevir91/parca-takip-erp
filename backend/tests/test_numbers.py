"""One rounding rule on both sides: the cases below run through app.core.numbers and frontend/src/api/num.ts."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core import numbers as num
from app.services import commerce

MONEY = [(2.675, 2.68), (1.005, 1.01), (1.1 * 1.15, 1.27), (-2.675, -2.68), (0.1 + 0.2, 0.3), (1234567.895, 1234567.9), (0.004, 0.0)]
QTY = [(1.0005, 1.001), (2.9999, 3.0), (0.1 + 0.7, 0.8), (-1.0005, -1.001)]
DOCS = [([(3, 19.99), (2, 0.335)], 20, 0), ([(1.5, 33.33), (7, 1.115)], 18, 12.5), ([(1, 0.005)], 20, 0), ([(10, 2.675)], 0, 3)]


@pytest.mark.parametrize("value,want", MONEY)
def test_money(value, want):
    assert num.money(value) == want


@pytest.mark.parametrize("value,want", QTY)
def test_qty(value, want):
    assert num.qty(value) == want


def test_no_negative_zero():
    assert str(num.money(-0.001)) == "0.0"


def test_hours_and_percent():
    assert num.hours(7.125) == 7.13
    assert num.pct(33.35) == 33.4


class Line:
    def __init__(self, qty, price):
        self.qty, self.unit_price = qty, price


def test_browser_uses_the_same_rule(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    source = Path(__file__).parents[2] / "frontend" / "src" / "api" / "num.ts"
    # Type annotations are the only TypeScript in the file, and node strips them on its own from 22.18
    script = tmp_path / "num.ts"
    script.write_text(source.read_text(encoding="utf-8") + f"""
const docs = {json.dumps(DOCS)};
console.log(JSON.stringify({{
  money: {json.dumps([v for v, _ in MONEY])}.map(money),
  qty: {json.dumps([v for v, _ in QTY])}.map(qty),
  docs: docs.map(([lines, tax, disc]) => docTotals(lines.map(([q, p]) => ({{ qty: q, price: p }})), tax, disc)),
}}));
""", encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    if run.returncode and "Unknown file extension" in run.stderr:
        pytest.skip("this node cannot run TypeScript")
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["money"] == [w for _, w in MONEY]
    assert got["qty"] == [w for _, w in QTY]
    for (lines, tax, disc), browser in zip(DOCS, got["docs"]):
        assert commerce.totals([Line(q, p) for q, p in lines], tax, disc) == browser


def test_spare_units_ignore_binary_noise():
    assert num.ceil_units(1000 * 1.1 / 100) == 11
    assert num.ceil_units(1001 * 1.1 / 100) == 12
    assert num.ceil_units(0) == 0


def test_message_numbers_read_like_the_screens():
    assert num.text(1234567.89) == "1.234.567,89"
    assert num.text(2.5) == "2,5"
    assert num.text(8) == "8"
    assert num.text(0.1 + 0.2) == "0,3"
