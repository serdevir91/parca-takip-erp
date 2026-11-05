"""Excel exports (SPEC §9): 'Takip Listesi' (full), 'Parça Takip' (parts only) and the fastener
order form. Built from `ProjectView`, laid out like docs/reference/build_takip_excel.py.

Status is a formula in the workbook (same table as core/status), so changing İlerleme or Temin
Şekli in Excel updates Durum, the counters, the summary KPIs and the charts.
"""
from __future__ import annotations

import io
import re
from typing import Any, Iterable
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.formatting.rule import DataBarRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from ..core.bomparse import ROOT_GROUP, TEMIN_HAZIR, TEMIN_IMALAT, TEMIN_NONE
from ..core.normalize import tr_sort_key
from ..core.status import (COLORS, PROG_WAIT, PROGRESS_CHOICES, STATUS_MAP,
                           STATUS_NO_TEMIN, KIND_HAZIR, KIND_IMALAT, KIND_MONTAJ)
from ..models import Project
from . import xlsafe
from .settings import manufacturers, temin_choices, temin_types
from .tracking import material_status_choices
from .state import FASTENER_COLORS, FASTENER_ORDER_STATUSES, FASTENER_TYPE_ORDER, ProjectView

# ---------- sheet / column names (shared with excel_import) ----------
SHEET_SUMMARY = "Özet"
SHEET_PARTS = "Parça Listesi"
SHEET_FX = "Bağlantı Elemanları"
SHEET_FX_SUM = "Bağlantı Özeti"
SHEET_ORDER = "Sipariş Formu"
SHEET_LISTS = "Listeler"

H_LEVEL, H_PNO, H_TYPE, H_GROUP, H_PARENT = "Seviye", "Parça No", "Tip", "Ana Grup", "Üst Montaj"
H_QTY, H_TOTAL, H_MAT, H_WEIGHT, H_TEMIN = "Adet", "Toplam Adet", "Malzeme", "Birim Ağırlık (g)", "Temin Şekli"
H_COAT, H_REV, H_PROG, H_STATUS = "Kaplama", "Rev", "İlerleme (seç)", "Durum (otomatik)"
H_MANUF, H_MATST, H_T35, H_NOTE, H_KEY = "Üretici", "Malzeme Durumu", "Durum Notu", "Not", "Anahtar"

PART_COLS: list[tuple[str, float]] = [
    (H_LEVEL, 9), (H_PNO, 30), (H_TYPE, 11), (H_GROUP, 16), (H_PARENT, 16), (H_QTY, 6), (H_TOTAL, 8),
    (H_MAT, 22), (H_WEIGHT, 11), (H_TEMIN, 15), (H_COAT, 14), (H_REV, 5), (H_PROG, 15), (H_STATUS, 21),
    (H_MANUF, 16), (H_MATST, 20), (H_T35, 40), (H_NOTE, 44), (H_KEY, 12),
]
PC = {h: i + 1 for i, (h, _) in enumerate(PART_COLS)}          # header -> 1-based column
PL_ = {h: L(c) for h, c in PC.items()}                        # header -> column letter

H_FX_STATUS, H_SPARE, H_ORDER_QTY, H_UNIT, H_PRICE, H_AMOUNT, H_SUPPLIER = (
    "Durum", "Yedek %", "Sipariş Miktarı", "Birim", "Birim Fiyat", "Tutar", "Tedarikçi")
FX_SUM_COLS: list[tuple[str, float]] = [
    ("Tür", 10), ("Açıklama", 32), ("Standart", 22), ("Ölçü", 14), ("Toplam Adet", 10),
    ("Kullanıldığı Ana Gruplar", 44), (H_FX_STATUS, 20), (H_SPARE, 8), (H_ORDER_QTY, 10), (H_UNIT, 8),
    (H_PRICE, 11), (H_AMOUNT, 12), (H_SUPPLIER, 18), (H_NOTE, 36), (H_KEY, 12),
]
FC = {h: i + 1 for i, (h, _) in enumerate(FX_SUM_COLS)}

KEY_PART, KEY_MISSING, KEY_FASTENER = "P:", "M:", "F:"
TYPE_PART, TYPE_ASM, TYPE_PURCH_ASM, TYPE_MISSING = "Parça", "Montaj", "Hazır Alım Montaj", "Eksik"
IN_PURCHASED_TEMIN = "Hazır montaj içinde"
MISSING_SUFFIX = " (EKSİK)"

# ---------- style ----------
FONT, NAVY = "Arial", "1F3864"
HR = 5                                     # header row; data starts at HR + 1
_thin = Side(style="thin", color="BFBFBF")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
HEAD_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=10)
STATUS_FONT = {"Üretilmedi": "833C0B", "Üretildi": "1F4E79", "Sipariş Verilmedi": "9C0006",
               "Sipariş Verildi": "9C5700", "Sipariş Teslim Edildi": "006100", "Montajlanmadı": "3A3838",
               "Montajlandı": "5B2C83", STATUS_NO_TEMIN: "FFFFFF", "Teslim Edildi": "006100"}
CHART = {"Üretildi": "2E75B6", "Üretilmedi": "E97B54", "Sipariş Verilmedi": "E06666", "Sipariş Verildi": "F1C232",
         "Sipariş Teslim Edildi": "6AA84F", "Teslim Edildi": "6AA84F", "Montajlandı": "8E7CC3",
         "Montajlanmadı": "BFBFBF"}
TYPE_FILL = {"Cıvata": "DDEBF7", "Somun": "FFF2CC", "Pim": "E2EFDA", "Rondela": "EDE2F6", "Kama": "FCE4D6",
             "Segman": "DEEAF1"}
TYPE_CHART = {"Cıvata": "2E75B6", "Somun": "F1C232", "Pim": "6AA84F", "Rondela": "8E7CC3", "Kama": "E69138",
              "Segman": "76A5AF"}
SELECT_FILL = "FFF2CC"


def _fill(c: str) -> PatternFill:
    return PatternFill("solid", fgColor=c)


def _f(**k: Any) -> Font:
    return Font(name=FONT, **{"size": 10, **k})


