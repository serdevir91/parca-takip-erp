"""Montaj föyü workbook: three sheets laid out like the hand-made reference, and reading an edited copy back.

Column N on the föy sheet (and the last column on the others) is hidden and tags rows, so reading back does not depend
on the language the file was written in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter as col_letter
from openpyxl.worksheet.pagebreak import Break

from ..core import assembly as core
from ..core.assembly import EPS, Doc, Foy, Sheet, SheetPick, SheetRow
from ..core.i18n import tx
from ..models import AssemblyPlan
from . import xlsafe
from .assembly import Context, uses_text

FONT = "Arial"
MARK = "LABERP-ASSEMBLY"
THIN = Side(style="thin", color="000000")
MEDIUM = Side(style="medium", color="000000")
HAIR = Side(style="hair", color="000000")
ALL_THIN = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TICK_FONT = Font(name="Segoe UI Symbol", size=15)
CHECKED, EMPTY = "☒", "☐"
NC = 12


def footer_title(ctx: Context) -> str:
    root = ctx.project.root_part_no or ""
    prefix = root.split("_")[0] if "_" in root else ctx.project.name
    return f"{prefix} – {tx('Günlük Montaj')}"


def _font(**k: Any) -> Font:
    return Font(name=FONT, **{"size": 10, **k})


def _box(ws: Any, rng: str, side: Side = MEDIUM) -> None:
    rows = ws[rng]
    for i, row in enumerate(rows):
        for j, c in enumerate(row):
            b = c.border
            c.border = Border(left=side if j == 0 else b.left, right=side if j == len(row) - 1 else b.right,
                              top=side if i == 0 else b.top, bottom=side if i == len(rows) - 1 else b.bottom)


def _page(ws: Any, title: str) -> None:
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top, ws.page_margins.bottom = 0.5, 0.6
    ws.oddFooter.left.text = title.replace("&", "&&")
    ws.oddFooter.right.text = tx("Sayfa {0} / {1}", "&P", "&N")
    ws.oddFooter.left.size = ws.oddFooter.right.size = 8
    ws.sheet_view.showGridLines = False


def _head(ws: Any, r: int, cols: list[str]) -> None:
    for i, h in enumerate(cols, 1):
        c = ws.cell(r, i, h)
        c.font = _font(bold=True, size=9)
        c.border = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r].height = 30


def _tick(c: Any, on: bool) -> None:
    c.value = CHECKED if on else EMPTY
    c.font = TICK_FONT
    c.alignment = Alignment(horizontal="center", vertical="center")


def _q(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _num(v: float) -> int | float:
    return int(v) if abs(v - round(v)) < EPS else v


def _plan_sheet(ws: Any, ctx: Context, plan: AssemblyPlan, doc: Doc) -> dict[int, int]:
    for col, w in zip("ABCDEFGHIJKL", [5, 17, 24, 8, 8, 8, 8, 8, 9, 9, 10, 14]):
        ws.column_dimensions[col].width = w
    ws.merge_cells("A1:L1")
    ws["A1"] = tx("GÜNLÜK MONTAJ PLANI")
    ws["A1"].font = _font(bold=True, size=16)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A2:L2")
    ws["A2"] = tx("Proje: {0}", ctx.project.name) + (f" ({ctx.project.root_part_no})" if ctx.project.root_part_no else "")
    ws["A2"].font = _font(size=11)
    ws["A2"].alignment = Alignment(horizontal="center")
    info = [(tx("Tarih"), plan.plan_date.strftime("%d.%m.%Y")), (tx("Montaj sorumlusu"), plan.responsible), (tx("Kontrol eden"), plan.checker)]
    for i, (k, v) in enumerate(info):
        r = 4 + i
        ws.cell(r, 1, k).font = _font(bold=True)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=5)
        ws.cell(r, 3, v).font = _font(size=11)
        for cc in range(3, 6):
            ws.cell(r, cc).border = Border(bottom=THIN)
    ws["G4"] = tx("Not:")
    ws["G4"].font = _font(bold=True)
    ws.merge_cells("H4:L6")
    ws["H4"] = plan.notes
    ws["H4"].font = _font(size=9)
    ws["H4"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A8:L8")
    ws["A8"] = tx("Hazır ve eksik kalemler parça adetlerinden, rezervasyon sırasına göre hesaplanır. Plan no: {0}", plan.no)
    ws["A8"].font = _font(italic=True, size=8)
    ws["A8"].alignment = Alignment(wrap_text=True)
    head = 10
    _head(ws, head, [tx("No"), tx("Montaj / Parça No"), tx("Tanım"), tx("Montaj Adedi"), tx("Parça Çeşidi"), tx("Toplam Parça"),
                     tx("Hazır Kalem"), tx("Eksik Kalem"), tx("Başlangıç"), tx("Bitiş"), f"{tx('Tamamlandı')} ☐", tx("İmza")])
    rows: dict[int, int] = {}
    r = head + 1
    for i, f in enumerate(doc.foys, 1):
        note = tx("Tekil parça – ana montaja doğrudan takılır") if f.single else (core.extra_shortage_text(doc, f) or f.name)
        ready = sum(1 for x in f.part_rows if x.state == core.READY)
        vals = [i, f.part_no, note, _num(f.qty), len({x.part_no for x in f.part_rows}), None, ready,
                len(f.part_rows) - ready, None, None, None, None]
        for j, v in enumerate(vals, 1):
            c = ws.cell(r, j, v)
            c.border = ALL_THIN
            c.font = _font(size=10, bold=j == 2)
            c.alignment = Alignment(vertical="center", horizontal="center" if j in (1, 4, 5, 6, 7, 8) else "left", wrap_text=j == 3)
        ws.cell(r, 4).font = _font(bold=True, size=12)
        ws.cell(r, 8).font = _font(bold=True, size=12)
        if note and j:
            ws.cell(r, 3).font = _font(italic=True, size=8)
        _tick(ws.cell(r, 11), f.done)
        ws.cell(r, 13, f"I|{f.item_id}")
        ws.row_dimensions[r].height = 26
        rows[f.item_id] = r
        r += 1
    last = r - 1
    _box(ws, f"A{head}:L{last}")
    ws.cell(last + 1, 3, tx("TOPLAM")).font = _font(bold=True)
    ws.cell(last + 1, 3).alignment = Alignment(horizontal="right")
    for col in "DEFGH":
        c = ws[f"{col}{last + 1}"]
        c.value = f"=SUM({col}{head + 1}:{col}{last})"
        c.font = _font(bold=True)
        c.border = ALL_THIN
        c.alignment = Alignment(horizontal="center")
    ws.cell(last + 1, 13, "T")
    r = last + 3
    ws.cell(r, 1, tx("Genel notlar:")).font = _font(bold=True)
    for k in range(5):
        for cc in range(1, 13):
            ws.cell(r + 1 + k, cc).border = Border(bottom=HAIR)
        ws.row_dimensions[r + 1 + k].height = 20
    ws.column_dimensions["M"].hidden = True
    return rows


def _foy_block(ws: Any, r: int, f: Foy, plan: AssemblyPlan, plan_ref: str, plan_row: int, cols: list[str],
               cells: dict[tuple[int, str, str], int]) -> int:
    top = r
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=NC)
    ws.cell(r, 1, tx("MONTAJ FÖYÜ")).font = _font(bold=True, size=9)
    ws.cell(r, 14, f"I|{f.item_id}")
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
    c = ws.cell(r, 1, f.part_no)
    c.font = _font(bold=True, size=20)
    c.alignment = Alignment(vertical="center")
    ws.row_dimensions[r].height = 34
    ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=7)
    ws.cell(r, 6, tx("Montaj adedi:") + "  ").font = _font(bold=True, size=9)
    ws.cell(r, 6).alignment = Alignment(horizontal="right", vertical="center")
    ws.merge_cells(start_row=r, start_column=8, end_row=r, end_column=9)
    c = ws.cell(r, 8, f"={plan_ref}!D{plan_row}")
    c.font = _font(bold=True, size=20)
    c.alignment = Alignment(horizontal="center", vertical="center")
    _box(ws, f"H{r}:I{r}")
    qty_row = r
    r += 1
    for label, value in ((tx("Tanım"), f.name), (tx("Montaj Rev"), f.rev or "-"), (tx("Tarih"), plan.plan_date.strftime("%d.%m.%Y"))):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.cell(r, 1, label).font = _font(bold=True, size=9)
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=7)
        ws.cell(r, 3, value).font = _font()
        for cc in range(3, 8):
            ws.cell(r, cc).border = Border(bottom=THIN)
        r += 1
    _box(ws, f"A{top}:{col_letter(NC)}{r - 1}")
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=NC)
    c = ws.cell(r, 1, legend())
    c.font = _font(italic=True, size=8)
    c.alignment = Alignment(wrap_text=True)
    ws.row_dimensions[r].height = 22
    r += 1
    for s in f.steps:
        need = f"$H${qty_row}" if s.is_top else f"{_num(s.make / f.qty)}*$H${qty_row}"
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
        c = ws.cell(r, 1, step_title(s))
        c.font = _font(bold=True, size=12)
        c.alignment = Alignment(vertical="center")
        ws.merge_cells(start_row=r, start_column=8, end_row=r, end_column=11)
        c = ws.cell(r, 8, step_info(s))
        c.font = _font(size=8, italic=True)
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c = ws.cell(r, 12, f'="{tx("Yapılacak:")} "&{need}&" {tx("adet")}   {CHECKED if s.done else EMPTY}"')
        c.font = _font(bold=True, size=10)
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(r, 14, f"S|{s.no}")
        ws.row_dimensions[r].height = 30
        _box(ws, f"A{r}:{col_letter(NC)}{r}")
        r += 1
        _head(ws, r, cols)
        head = r
        r += 1
        for row in s.rows:
            vals = [row.poz, row.part_no, tx("Alt montaj") if row.is_sub else (row.procurement or tx("Belirtilmemiş")), row.material or "—",
                    row.rev or "—", _num(row.qty), f"={_num(row.qty)}*{need}"]
            for i, v in enumerate(vals, 1):
                c = ws.cell(r, i, v)
                c.font = _font(bold=row.is_sub or i == 7, size=8 if i == 4 else 10)
                c.alignment = Alignment(vertical="center", horizontal="center" if i in (1, 5, 6, 7) else "left", wrap_text=i in (3, 4))
            for cc in range(1, NC + 1):
                ws.cell(r, cc).border = ALL_THIN
            box = core.RUNNING if row.state == core.PARTIAL else row.state
            for cc, state in ((8, core.READY), (9, core.RUNNING), (10, core.MISSING)):
                if row.is_sub:
                    ws.cell(r, cc).value = "—"
                    ws.cell(r, cc).alignment = Alignment(horizontal="center", vertical="center")
                else:
                    _tick(ws.cell(r, cc), box == state)
            _tick(ws.cell(r, 11), row.mounted)
            ws.cell(r, 11).border = Border(left=MEDIUM, right=THIN, top=THIN, bottom=THIN)
            warn = any(x["warn"] for x in row.notes)
            note = "; ".join(x["text"] for x in row.notes)
            c = ws.cell(r, 12, note or None)
            c.font = _font(italic=True, bold=warn, size=8)
            c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.cell(r, 14, f"R|{row.part_no}")
            ws.row_dimensions[r].height = 26 if len(note) < 30 else 32 if len(note) < 70 else 44
            cells[(f.item_id, s.path, row.part_no)] = r
            r += 1
        _box(ws, f"A{head}:{col_letter(NC)}{r - 1}")
        r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=NC)
    ws.cell(r, 1, fastener_title(f)).font = _font(italic=True, size=8)
    r += 1
    for k in range(2):
        if k < len(f.fasteners):
            ws.cell(r, 1, ", ".join(f.fasteners[k::2])).font = _font(size=8)
        for cc in range(1, NC + 1):
            ws.cell(r, cc).border = Border(bottom=HAIR)
        ws.row_dimensions[r].height = 18
        r += 1
    ws.cell(r, 1, tx("Montaj notları / uygunsuzluklar:")).font = _font(bold=True, size=9)
    r += 1
    for _ in range(3):
        for cc in range(1, NC + 1):
            ws.cell(r, cc).border = Border(bottom=HAIR)
        ws.row_dimensions[r].height = 18
        r += 1
    r += 1
    for i, label in enumerate((tx("Montajı yapan"), tx("Kontrol eden"), tx("Tamamlanma saati"))):
        start, end = (1, 5, 10)[i], (3, 8, 12)[i]
        ws.cell(r, start, label).font = _font(bold=True, size=9)
        for cc in range(start, end + 1):
            ws.cell(r + 2, cc).border = Border(top=THIN)
        ws.cell(r + 2, start, tx("Ad Soyad / İmza") if i < 2 else tx("Saat")).font = _font(size=7, italic=True)
    ws.row_dimensions[r + 1].height = 26
    return r + 4


def legend() -> str:
    return tx("☒ = sistemdeki durum. İmalat parçası: Üretildi / Üretimde / Üretilmedi – Hazır alım: Geldi / Siparişte / Gelmedi. "
              "Alt montajlar önce yapılır; adım sırasını takip et.")


def step_title(s: core.Step) -> str:
    kind = tx("ANA MONTAJ") if s.is_top else tx("ALT MONTAJ")
    return f"{tx('ADIM {0}/{1}', s.no, s.total)}  –  {kind}: {s.part_no}"


def step_info(s: core.Step) -> str:
    if s.is_top:
        return tx("Son adım – alt montajlar ve parçalar buraya takılır")
    return tx("Takılacağı yer: {0}  ({1} adet / üst montaj)", s.parent, core.n(s.per_parent))


def fastener_title(f: Foy) -> str:
    if f.fasteners:
        return tx("Bağlantı elemanları (BOM'dan) – eklenenleri yaz:")
    return tx("Bağlantı elemanları (cıvata, pim, rondela) bu BOM'da yok – kullanılanları yaz:")


def _foy_sheet(ws: Any, plan: AssemblyPlan, doc: Doc, plan_ref: str, plan_rows: dict[int, int]) -> dict[tuple[int, str, str], int]:
    for col, w in zip("ABCDEFGHIJKL", [6, 24, 14, 18, 5, 8, 9, 10, 10, 10, 11, 24]):
        ws.column_dimensions[col].width = w
    cols = [tx("Poz"), tx("Parça No"), tx("Temin"), tx("Malzeme"), tx("Rev"), tx("Adet\n(bu montaja)"), tx("Toplam\nGerekli"), tx("Üretildi\n/ Geldi"),
            tx("Üretimde\n/ Siparişte"), tx("Üretilmedi\n/ Gelmedi"), tx("Montajlandı\n/ Takıldı"), tx("Not")]
    cells: dict[tuple[int, str, str], int] = {}
    r = 1
    for f in doc.foys:
        if f.single:
            continue
        if r > 1:
            ws.row_breaks.append(Break(id=r - 1))
        r = _foy_block(ws, r, f, plan, plan_ref, plan_rows[f.item_id], cols, cells)
    ws.column_dimensions["N"].hidden = True
    return cells


def _pick_sheet(ws: Any, ctx: Context, plan: AssemblyPlan, doc: Doc, plan_ref: str, foy_ref: str, plan_rows: dict[int, int],
                cells: dict[tuple[int, str, str], int]) -> None:
    for col, w in zip("ABCDEFGHIJK", [5, 18, 13, 17, 5, 34, 9, 9, 9, 9, 20]):
        ws.column_dimensions[col].width = w
    ws.merge_cells("A1:K1")
    ws["A1"] = tx("MALZEME TOPLAMA LİSTESİ")
    ws["A1"].font = _font(bold=True, size=16)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A2:K2")
    ws["A2"] = tx("Plandaki montajlar için toplanacak parçalar. Gerekli − Hazır = Eksik.")
    ws["A2"].font = _font(italic=True, size=8)
    ws["A2"].alignment = Alignment(horizontal="center", wrap_text=True)
    ws["A3"] = tx("Tarih:")
    ws["A3"].font = _font(bold=True)
    ws["B3"] = plan.plan_date.strftime("%d.%m.%Y")
    ws["D3"] = tx("Toplayan:")
    ws["D3"].font = _font(bold=True)
    for cc in "EF":
        ws[f"{cc}3"].border = Border(bottom=THIN)
    head = 5
    _head(ws, head, [tx("No"), tx("Parça No"), tx("Temin"), tx("Malzeme"), tx("Rev"), tx("Kullanıldığı Montaj (1 montaj için adet)"), tx("Toplam Gerekli"),
                     tx("Hazır"), tx("Eksik"), f"{tx('Toplandı')} ☐", tx("Durum")])
    r = head + 1
    for i, p in enumerate(doc.picks, 1):
        need: list[str] = []
        ready: list[str] = []
        loose = p.extra_ready
        for f in doc.foys:
            for x in f.part_rows:
                if x.part_no != p.part_no:
                    continue
                ref = f"{plan_ref}!D{plan_rows[f.item_id]}" if f.single else f"{foy_ref}!G{cells[(f.item_id, x.path, x.part_no)]}"
                need.append(ref)
                if x.state == core.READY:
                    ready.append(ref)
                else:
                    loose += min(x.allocated, x.need)
        extra = [str(_num(p.extra))] if p.extra else []
        total: Any = "=" + "+".join(need + extra) if need else _num(p.extra)
        got = ready + ([str(_num(loose))] if loose > EPS else [])
        have: Any = "=" + "+".join(got) if got else 0
        vals = [i, p.part_no, p.procurement or tx("Belirtilmemiş"), p.material or "—", p.rev or "—", uses_text(p), total, have, f"=G{r}-H{r}", None, p.status]
        for j, v in enumerate(vals, 1):
            c = ws.cell(r, j, v)
            c.border = ALL_THIN
            c.font = _font(size=8 if j in (4, 6, 11) else 10, bold=j in (2, 7, 9))
            c.alignment = Alignment(vertical="center", horizontal="center" if j in (1, 5, 7, 8, 9) else "left", wrap_text=j in (3, 4, 6, 11))
        ws.cell(r, 9).number_format = '0;-0;"✓"'
        ws.cell(r, 7).font = _font(bold=True, size=12)
        _tick(ws.cell(r, 10), False)
        ws.cell(r, 12, f"R|{p.part_no}")
        ws.row_dimensions[r].height = 26 if len(vals[5]) < 60 else 36
        r += 1
    last = r - 1
    _box(ws, f"A{head}:K{last}")
    ws.cell(last + 1, 6, tx("TOPLAM PARÇA")).font = _font(bold=True)
    ws.cell(last + 1, 6).alignment = Alignment(horizontal="right")
    for col in "GHI":
        c = ws[f"{col}{last + 1}"]
        c.value = f"=SUM({col}{head + 1}:{col}{last})"
        c.font = _font(bold=True, size=12)
        c.border = ALL_THIN
        c.alignment = Alignment(horizontal="center")
    ws.cell(last + 1, 12, "T")
    ws.print_title_rows = f"{head}:{head}"
    ws.column_dimensions["L"].hidden = True


def build(ctx: Context, plan: AssemblyPlan, doc: Doc) -> bytes:
    wb = Workbook()
    wb.properties.subject = f"{MARK}:{plan.id}"
    pl = wb.active
    pl.title = tx("Montaj Planı")[:31]
    tl = wb.create_sheet(tx("Toplama Listesi")[:31])
    fy = wb.create_sheet(tx("Montaj Föyleri")[:31])
    plan_rows = _plan_sheet(pl, ctx, plan, doc)
    plan_ref, foy_ref = _q(pl.title), _q(fy.title)
    cells = _foy_sheet(fy, plan, doc, plan_ref, plan_rows)
    _pick_sheet(tl, ctx, plan, doc, plan_ref, foy_ref, plan_rows, cells)
    for f in doc.foys:
        r = plan_rows[f.item_id]
        rows = [cells[(f.item_id, x.path, x.part_no)] for x in f.part_rows] if not f.single else []
        pl.cell(r, 6).value = f"=D{r}" if f.single else "=" + "+".join(f"{foy_ref}!G{x}" for x in rows) if rows else 0
    title = footer_title(ctx)
    for ws in (pl, tl, fy):
        _page(ws, title)
    out = BytesIO()
    wb = xlsafe.neutralize(wb)
    wb.save(out)
    return out.getvalue()


# ---------- reading an edited copy back ----------

@dataclass
class Returned:
    sheet: Sheet
    changes: list[dict[str, Any]]


def _is_marked(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return s in ("x", "X", "✓", "✔", "☑", CHECKED)


def _number(formulas: Any, values: Any, coord: str, fallback: float) -> float:
    """A typed number wins. A formula gives its saved result; a file nobody recalculated has none, so it means no change."""
    raw = formulas[coord].value
    if isinstance(raw, (int, float)):
        return float(raw)
    cached = values[coord].value
    if isinstance(cached, (int, float)):
        return float(cached)
    if isinstance(raw, str) and raw.strip().replace(",", ".").replace(".", "", 1).isdigit():
        return float(raw.replace(",", "."))
    return fallback


def read_back(data: bytes, plan: AssemblyPlan, doc: Doc) -> Returned:
    try:
        wf = load_workbook(BytesIO(data))
        wv = load_workbook(BytesIO(data), data_only=True)
    except Exception as e:  # openpyxl raises many kinds for a broken file
        raise HTTPException(400, tx("Excel dosyası okunamadı: {0}", e)) from e
    if len(wf.worksheets) < 3:
        raise HTTPException(400, tx("Bu dosya montaj föyü değil: üç sayfa bekleniyor"))
    subject = wf.properties.subject or ""
    if not subject.startswith(MARK):
        raise HTTPException(400, tx("Bu dosya montaj föyü değil"))
    if subject != f"{MARK}:{plan.id}":
        raise HTTPException(400, tx("Bu dosya başka bir plana ait"))
    pf, tf, ff = wf.worksheets[:3]
    pv, tv, fv = wv.worksheets[:3]
    changes: list[dict[str, Any]] = []
    picks: list[SheetPick] = []
    rows: list[SheetRow] = []
    seen_ready: dict[str, float] = {}
    pick_total = 0.0
    for r in range(1, tf.max_row + 1):
        tag = tf.cell(r, 12).value
        if not (isinstance(tag, str) and tag.startswith("R|")):
            continue
        part = tag[2:]
        base = doc.pick(part)
        if base is None:
            continue
        need = _number(tf, tv, f"G{r}", base.need)
        ready = _number(tf, tv, f"H{r}", base.ready)
        short = _number(tf, tv, f"I{r}", need - ready)
        found = re.search(r"\+\s*(\d+(?:[.,]\d+)?)\s*\S*\s*$", str(tf.cell(r, 6).value or ""))
        status = str(tf.cell(r, 11).value or "")
        picks.append(SheetPick(part, need, ready, short, status, float(found.group(1).replace(",", ".")) if found else None))
        pick_total += need
        seen_ready[part] = ready
        if abs(ready - base.ready) > EPS:
            changes.append({"type": "ready", "part_no": part, "old": base.ready, "new": ready})
    foy: Foy | None = None
    step: core.Step | None = None
    typed_parts = {c["part_no"] for c in changes}
    for r in range(1, ff.max_row + 1):
        tag = ff.cell(r, 14).value
        if not isinstance(tag, str):
            continue
        kind, _, val = tag.partition("|")
        if kind == "I":
            foy = next((f for f in doc.foys if str(f.item_id) == val), None)
            step = None
        elif kind == "S" and foy is not None:
            step = next((s for s in foy.steps if str(s.no) == val), None)
            if step is not None:
                text = str(fv.cell(r, 12).value or ff.cell(r, 12).value or "")
                done = CHECKED in text
                if done != step.done:
                    changes.append({"type": "step", "item_id": foy.item_id, "path": step.path, "part_no": step.part_no, "old": step.done, "new": done})
        elif kind == "R" and foy is not None and step is not None:
            row = next((x for x in step.rows if x.part_no == val), None)
            if row is None:
                continue
            mounted = _is_marked(ff.cell(r, 11).value)
            if mounted != row.mounted:
                changes.append({"type": "mounted", "item_id": foy.item_id, "path": step.path, "part_no": row.part_no, "old": row.mounted, "new": mounted})
            if row.is_sub:
                continue
            marked = [s for cc, s in ((8, core.READY), (9, core.RUNNING), (10, core.MISSING)) if _is_marked(ff.cell(r, cc).value)]
            box = marked[0] if len(marked) == 1 else ("multi" if marked else "")
            was = core.RUNNING if row.state == core.PARTIAL else row.state
            need = _number(ff, fv, f"G{r}", row.need)
            ready_qty = need if box == core.READY else min(row.allocated, row.need) if box == was else 0.0
            rows.append(SheetRow(foy.part_no, step.no, row.part_no, need, box, ready_qty))
            if box in (core.READY, core.RUNNING, core.MISSING) and box != was and row.part_no not in typed_parts:
                changes.append({"type": "state", "item_id": foy.item_id, "path": step.path, "part_no": row.part_no, "old": was, "new": box})
    for f in doc.foys:
        if f.single:
            x = f.rows[0]
            state = x.state
            rows.append(SheetRow(f.part_no, 1, x.part_no, x.need, core.RUNNING if state == core.PARTIAL else state, min(x.allocated, x.need)))
    total = 0.0
    for r in range(1, pf.max_row + 1):
        tag = pf.cell(r, 13).value
        if isinstance(tag, str) and tag.startswith("I|"):
            f = next((x for x in doc.foys if str(x.item_id) == tag[2:]), None)
            if f is not None:
                total += _number(pf, pv, f"F{r}", sum(x.need for x in f.part_rows))
    return Returned(Sheet(picks, rows, total, pick_total), changes)