def _header(ws: Worksheet, cols: list[tuple[str, float]], row: int = HR) -> None:
    for i, (h, w) in enumerate(cols, 1):
        c = ws.cell(row, i, h)
        c.fill, c.font, c.border = HEAD_FILL, HEAD_FONT, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[L(i)].width = w
    ws.row_dimensions[row].height = 30


def _title(ws: Worksheet, title: str, sub: str, size: int = 14) -> None:
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, bold=True, size=size, color=NAVY)
    ws["A2"] = sub
    ws["A2"].font = Font(name=FONT, italic=True, size=9, color="595959")


def _landscape(ws: Worksheet, title_rows: bool = True) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    if title_rows:
        ws.print_title_rows = f"{HR}:{HR}"


def _status_cf(ws: Worksheet, rng: str, first: str, colors: dict[str, str]) -> None:
    for status, bg in colors.items():
        if not bg:
            continue
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f'{first}="{status}"'], fill=_fill(bg),
            font=Font(name=FONT, bold=True, color=STATUS_FONT.get(status, "000000"))))


def _xl_str(s: str) -> str:
    """String literal for a formula."""
    return '"' + s.replace('"', '""') + '"'


def _sheet_ref(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


# ---------- formulas ----------
def _is_any(cell: str, names: Iterable[str]) -> str:
    return "OR(" + ",".join(f"{cell}={_xl_str(n)}" for n in names) + ")"


def status_formula(r: int, make: Iterable[str] = (TEMIN_IMALAT,), buy: Iterable[str] = (TEMIN_HAZIR,)) -> str:
    """Durum from İlerleme + Temin Şekli + Tip, the table of SPEC §5 (core/status.STATUS_MAP)."""
    m, j, c = f"{PL_[H_PROG]}{r}", f"{PL_[H_TEMIN]}{r}", f"{PL_[H_TYPE]}{r}"
    done, run = _xl_str(PROGRESS_CHOICES[2]), _xl_str(PROGRESS_CHOICES[1])

    def pick(kind: str) -> str:
        s = STATUS_MAP[kind]
        return (f"IF({m}={done},{_xl_str(s[PROGRESS_CHOICES[2]])},IF({m}={run},"
                f"{_xl_str(s[PROGRESS_CHOICES[1]])},{_xl_str(s[PROGRESS_CHOICES[0]])}))")
    return (f'=IF({m}="","",IF({_is_any(j, buy)},{pick(KIND_HAZIR)},'
            f'IF(OR({c}={_xl_str(TYPE_ASM)},{c}={_xl_str(TYPE_PURCH_ASM)}),{pick(KIND_MONTAJ)},'
            f'IF({_is_any(j, make)},{pick(KIND_IMALAT)},{_xl_str(STATUS_NO_TEMIN)}))))')


# ---------- lists sheet (dropdown sources) ----------
class _Lists:
    """Hidden sheet holding dropdown values; avoids the 255 character limit of inline lists."""

    def __init__(self, wb: Workbook, lists: dict[str, list[str]], make: list[str], buy: list[str]):
        self.make, self.buy = make, buy
        ws = wb.create_sheet(SHEET_LISTS)
        ws.sheet_state = "hidden"
        self.ref: dict[str, str] = {}
        for i, (name, values) in enumerate(lists.items(), 1):
            ws.cell(1, i, name).font = _f(bold=True)
            for j, v in enumerate(values, 2):
                ws.cell(j, i, v)
            if values:
                col = L(i)
                self.ref[name] = f"{SHEET_LISTS}!${col}$2:${col}${len(values) + 1}"

    def validation(self, ws: Worksheet, name: str, prompt: str) -> DataValidation | None:
        if name not in self.ref:
            return None
        dv = DataValidation(type="list", formula1=self.ref[name], allow_blank=True, showErrorMessage=True,
                            errorTitle="Geçersiz değer", error="Lütfen listeden bir değer seçin.",
                            promptTitle=prompt, prompt="Listeden seçin")
        ws.add_data_validation(dv)
        return dv


def _lists(db: Session) -> dict[str, list[str]]:
    return {"progress": list(PROGRESS_CHOICES), "temin": temin_choices(db),
            "manufacturer": manufacturers(db), "material_status": material_status_choices(db),
            "fastener_status": list(FASTENER_ORDER_STATUSES)}


# ---------- parts sheet ----------
def _part_line(v: dict[str, Any], parts_only: bool) -> dict[str, Any]:
    if v["is_assembly"]:
        typ = TYPE_PURCH_ASM if parts_only else TYPE_ASM
    else:
        typ = TYPE_PART
    in_p = bool(v["in_purchased"])
    root = v["depth"] == 0
    temin = IN_PURCHASED_TEMIN if in_p else (v["procurement"] or "")
    levels = v.get("levels") or [v["level"]]
    return {
        "level": levels[0], "pno": v["part_no"], "typ": typ, "group": v["main_group"] or ROOT_GROUP,
        "parent": v["parent_part_no"] or "", "qty": v["qty"], "total": v["total_qty"],
        "mat": v["material"] or ("" if v["is_assembly"] else TEMIN_NONE), "weight": v["weight"],
        "temin": temin, "coat": v["coating"] or "", "rev": v["rev"] or "-",
        "progress": None if (in_p or root) else (v["progress"] or PROG_WAIT),
        "manuf": v["manufacturer"] or "", "matst": v["material_status"] or "", "t35": v["t35_note"] or "",
        "note": v["note"] or "", "key": "" if (in_p or root) else KEY_PART + v["part_no"],
        "depth": v["depth"], "is_asm": v["is_assembly"], "in_p": in_p, "new": v["is_new"], "missing": False,
        "editable": not (in_p or root), "temin_editable": not in_p and not root and not v["is_purchased_assembly"],
    }


def _missing_line(m: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any]:
    b = base or {}
    return {
        "level": (b.get("level") or "") + "+", "pno": m["part_no"] + MISSING_SUFFIX, "typ": TYPE_MISSING,
        "group": b.get("group", ""), "parent": b.get("parent", ""), "qty": None, "total": m["qty"],
        "mat": m["material"] or b.get("mat", ""), "weight": b.get("weight"), "temin": m["procurement"] or "",
        "coat": b.get("coat", ""), "rev": m["rev"] or "-", "progress": m["progress"] or PROG_WAIT,
        "manuf": "", "matst": "", "t35": "", "note": m["note"] or m["reason"] or "",
        "key": f"{KEY_MISSING}{m['id']}", "depth": b.get("depth", 1), "is_asm": False, "in_p": False,
        "new": False, "missing": True, "editable": True, "temin_editable": False,
    }


def _with_missing(lines: list[dict[str, Any]], view: ProjectView) -> list[dict[str, Any]]:
    """Insert each missing row after the first line of its part (or at the end)."""
    by_part: dict[str, list[dict[str, Any]]] = {}
    for m in view.missing_views():
        by_part.setdefault(m["part_no"], []).append(m)
    out: list[dict[str, Any]] = []
    for x in lines:
        out.append(x)
        if x["editable"] and not x["missing"] and x["pno"] in by_part:
            out.extend(_missing_line(m, x) for m in by_part.pop(x["pno"]))
    for ms in by_part.values():
        out.extend(_missing_line(m, None) for m in ms)
    return out


def takip_lines(view: ProjectView) -> list[dict[str, Any]]:
    """Full list: every non-fastener BOM row (assemblies indented), plus missing rows."""
    lines = [_part_line(view.row_view(r), False) for r in view.rows if not r.fastener_key]
    return _with_missing(lines, view)


def _temin_groups(db: Session) -> tuple[list[str], list[str]]:
    types = temin_types(db)
    return [t["name"] for t in types if t["kind"] == KIND_IMALAT], [t["name"] for t in types if t["kind"] == KIND_HAZIR]


def parca_lines(view: ProjectView, only: set[str] | None = None) -> list[dict[str, Any]]:
    """Parts only: one line per part, assemblies dropped except purchased (Hazır Alım) ones."""
    lines = []
    for v in view.parts(include_in_purchased=False):
        if v["is_assembly"] and v["status_kind"] != KIND_HAZIR:
            continue
        if only is not None and v["part_no"] not in only:
            continue
        lines.append(_part_line(v, True))
    out = _with_missing(lines, view)
    if only is not None:
        out = [x for x in out if not x["missing"] or x["pno"][: -len(MISSING_SUFFIX)] in only]
    return out


def _write_parts(ws: Worksheet, lines: list[dict[str, Any]], lists: _Lists, title: str,
                 parts_only: bool) -> int:
    sub = (("Montaj satırları çıkarıldı; sadece imal edilecek ve satın alınacak kalemler. " if parts_only else "")
           + 'Sarı "İlerleme" sütunundan seçin; "Durum" Temin Şekli\'ne göre otomatik oluşur. '
           "Yeşil parça no = yeni BOM kalemi; mor satır = eksik adet. Değişiklikleri sisteme geri yükleyebilirsiniz.")
    _title(ws, title, sub)
    _header(ws, PART_COLS)
    ws.cell(HR, PC[H_PROG]).fill = _fill("BF8F00")
    ws.cell(HR, PC[H_STATUS]).fill = _fill("595959")
    ncol = len(PART_COLS)
    dv_prog = lists.validation(ws, "progress", "İlerleme")
    dv_temin = lists.validation(ws, "temin", "Temin Şekli")
    dv_man = lists.validation(ws, "manufacturer", "Üretici")
    dv_mat = lists.validation(ws, "material_status", "Malzeme Durumu")
    base = _f()
    r = HR + 1
    for x in lines:
        indent = "" if parts_only else "   " * max(x["depth"] - 1, 0)
        vals = {
            H_LEVEL: x["level"], H_PNO: indent + x["pno"], H_TYPE: x["typ"], H_GROUP: x["group"],
            H_PARENT: x["parent"], H_QTY: x["qty"], H_TOTAL: x["total"], H_MAT: x["mat"] or None,
            H_WEIGHT: x["weight"], H_TEMIN: x["temin"] or None, H_COAT: x["coat"] or None, H_REV: x["rev"],
            H_PROG: x["progress"], H_STATUS: status_formula(r, lists.make, lists.buy) if x["editable"] else None,
            H_MANUF: x["manuf"] or None, H_MATST: x["matst"] or None, H_T35: x["t35"] or None,
            H_NOTE: x["note"] or None, H_KEY: x["key"] or None,
        }
        for h, col in PC.items():
            c = ws.cell(r, col, vals[h])
            c.font, c.border = base, BORDER
            c.alignment = Alignment(vertical="center", wrap_text=h in (H_T35, H_NOTE))
        ws.cell(r, PC[H_LEVEL]).number_format = "@"
        ws.cell(r, PC[H_WEIGHT]).number_format = "#,##0.00"
        for h in (H_QTY, H_TOTAL, H_REV, H_PROG):
            ws.cell(r, PC[h]).alignment = Alignment(horizontal="center", vertical="center")
        if x["missing"]:
            for i in range(1, ncol + 1):
                ws.cell(r, i).font = _f(bold=True, color="5B2C83")
                ws.cell(r, i).fill = _fill(COLORS["missing"])
            ws.cell(r, PC[H_TOTAL]).font = _f(bold=True, color="0000FF")
        elif x["is_asm"]:
            for i in range(1, ncol + 1):
                ws.cell(r, i).font = _f(bold=True)
                ws.cell(r, i).fill = _fill("FCE4D6" if parts_only else ("DDEBF7" if x["depth"] <= 1 else "EEF4FB"))
        if x["in_p"]:
            for i in range(1, ncol + 1):
                ws.cell(r, i).font = _f(color="808080", italic=True)
        if not x["missing"]:
            if x["mat"] == TEMIN_NONE:
                ws.cell(r, PC[H_MAT]).font = _f(italic=True, color="C00000")
            if x["temin"] == TEMIN_NONE:
                ws.cell(r, PC[H_TEMIN]).font = _f(italic=True, color="C00000")
            if x["new"]:
                ws.cell(r, PC[H_PNO]).fill = _fill(COLORS["new"])
                ws.cell(r, PC[H_PNO]).font = _f(bold=True, color="274E13")
        if x["editable"]:
            cell = ws.cell(r, PC[H_PROG])
            cell.fill, cell.font = _fill(SELECT_FILL), _f(bold=True, color="0000FF")
            pairs = [(dv_prog, H_PROG)] + ([] if x["missing"] else [(dv_man, H_MANUF), (dv_mat, H_MATST)])
            for dv, h in pairs:
                if dv is not None:
                    dv.add(ws.cell(r, PC[h]).coordinate)
            if dv_temin is not None and x["temin_editable"] and (not x["is_asm"] or x["temin"] in lists.buy):
                dv_temin.add(ws.cell(r, PC[H_TEMIN]).coordinate)
        r += 1
    last = max(r - 1, HR + 1)
    st = PL_[H_STATUS]
    _status_cf(ws, f"{st}{HR + 1}:{st}{last}", f"{st}{HR + 1}",
               {s: COLORS.get(s, "") for s in [*STATUS_MAP[KIND_IMALAT].values(), *STATUS_MAP[KIND_HAZIR].values(),
                                               *STATUS_MAP[KIND_MONTAJ].values(), STATUS_NO_TEMIN]})
    pg = PL_[H_PROG]
    ws.conditional_formatting.add(f"{pg}{HR + 1}:{pg}{last}", FormulaRule(
        formula=[f'{pg}{HR + 1}="{PROGRESS_CHOICES[2]}"'], fill=_fill("E2EFDA"),
        font=Font(name=FONT, bold=True, color="375623")))
    ws.conditional_formatting.add(f"{pg}{HR + 1}:{pg}{last}", FormulaRule(
        formula=[f'{pg}{HR + 1}="{PROGRESS_CHOICES[1]}"'], fill=_fill("FFEB9C"),
        font=Font(name=FONT, bold=True, color="7F6000")))
    ws.auto_filter.ref = f"A{HR}:{L(ncol)}{last}"
    ws.freeze_panes = f"C{HR + 1}"
    ws.column_dimensions[PL_[H_KEY]].hidden = True
    b, g = PL_[H_PNO], PL_[H_TOTAL]
    ws["A3"], ws["E3"] = "Filtrelenen satır:", "Filtrelenen toplam adet:"
    ws["C3"] = f"=SUBTOTAL(103,{b}{HR + 1}:{b}{last})"
    ws["G3"] = f"=SUBTOTAL(109,{g}{HR + 1}:{g}{last})"
    for a in ("A3", "E3"):
        ws[a].font = _f(bold=True)
    for a in ("C3", "G3"):
        ws[a].font, ws[a].fill = _f(bold=True, color=NAVY), _fill(SELECT_FILL)
    ws["I3"] = "Renkler:"
    ws["I3"].font = _f(bold=True)
    legend = [("Yeni BOM kalemi", COLORS["new"], "274E13"), ("Eksik adet", COLORS["missing"], "5B2C83"),
              ("Hazır alım montaj", "FCE4D6", "000000") if parts_only else ("Ana grup montaj", "DDEBF7", NAVY),
              ("Seçim sütunu", SELECT_FILL, "0000FF")]
    for col, (t, bg, fg) in zip(("J", "K", "L", "M"), legend):
        c = ws[f"{col}3"]
        c.value, c.fill, c.font, c.border = t, _fill(bg), _f(bold=True, color=fg), BORDER
    _landscape(ws)
    return last


# ---------- fastener sheets ----------
def _write_fastener_detail(ws: Worksheet, view: ProjectView) -> int:
    _title(ws, "Bağlantı Elemanları – Detay (montaj bazında)",
           'Toplam Adet = Adet × Montaj Çarpanı. Sipariş takibi "Bağlantı Özeti" sayfasındadır. '
           "Satın alınan montajların içindekiler hariç.")
    cols = [("Ana Grup", 16), ("Üst Montaj", 16), ("Seviye", 11), ("Tür", 9), ("Açıklama", 30), ("Standart", 22),
            ("Ölçü", 14), ("Adet", 7), ("Montaj Çarpanı", 9), ("Toplam Adet", 9), ("Orijinal Ad", 36), (H_KEY, 12)]
    _header(ws, cols)
    base = _f()
    r = HR + 1
    for v in view.fastener_rows():
        if v["in_purchased"]:
            continue
        group = ROOT_GROUP if v["depth"] <= 1 else (v["main_group"] or ROOT_GROUP)
        tot = f"=H{r}*I{r}" if v["qty"] * v["multiplier"] == v["total_qty"] else v["total_qty"]
        vals = [group, v["parent_part_no"] or "", v["level"], v["fastener_type"], v["fastener_desc"],
                v["fastener_std"], v["fastener_size"], v["qty"], v["multiplier"], tot, v["file_name"],
                v["fastener_key"]]
        for i, val in enumerate(vals, 1):
            c = ws.cell(r, i, val)
            c.font, c.border = base, BORDER
            if i in (7, 8, 9, 10):
                c.alignment = Alignment(horizontal="center")
        ws.cell(r, 4).fill = _fill(TYPE_FILL.get(v["fastener_type"] or "", "FFFFFF"))
        ws.cell(r, 4).font = _f(bold=True)
        ws.cell(r, 10).font = _f(bold=True)
        ws.cell(r, 3).number_format = "@"
        r += 1
    last = max(r - 1, HR + 1)
    ws.auto_filter.ref = f"A{HR}:{L(len(cols))}{last}"
    ws.freeze_panes = f"D{HR + 1}"
    ws.column_dimensions[L(len(cols))].hidden = True
    ws["A3"] = "Filtrelenen toplam adet:"
    ws["A3"].font = _f(bold=True)
    ws["C3"] = f"=SUBTOTAL(109,J{HR + 1}:J{last})"
    ws["C3"].font, ws["C3"].fill = _f(bold=True, size=11, color=NAVY), _fill(SELECT_FILL)
    _landscape(ws)
    return last


def _write_fastener_summary(ws: Worksheet, view: ProjectView, lists: _Lists, detail_last: int | None,
                            title: str, sub: str) -> int:
    """One line per fastener item with order status and order form columns.
    With `detail_last`, Toplam Adet sums the detail sheet; otherwise it is a value."""
    _title(ws, title, sub)
    _header(ws, FX_SUM_COLS)
    base = _f()
    dv = lists.validation(ws, "fastener_status", "Sipariş Durumu")
    c = {h: L(i) for h, i in FC.items()}
    r = HR + 1
    dref = _sheet_ref(SHEET_FX)
    for it in view.fasteners():
        if detail_last:
            total: Any = (f"=SUMIF({dref}!$L${HR + 1}:$L${detail_last},{c[H_KEY]}{r},"
                          f"{dref}!$J${HR + 1}:$J${detail_last})")
        else:
            total = it["total_qty"]
        vals = {
            "Tür": it["type"], "Açıklama": it["desc"], "Standart": it["std"], "Ölçü": it["size"],
            "Toplam Adet": total, "Kullanıldığı Ana Gruplar": ", ".join(it["groups"]),
            H_FX_STATUS: it["order_status"], H_SPARE: it["spare_pct"],
            H_ORDER_QTY: f"={c['Toplam Adet']}{r}+ROUNDUP({c['Toplam Adet']}{r}*{c[H_SPARE]}{r}/100,0)",
            H_UNIT: it["unit"], H_PRICE: it["unit_price"],
            H_AMOUNT: f'=IF({c[H_PRICE]}{r}="","",{c[H_ORDER_QTY]}{r}*{c[H_PRICE]}{r})',
            H_SUPPLIER: it["supplier"] or None, H_NOTE: it["note"] or None, H_KEY: KEY_FASTENER + it["key"],
        }
        for h, col in FC.items():
            cell = ws.cell(r, col, vals[h])
            cell.font, cell.border = base, BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=h in ("Kullanıldığı Ana Gruplar", H_NOTE))
            if h in ("Ölçü", "Toplam Adet", H_SPARE, H_ORDER_QTY, H_UNIT):
                cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(r, FC["Tür"]).fill = _fill(TYPE_FILL.get(it["type"] or "", "FFFFFF"))
        ws.cell(r, FC["Tür"]).font = _f(bold=True)
        ws.cell(r, FC["Toplam Adet"]).font = _f(bold=True, size=11)
        ws.cell(r, FC[H_ORDER_QTY]).font = _f(bold=True)
        for h in (H_FX_STATUS, H_SPARE, H_PRICE):
            ws.cell(r, FC[h]).fill = _fill(SELECT_FILL)
        ws.cell(r, FC[H_PRICE]).number_format = "#,##0.00"
        ws.cell(r, FC[H_AMOUNT]).number_format = "#,##0.00"
        if dv is not None:
            dv.add(ws.cell(r, FC[H_FX_STATUS]).coordinate)
        r += 1
    last = max(r - 1, HR + 1)
    spare = DataValidation(type="decimal", operator="between", formula1="0", formula2="1000", allow_blank=True,
                           showErrorMessage=True, error="Yedek yüzdesi 0 ile 1000 arasında olmalı.")
    ws.add_data_validation(spare)
    spare.add(f"{c[H_SPARE]}{HR + 1}:{c[H_SPARE]}{last}")
    _status_cf(ws, f"{c[H_FX_STATUS]}{HR + 1}:{c[H_FX_STATUS]}{last}", f"{c[H_FX_STATUS]}{HR + 1}", FASTENER_COLORS)
    ws.auto_filter.ref = f"A{HR}:{L(len(FX_SUM_COLS))}{last}"
    ws.freeze_panes = f"A{HR + 1}"
    ws.column_dimensions[c[H_KEY]].hidden = True
    ws["A3"] = "Filtrelenen toplam adet:"
    ws["A3"].font = _f(bold=True)
    ws["C3"] = f"=SUBTOTAL(109,{c['Toplam Adet']}{HR + 1}:{c['Toplam Adet']}{last})"
    ws["E3"] = "Filtrelenen sipariş tutarı:"
    ws["E3"].font = _f(bold=True)
    ws["G3"] = f"=SUBTOTAL(109,{c[H_AMOUNT]}{HR + 1}:{c[H_AMOUNT]}{last})"
    ws["G3"].number_format = "#,##0.00"
    for a in ("C3", "G3"):
        ws[a].font, ws[a].fill = _f(bold=True, size=11, color=NAVY), _fill(SELECT_FILL)
    _landscape(ws)
    return last


# ---------- summary sheet ----------
def _write_summary(o: Worksheet, view: ProjectView, title: str, parts_last: int, with_fx: bool,
                   fx_last: int | None, with_montaj: bool) -> None:
    o.sheet_view.zoomScale = 90
    for col, w in zip("ABCDEFGHIJKLMNOP", [30] + [11] * 15):
        o.column_dimensions[col].width = w
    ver = view.version
    approved = ver.approved_at.astimezone().strftime("%d.%m.%Y") if ver is not None and ver.approved_at else "-"
    _title(o, title, f"{SHEET_PARTS}" + (f" ve {SHEET_FX_SUM}" if with_fx else "")
           + f"'ndeki seçimlere ve Temin Şekli'ne göre otomatik güncellenir. Güncel BOM: "
           f"{ver.filename if ver else '-'} (onay {approved}).", size=16)
    P = _sheet_ref(SHEET_PARTS)
    lo, hi = HR + 1, parts_last

    def rng(h: str) -> str:
        return f"{P}!${PL_[h]}${lo}:${PL_[h]}${hi}"
    dur, qty, grp, tip = rng(H_STATUS), rng(H_TOTAL), rng(H_GROUP), rng(H_TYPE)

    def sec(row: int, t: str, h2: str = "Satır", h3: str = "Adet") -> None:
        for k, v in enumerate([t, h2, h3]):
            c = o.cell(row, 1 + k, v)
            c.fill, c.font = HEAD_FILL, HEAD_FONT
            c.alignment = Alignment(horizontal="left" if k == 0 else "center")

    def line(row: int, label: str, f1: Any, f2: Any = None, key: str | None = None, bold: bool = False,
             pct: bool = False, bg: str | None = None) -> None:
        for i, v in enumerate([label, f1, f2], 1):
            c = o.cell(row, i, v)
            c.font, c.border = _f(bold=bold), BORDER
            if i > 1:
                c.alignment = Alignment(horizontal="center")
                if pct:
                    c.number_format = "0%"
        if key:
            o.cell(row, 1).fill = _fill(COLORS.get(key) or FASTENER_COLORS.get(key, "FFFFFF"))
            o.cell(row, 1).font = _f(bold=True, color=STATUS_FONT.get(key, "000000"))
        if bg:
            o.cell(row, 1).fill = _fill(bg)

    def cnt(status: str) -> tuple[str, str]:
        # Every status belongs to one kind, so the temin column adds nothing here
        return (f"=COUNTIFS({dur},{_xl_str(status)})", f"=SUMIFS({qty},{dur},{_xl_str(status)})")

    imalat = list(dict.fromkeys(STATUS_MAP[KIND_IMALAT].values()))[::-1]      # Üretildi, Üretilmedi
    hazir = list(dict.fromkeys(STATUS_MAP[KIND_HAZIR].values()))
    montaj = list(dict.fromkeys(STATUS_MAP[KIND_MONTAJ].values()))[::-1]

    R0 = 9
    sec(R0, "İmalat Parçaları")
    for i, s in enumerate(imalat):
        line(R0 + 1 + i, s, *cnt(s), key=s)
    line(R0 + 3, "Toplam", f"=B{R0 + 1}+B{R0 + 2}", f"=C{R0 + 1}+C{R0 + 2}", bold=True)
    line(R0 + 4, "İlerleme", f"=IFERROR(B{R0 + 1}/B{R0 + 3},0)", f"=IFERROR(C{R0 + 1}/C{R0 + 3},0)", bold=True,
         pct=True)
    R1 = R0 + 6
    sec(R1, "Hazır Alım (parça + montaj)")
    for i, s in enumerate(hazir):
        line(R1 + 1 + i, s, *cnt(s), key=s)
    line(R1 + 4, "Toplam", f"=SUM(B{R1 + 1}:B{R1 + 3})", f"=SUM(C{R1 + 1}:C{R1 + 3})", bold=True)
    line(R1 + 5, "Teslim oranı", f"=IFERROR(B{R1 + 3}/B{R1 + 4},0)", f"=IFERROR(C{R1 + 3}/C{R1 + 4},0)",
         bold=True, pct=True)
    nxt = R1 + 7
    RM = None
    if with_montaj:
        RM = nxt
        sec(RM, "Montajlar")
        for i, s in enumerate(montaj):
            line(RM + 1 + i, s, *cnt(s), key=s)
        line(RM + 3, "Toplam", f"=B{RM + 1}+B{RM + 2}", f"=C{RM + 1}+C{RM + 2}", bold=True)
        nxt = RM + 5
    R2 = RT = R3 = None
    types: list[str] = []
    if with_fx and fx_last:
        S = _sheet_ref(SHEET_FX_SUM)
        BT = f"{S}!$A${HR + 1}:$A${fx_last}"
        BQ = f"{S}!${L(FC['Toplam Adet'])}${HR + 1}:${L(FC['Toplam Adet'])}${fx_last}"
        BD = f"{S}!${L(FC[H_FX_STATUS])}${HR + 1}:${L(FC[H_FX_STATUS])}${fx_last}"
        R2 = nxt
        sec(R2, "Bağlantı Elemanları", "Kalem", "Adet")
        present = {f["type"] for f in view.fasteners()}
        types = [t for t in FASTENER_TYPE_ORDER if t in present] + sorted(present - set(FASTENER_TYPE_ORDER),
                                                                           key=tr_sort_key)
        for i, t in enumerate(types):
            line(R2 + 1 + i, t, f"=COUNTIF({BT},{_xl_str(t)})", f"=SUMIF({BT},{_xl_str(t)},{BQ})",
                 bg=TYPE_FILL.get(t, "FFFFFF"))
        RT = R2 + 1 + len(types)
        line(RT, "Toplam", f"=SUM(B{R2 + 1}:B{max(RT - 1, R2 + 1)})" if types else 0,
             f"=SUM(C{R2 + 1}:C{max(RT - 1, R2 + 1)})" if types else 0, bold=True)
        R3 = RT + 2
        sec(R3, "Bağlantı Elemanı Siparişi", "Kalem", "")
        for i, s in enumerate(FASTENER_ORDER_STATUSES):
            line(R3 + 1 + i, s, f"=COUNTIF({BD},{_xl_str(s)})", "", key=s)
        nxt = R3 + 5
    R4 = nxt
    sec(R4, "Diğer")
    line(R4 + 1, "Eksik adet satırları", f"=COUNTIF({tip},{_xl_str(TYPE_MISSING)})",
         f"=SUMIF({tip},{_xl_str(TYPE_MISSING)},{qty})", bg=COLORS["missing"])
    line(R4 + 2, "Temin şekli belirtilmemiş", f"=COUNTIF({dur},{_xl_str(STATUS_NO_TEMIN)})",
         f"=SUMIF({dur},{_xl_str(STATUS_NO_TEMIN)},{qty})")
    o.cell(R4 + 2, 1).font = _f(color="C00000")

    cards = [("A4", "A5", "İMALAT İLERLEMESİ", f"=B{R0 + 4}", "0%", "2E75B6"),
             ("B4:D4", "B5:D5", "ÜRETİLEN PARÇA (satır)", f'=B{R0 + 1}&" / "&B{R0 + 3}', "@", "2E75B6"),
             ("E4:G4", "E5:G5", "HAZIR ALIM TESLİM (satır)", f'=B{R1 + 3}&" / "&B{R1 + 4}', "@", "6AA84F")]
    if with_fx and RT and R3:
        cards += [("H4:J4", "H5:J5", "BAĞLANTI ELEMANI (adet)", f"=C{RT}", "#,##0", "8E7CC3"),
                  ("K4:M4", "K5:M5", "BAĞLANTI TESLİM (kalem)", f'=B{R3 + 3}&" / "&B{RT}', "@", "8E7CC3"),
                  ("N4:P4", "N5:P5", "EKSİK ADET", f"=C{R4 + 1}", "0", "5B2C83")]
    else:
        cards += [("H4:J4", "H5:J5", "TESLİM ORANI", f"=B{R1 + 5}", "0%", "6AA84F"),
                  ("K4:M4", "K5:M5", "EKSİK ADET", f"=C{R4 + 1}", "0", "5B2C83")]
    for lab_rng, val_rng, lab, formula, fmt, colr in cards:
        if ":" in lab_rng:
            o.merge_cells(lab_rng)
            o.merge_cells(val_rng)
        a, v = o[lab_rng.split(":")[0]], o[val_rng.split(":")[0]]
        a.value, a.font = lab, Font(name=FONT, bold=True, size=9, color="FFFFFF")
        a.alignment = Alignment(horizontal="center", vertical="center")
        v.value, v.font, v.number_format = formula, Font(name=FONT, bold=True, size=20, color=colr), fmt
        v.alignment = Alignment(horizontal="center", vertical="center")
        sd = Side(style="thin", color=colr)
        for rr in (lab_rng, val_rng):
            cells = o[rr] if ":" in rr else ((o[rr],),)
            for row_ in cells:
                for cc in row_:
                    cc.border = Border(left=sd, right=sd, top=sd, bottom=sd)
                    if rr == lab_rng:
                        cc.fill = _fill(colr)
    o.row_dimensions[4].height = 20
    o.row_dimensions[5].height = 36

    def pie(title_: str, r1: int, r2: int, val_col: int, colors: list[str], anchor: str) -> None:
        ch = PieChart()
        ch.title = title_
        ch.add_data(Reference(o, min_col=val_col, min_row=r1, max_row=r2), titles_from_data=False)
        ch.set_categories(Reference(o, min_col=1, min_row=r1, max_row=r2))
        s = ch.series[0]
        for i, col in enumerate(colors):
            pt = DataPoint(idx=i)
            pt.graphicalProperties.solidFill = col
            pt.graphicalProperties.line.solidFill = "FFFFFF"
            s.dPt.append(pt)
        dl = DataLabelList()
        dl.showPercent, dl.showVal = True, True
        dl.showCatName = dl.showSerName = dl.showLegendKey = dl.showLeaderLines = False
        ch.dataLabels = dl
        ch.legend.position = "r"
        ch.width, ch.height = 11.5, 7.2
        o.add_chart(ch, anchor)

    pie("İmalat Parçaları (satır)", R0 + 1, R0 + 2, 2, [CHART[s] for s in imalat], "E8")
    pie("Hazır Alım Siparişleri (satır)", R1 + 1, R1 + 3, 2, [CHART[s] for s in hazir], "K8")
    if with_fx and R2 and RT and R3:
        if types:
            pie("Bağlantı Elemanları – türe göre adet", R2 + 1, RT - 1, 3,
                [TYPE_CHART.get(t, "999999") for t in types], "E23")
        pie("Bağlantı Elemanı Siparişleri (kalem)", R3 + 1, R3 + 3, 2,
            [CHART[s] for s in FASTENER_ORDER_STATUSES], "K23")
    elif RM:
        pie("Montajlar (satır)", RM + 1, RM + 2, 2, [CHART[s] for s in montaj], "E23")

    # groups table + stacked bar chart
    G0 = max(R4 + 6, 39 if with_fx else 27)
    o.cell(G0 - 1, 1, "Ana Gruplara Göre Durum").font = Font(name=FONT, bold=True, size=12, color=NAVY)
    heads = ["Ana Grup", "İmalat Parça", "Üretildi", "Üretilmedi", "İlerleme", "Hazır Alım", "Teslim Edildi"]
    for i, h in enumerate(heads, 1):
        c = o.cell(G0, i, h)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    o.row_dimensions[G0].height = 30
    groups = [g["group"] for g in view.dashboard()["groups"]] or [ROOT_GROUP]
    # A part can list several groups ("A, B"); FIND on ", list," matches whole names only.
    in_grp = f'ISNUMBER(FIND(", "&$A{{r}}&",",", "&{grp}&","))'

    def sp(r: int, *conds: str) -> str:
        return "=SUMPRODUCT(" + "*".join([f"--{in_grp.format(r=r)}", *[f"--({c})" for c in conds]]) + ")"
    r = G0 + 1
    for g in groups:
        vals = [g, f"=C{r}+D{r}",
                sp(r, f'{dur}="Üretildi"'),
                sp(r, f'{dur}="Üretilmedi"'),
                f'=IF(B{r}=0,"-",C{r}/B{r})',
                sp(r, "+".join(f"({dur}={_xl_str(s)})" for s in dict.fromkeys(STATUS_MAP[KIND_HAZIR].values()))),
                sp(r, f'{dur}="Sipariş Teslim Edildi"')]
        for i, v in enumerate(vals, 1):
            c = o.cell(r, i, v)
            c.font, c.border = _f(), BORDER
            c.alignment = Alignment(horizontal="center" if i > 1 else "left")
        o.cell(r, 5).number_format = "0%"
        o.cell(r, 5).font = _f(bold=True)
        r += 1
    GL = r - 1
    tot = ["TOPLAM", f"=SUM(B{G0 + 1}:B{GL})", f"=SUM(C{G0 + 1}:C{GL})", f"=SUM(D{G0 + 1}:D{GL})",
           f'=IF(B{r}=0,"-",C{r}/B{r})', f"=SUM(F{G0 + 1}:F{GL})", f"=SUM(G{G0 + 1}:G{GL})"]
    for i, v in enumerate(tot, 1):
        c = o.cell(r, i, v)
        c.font, c.fill, c.border = Font(name=FONT, bold=True, color="FFFFFF"), HEAD_FILL, BORDER
        c.alignment = Alignment(horizontal="center" if i > 1 else "left")
    o.cell(r, 5).number_format = "0%"
    o.conditional_formatting.add(f"E{G0 + 1}:E{GL}", DataBarRule(start_type="num", start_value=0, end_type="num",
                                                                  end_value=1, color="5B9BD5"))
    bar = BarChart()
    bar.type, bar.grouping, bar.overlap = "bar", "stacked", 100
    bar.title = "Ana gruplara göre imalat parçaları (satır)"
    bar.add_data(Reference(o, min_col=3, min_row=G0, max_row=GL), titles_from_data=True)
    bar.add_data(Reference(o, min_col=4, min_row=G0, max_row=GL), titles_from_data=True)
    bar.set_categories(Reference(o, min_col=1, min_row=G0 + 1, max_row=GL))
    bar.series[0].graphicalProperties.solidFill = CHART["Üretildi"]
    bar.series[1].graphicalProperties.solidFill = CHART["Üretilmedi"]
    bar.x_axis.scaling.orientation = "maxMin"
    bar.legend.position = "b"
    bar.gapWidth = 40
    bar.y_axis.majorGridlines = None
    bar.x_axis.delete = bar.y_axis.delete = False
    bar.x_axis.tickLblSkip = 1
    bar.width, bar.height = 17, max(7.5, min(30.0, 1.0 * len(groups) + 3))
    o.add_chart(bar, f"I{G0}")
    _landscape(o, title_rows=False)


# ---------- workbooks ----------
def _name(project: Project) -> str:
    return project.root_part_no or project.name


def _finish(wb: Workbook, colors: Iterable[str]) -> Workbook:
    for s, cl in zip([w for w in wb.worksheets if w.title != SHEET_LISTS], colors):
        s.sheet_properties.tabColor = cl
    for s in wb.worksheets:
        s.sheet_view.showGridLines = False
    wb.active = 0
    return wb


def build_takip_listesi(db: Session, view: ProjectView) -> Workbook:
    """Full workbook: Özet, Parça Listesi (assemblies indented), Bağlantı Elemanları, Bağlantı Özeti."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_PARTS
    lists = _Lists(wb, _lists(db), *_temin_groups(db))
    name = _name(view.project)
    pl = _write_parts(ws, takip_lines(view), lists, f"{name} – Parça Listesi", parts_only=False)
    fl = _write_fastener_detail(wb.create_sheet(SHEET_FX, 1), view)
    ul = _write_fastener_summary(
        wb.create_sheet(SHEET_FX_SUM, 2), view, lists, fl, "Bağlantı Elemanları – Kalem Bazında Toplam",
        'Her ölçü tek satır; adetler "Bağlantı Elemanları" sayfasından otomatik toplanır. '
        "Sipariş durumunu, yedek yüzdesini ve birim fiyatı buradan takip edin.")
    o = wb.create_sheet(SHEET_SUMMARY, 0)
    _write_summary(o, view, f"{name} – Proje Takip Özeti", pl, True, ul, with_montaj=True)
    return _finish(wb, [NAVY, "2E75B6", "70AD47", "548235"])


def build_parca_takip(db: Session, view: ProjectView, only: set[str] | None = None) -> Workbook:
    """Simple workbook: Özet + Parça Listesi (parts only, purchased assemblies as one line).
    `only` limits the list to the given part numbers ("görüneni dışa aktar")."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_PARTS
    lists = _Lists(wb, _lists(db), *_temin_groups(db))
    name = _name(view.project)
    pl = _write_parts(ws, parca_lines(view, only), lists, f"{name} – Parça Listesi", parts_only=True)
    o = wb.create_sheet(SHEET_SUMMARY, 0)
    _write_summary(o, view, f"{name} – Proje Takip Özeti", pl, False, None, with_montaj=False)
    return _finish(wb, [NAVY, "2E75B6"])


def build_fastener_order(db: Session, view: ProjectView) -> Workbook:
    """Fastener order form: item, standard, size, need, spare %, order qty, unit, unit price, amount."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_ORDER
    lists = _Lists(wb, _lists(db), *_temin_groups(db))
    last = _write_fastener_summary(
        ws, view, lists, None, f"{_name(view.project)} – Bağlantı Elemanı Sipariş Formu",
        "Sipariş Miktarı = İhtiyaç + yedek (yukarı yuvarlanır); Tutar = Sipariş Miktarı × Birim Fiyat. "
        "Satın alınan montajların içindekiler hariç.")
    c = {h: L(i) for h, i in FC.items()}
    tr = last + 2
    ws.cell(tr, FC[H_ORDER_QTY] - 1, "TOPLAM").font = _f(bold=True)
    ws.cell(tr, FC[H_ORDER_QTY], f"=SUM({c[H_ORDER_QTY]}{HR + 1}:{c[H_ORDER_QTY]}{last})").font = _f(bold=True)
    amt = ws.cell(tr, FC[H_AMOUNT], f"=SUM({c[H_AMOUNT]}{HR + 1}:{c[H_AMOUNT]}{last})")
    amt.font, amt.number_format = _f(bold=True), "#,##0.00"
    return _finish(wb, [NAVY])


def to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    xlsafe.neutralize(wb).save(buf)
    return buf.getvalue()


EXPORT_KINDS = {"parca-takip": "Parça_Takip", "takip-listesi": "Takip_Listesi",
                "baglanti-siparis": "Bağlantı_Sipariş_Formu", "gorunen": "Parça_Takip_Görünen"}


def export_filename(project: Project, kind: str) -> str:
    base = re.sub(r'[\\/:*?"<>|\s]+', "_", _name(project)).strip("_") or "proje"
    return f"{base}_{EXPORT_KINDS.get(kind, kind)}.xlsx"


def content_disposition(filename: str) -> str:
    """attachment header with an ASCII fallback and the UTF-8 name (RFC 5987/6266)."""
    tr = str.maketrans("çğıİöşüÇĞÖŞÜ", "cgiIosuCGOSU")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename.translate(tr))
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
