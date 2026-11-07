"""Montaj föyü PDF: plan, pick list, sheets and drawings in one black and white file.

ReportLab draws the pages, pypdf joins them with the drawings, then one last pass stamps the footer so "Sayfa X / N"
counts the drawing pages too. DejaVu is embedded so ☐ and ☒ print as plain glyphs, never as colour emoji.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing as Shape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from ..core import assembly as core
from ..core.assembly import EPS, Doc, Foy, Row
from ..core.i18n import tx
from ..models import AssemblyPlan, Drawing
from . import assembly_marks as marks
from .assembly import Context, pick_drawing, uses_text
from .assembly_excel import CHECKED, EMPTY, fastener_title, footer_title, legend, step_info, step_title

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
BLACK = colors.black
MARGIN = 10 * mm
BOTTOM = 14 * mm
PAGE_W = A4[0] - 2 * MARGIN
MAX_RASTER_DPI = 200
LABEL_W, LABEL_H = 70 * mm, 37 * mm
LABEL_COLS, LABEL_ROWS = 3, 8
FRONT_QR = 20 * mm
FRONT_CLEAR = 2                 # empty millimetres kept around a code on a drawing
FRONT_EDGE_X, FRONT_EDGE_Y = 8, 10   # printers lose the page edge, and the footer takes the bottom
INK = 245


@lru_cache(maxsize=1)
def _fonts() -> None:
    for name, file in (("Dj", "DejaVuSans.ttf"), ("Dj-B", "DejaVuSans-Bold.ttf"), ("Dj-I", "DejaVuSans-Oblique.ttf"),
                       ("Dj-BI", "DejaVuSans-BoldOblique.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))
    pdfmetrics.registerFontFamily("Dj", normal="Dj", bold="Dj-B", italic="Dj-I", boldItalic="Dj-BI")


def _style(size: float = 8, font: str = "Dj", **k: Any) -> ParagraphStyle:
    return ParagraphStyle("s", fontName=font, fontSize=size, leading=size * 1.18, textColor=BLACK, **k)


def _p(text: Any, size: float = 8, font: str = "Dj", **k: Any) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")).replace("\n", "<br/>"), _style(size, font, **k))


def _grid(extra: list[tuple] | None = None) -> TableStyle:
    return TableStyle([("GRID", (0, 0), (-1, -1), 0.4, BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                       ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                       ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                       ("LINEABOVE", (0, 0), (-1, 0), 1.1, BLACK), ("LINEBELOW", (0, 0), (-1, 0), 1.1, BLACK),
                       ("BOX", (0, 0), (-1, -1), 1.1, BLACK), *(extra or [])])


def _widths(parts: list[float]) -> list[float]:
    total = sum(parts)
    return [PAGE_W * w / total for w in parts]


def _lines(count: int, height: float = 6 * mm) -> Table:
    t = Table([[""] for _ in range(count)], colWidths=[PAGE_W], rowHeights=[height] * count)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, BLACK)]))
    return t


def _doc(buffer: BytesIO, later_header: Any = None) -> BaseDocTemplate:
    d = BaseDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=BOTTOM)
    first = Frame(MARGIN, BOTTOM, PAGE_W, A4[1] - MARGIN - BOTTOM, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    later = Frame(MARGIN, BOTTOM, PAGE_W, A4[1] - MARGIN - BOTTOM - 9 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    d.addPageTemplates([PageTemplate("first", [first]), PageTemplate("later", [later], onPage=later_header or (lambda c, _d: None))])
    return d


def _plan_story(ctx: Context, plan: AssemblyPlan, doc: Doc) -> list[Any]:
    story: list[Any] = [_p(tx("GÜNLÜK MONTAJ PLANI"), 15, "Dj-B", alignment=TA_CENTER), Spacer(1, 2),
                        _p(tx("Proje: {0}", ctx.project.name) + (f" ({ctx.project.root_part_no})" if ctx.project.root_part_no else ""), 10, alignment=TA_CENTER),
                        Spacer(1, 8)]
    info = [[_p(tx("Tarih"), 9, "Dj-B"), _p(plan.plan_date.strftime("%d.%m.%Y"), 9), _p(tx("Not:"), 9, "Dj-B"), _p(plan.notes, 8)],
            [_p(tx("Montaj sorumlusu"), 9, "Dj-B"), _p(plan.responsible, 9), "", ""],
            [_p(tx("Kontrol eden"), 9, "Dj-B"), _p(plan.checker, 9), "", ""]]
    t = Table(info, colWidths=_widths([22, 28, 7, 43]), rowHeights=[7 * mm] * 3)
    t.setStyle(TableStyle([("LINEBELOW", (1, 0), (1, 2), 0.5, BLACK), ("SPAN", (3, 0), (3, 2)), ("SPAN", (2, 0), (2, 2)),
                           ("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("VALIGN", (2, 0), (3, 2), "TOP")]))
    story += [t, Spacer(1, 6), _p(tx("Hazır ve eksik kalemler parça adetlerinden, rezervasyon sırasına göre hesaplanır. Plan no: {0}", plan.no), 7, "Dj-I"), Spacer(1, 4)]
    head = [_p(h, 6.5, "Dj-B", alignment=TA_CENTER) for h in (tx("No"), tx("Montaj / Parça No"), tx("Tanım"), tx("Montaj Adedi"), tx("Parça Çeşidi"), tx("Toplam Parça"),
                                                            tx("Hazır Kalem"), tx("Eksik Kalem"), tx("Başlangıç"), tx("Bitiş"), f"{tx('Tamamlandı')} ☐", tx("İmza"))]
    rows = [head]
    sums = [0.0] * 5
    for i, f in enumerate(doc.foys, 1):
        note = tx("Tekil parça – ana montaja doğrudan takılır") if f.single else (core.extra_shortage_text(doc, f) or f.name)
        ready = sum(1 for x in f.part_rows if x.state == core.READY)
        kinds = len({x.part_no for x in f.part_rows})
        total = sum(x.need for x in f.part_rows)
        vals = (f.qty, kinds, total, ready, len(f.part_rows) - ready)
        sums = [a + b for a, b in zip(sums, vals)]
        rows.append([_p(i, 8, alignment=TA_CENTER), _p(f.part_no, 7.5, "Dj-B"), _p(note, 6.5, "Dj-I"), _p(core.n(f.qty), 10, "Dj-B", alignment=TA_CENTER),
                     _p(kinds, 8, alignment=TA_CENTER), _p(core.n(total), 8, alignment=TA_CENTER), _p(ready, 8, alignment=TA_CENTER),
                     _p(vals[4], 10, "Dj-B", alignment=TA_CENTER), "", "", _p(CHECKED if f.done else EMPTY, 13, alignment=TA_CENTER), ""])
    rows.append(["", "", _p(tx("TOPLAM"), 8, "Dj-B", alignment=2), *[_p(core.n(v), 8, "Dj-B", alignment=TA_CENTER) for v in sums], "", "", "", ""])
    t = Table(rows, colWidths=_widths([4, 21, 16, 8, 8, 8, 8, 8, 10, 8, 14, 12]), repeatRows=1, rowHeights=[None] + [9 * mm] * len(doc.foys) + [6 * mm])
    t.setStyle(_grid())
    story += [t, Spacer(1, 10), _p(tx("Genel notlar:"), 9, "Dj-B"), _lines(5)]
    return story


def _pick_story(plan: AssemblyPlan, doc: Doc) -> list[Any]:
    story: list[Any] = [_p(tx("MALZEME TOPLAMA LİSTESİ"), 15, "Dj-B", alignment=TA_CENTER), Spacer(1, 2),
                        _p(tx("Plandaki montajlar için toplanacak parçalar. Gerekli − Hazır = Eksik."), 7, "Dj-I", alignment=TA_CENTER), Spacer(1, 6)]
    t = Table([[_p(f"{tx('Tarih:')} {plan.plan_date.strftime('%d.%m.%Y')}", 9, "Dj-B"), _p(tx("Toplayan:"), 9, "Dj-B"), ""]], colWidths=_widths([30, 12, 58]))
    t.setStyle(TableStyle([("LINEBELOW", (2, 0), (2, 0), 0.5, BLACK)]))
    story += [t, Spacer(1, 6)]
    head = [_p(h, 6.5, "Dj-B", alignment=TA_CENTER) for h in (tx("No"), tx("Parça No"), tx("Temin"), tx("Malzeme"), tx("Rev"), tx("Kullanıldığı Montaj (1 montaj için adet)"),
                                                            tx("Toplam Gerekli"), tx("Hazır"), tx("Eksik"), f"{tx('Toplandı')} ☐", tx("Durum"))]
    rows = [head]
    for i, p in enumerate(doc.picks, 1):
        short = "✓" if p.short <= EPS else core.n(p.short)
        rows.append([_p(i, 7, alignment=TA_CENTER), _p(p.part_no, 7.5, "Dj-B"), _p(p.procurement or tx("Belirtilmemiş"), 6.5), _p(p.material or "—", 6),
                     _p(p.rev or "—", 7, alignment=TA_CENTER), _p(uses_text(p), 6), _p(core.n(p.need), 9, "Dj-B", alignment=TA_CENTER),
                     _p(core.n(p.ready), 8, alignment=TA_CENTER), _p(short, 9, "Dj-B", alignment=TA_CENTER), _p(EMPTY, 12, alignment=TA_CENTER), _p(p.status, 6)])
    rows.append(["", "", "", "", "", _p(tx("TOPLAM PARÇA"), 8, "Dj-B", alignment=2), _p(core.n(doc.pick_total), 9, "Dj-B", alignment=TA_CENTER),
                 _p(core.n(sum(p.ready for p in doc.picks)), 9, "Dj-B", alignment=TA_CENTER), _p(core.n(sum(p.short for p in doc.picks)), 9, "Dj-B", alignment=TA_CENTER), "", ""])
    t = Table(rows, colWidths=_widths([4, 21, 13, 15, 5.5, 28, 9, 8, 8, 10, 18]), repeatRows=1)
    t.setStyle(_grid())
    story.append(t)
    return story


def _foy_header(f: Foy, plan: AssemblyPlan) -> Table:
    qty = Table([[_p(core.n(f.qty), 18, "Dj-B", alignment=TA_CENTER)]], colWidths=[24 * mm], rowHeights=[11 * mm])
    qty.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    rows = [[_p(tx("MONTAJ FÖYÜ"), 8, "Dj-B"), "", ""],
            [_p(f.part_no, 18, "Dj-B"), _p(tx("Montaj adedi:"), 8, "Dj-B", alignment=2), qty],
            [_p(f"{tx('Tanım')}: {f.name}", 8), "", _p(f"{tx('Plan no')}: {plan.no}", 8)],
            [_p(f"{tx('Montaj Rev')}: {f.rev or '-'}", 8), _p(f"{tx('Tarih')}: {plan.plan_date.strftime('%d.%m.%Y')}", 8), _p(f"{tx('Föy no')}: P{plan.id}-{f.item_id}", 8)]]
    t = Table(rows, colWidths=[PAGE_W - 58 * mm, 30 * mm, 28 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


def _row_cells(r: Row) -> list[Any]:
    bold = "Dj-B" if r.is_sub else "Dj"
    box = core.RUNNING if r.state == core.PARTIAL else r.state

    def tick(state: str) -> Paragraph:
        if r.is_sub:
            return _p("—", 8, alignment=TA_CENTER)
        return _p(CHECKED if box == state else EMPTY, 11, alignment=TA_CENTER)
    notes = "; ".join(f"<b><i>{escape(x['text'])}</i></b>" if x["warn"] else f"<i>{escape(x['text'])}</i>" for x in r.notes)
    return [_p(r.poz, 7.5, alignment=TA_CENTER), _p(r.part_no, 8, bold), _p(tx("Alt montaj") if r.is_sub else r.procurement or tx("Belirtilmemiş"), 6.5, bold),
            _p(r.material or "—", 5.5), _p(r.rev or "—", 7, alignment=TA_CENTER), _p(core.n(r.qty), 8, alignment=TA_CENTER),
            _p(core.n(r.need), 8, "Dj-B", alignment=TA_CENTER), tick(core.READY), tick(core.RUNNING), tick(core.MISSING),
            _p(CHECKED if r.mounted else EMPTY, 11, alignment=TA_CENTER), Paragraph(notes, _style(5.8))]


def _step_table(s: core.Step) -> list[Any]:
    title = Table([[_p(step_title(s), 9, "Dj-B"), _p(step_info(s), 6.5, "Dj-I"),
                    _p(f"{tx('Yapılacak:')} {core.n(s.make)} {tx('adet')} {CHECKED if s.done else EMPTY}", 8.5, "Dj-B", alignment=TA_CENTER)]],
                  colWidths=_widths([50, 28, 22]))
    title.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.1, BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    head = [_p(h, 5.5, "Dj-B", alignment=TA_CENTER) for h in (tx("Poz"), tx("Parça No"), tx("Temin"), tx("Malzeme"), tx("Rev"), tx("Adet\n(bu montaja)"), tx("Toplam\nGerekli"),
                                                            tx("Üretildi\n/ Geldi"), tx("Üretimde\n/ Siparişte"), tx("Üretilmedi\n/ Gelmedi"), tx("Montajlandı\n/ Takıldı"), tx("Not"))]
    t = Table([head] + [_row_cells(r) for r in s.rows], colWidths=_widths([5, 20, 12, 13, 4, 7.5, 7.5, 9.5, 9.5, 9.5, 10.5, 18.5]), repeatRows=1)
    t.setStyle(_grid([("LINEBEFORE", (10, 0), (10, -1), 1.1, BLACK)]))
    return [KeepTogether([title, t]) if len(s.rows) <= 12 else title, *([] if len(s.rows) <= 12 else [t]), Spacer(1, 5)]


def _qr(url: str, size: float = 15 * mm) -> Shape:
    w = QrCodeWidget(url, barLevel="M", barFillColor=BLACK)
    x0, y0, x1, y1 = w.getBounds()
    d = Shape(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(w)
    return d


@dataclass
class Attached:
    part_no: str
    step_no: int
    step_total: int
    drawing: Drawing | None
    warning: str
    path: Path | None


def _attachments(ctx: Context, f: Foy) -> list[Attached]:
    out: list[Attached] = []
    seen: set[str] = set()
    for s in f.steps:
        for r in s.rows:
            part = ctx.cat.get(r.part_no)
            if r.is_sub or r.part_no in seen or part is None or not (part.needs_drawing or r.kind == core.KIND_IMALAT):
                continue
            seen.add(r.part_no)
            d, warning = pick_drawing(ctx, r.part_no)
            if d is None:
                continue
            v = next((x for x in d.versions if x.version_no == d.current_version), None)
            path = Path(v.storage_path) if v is not None and d.ext.lower().lstrip(".") == "pdf" else None
            out.append(Attached(r.part_no, s.no, s.total, d, warning, path if path is not None and path.exists() else None))
    return out


def _list_story(ctx: Context, atts: list[Attached], base_url: str) -> list[Any]:
    if not atts:
        return []
    head = [_p(h, 7, "Dj-B", alignment=TA_CENTER) for h in (tx("Parça No"), tx("Resim dosyası"), tx("Rev"), "QR")]
    rows = [head]
    for a in atts:
        name = a.drawing.filename + (f" – {a.warning}" if a.warning else "")
        url = f"{base_url}/p/{ctx.project.id}/drawings?q={a.part_no}"
        rows.append([_p(a.part_no, 8, "Dj-B"), _p(name, 7), _p(a.drawing.rev or "—", 8, alignment=TA_CENTER), _qr(url)])
    t = Table(rows, colWidths=_widths([25, 50, 7, 18]), repeatRows=1)
    t.setStyle(_grid())
    return [Spacer(1, 6), _p(tx("Teknik resim listesi"), 9, "Dj-B"), Spacer(1, 2), t]


def _foy_pdf(ctx: Context, plan: AssemblyPlan, f: Foy, atts: list[Attached], base_url: str) -> bytes:
    def later(c: Canvas, _d: Any) -> None:
        c.setFont("Dj-B", 9)
        c.drawString(MARGIN, A4[1] - MARGIN - 4 * mm, f"{tx('MONTAJ FÖYÜ')}: {f.part_no} – {tx('devam')}")
        c.setFont("Dj", 8)
        c.drawRightString(A4[0] - MARGIN, A4[1] - MARGIN - 4 * mm, f"{tx('Montaj adedi:')} {core.n(f.qty)}  {plan.plan_date.strftime('%d.%m.%Y')}")
        c.setLineWidth(1)
        c.line(MARGIN, A4[1] - MARGIN - 6 * mm, A4[0] - MARGIN, A4[1] - MARGIN - 6 * mm)

    story: list[Any] = [NextPageTemplate("later"), _foy_header(f, plan), Spacer(1, 3), _p(legend(), 6.5, "Dj-I"), Spacer(1, 4)]
    for s in f.steps:
        story += _step_table(s)
    sign = Table([[_p(tx("Montajı yapan"), 8, "Dj-B"), "", _p(tx("Kontrol eden"), 8, "Dj-B"), "", _p(tx("Tamamlanma saati"), 8, "Dj-B")],
                  ["", "", "", "", ""],
                  [_p(tx("Ad Soyad / İmza"), 6, "Dj-I"), "", _p(tx("Ad Soyad / İmza"), 6, "Dj-I"), "", _p(tx("Saat"), 6, "Dj-I")]],
                 colWidths=_widths([32, 3, 32, 3, 30]), rowHeights=[None, 7 * mm, None])
    sign.setStyle(TableStyle([("LINEBELOW", (0, 1), (0, 1), 0.5, BLACK), ("LINEBELOW", (2, 1), (2, 1), 0.5, BLACK), ("LINEBELOW", (4, 1), (4, 1), 0.5, BLACK)]))
    fast = [_p(fastener_title(f), 6.5, "Dj-I")]
    if f.fasteners:
        fast.append(_p(", ".join(f.fasteners), 6.5))
    story.append(KeepTogether([*fast, _lines(2, 5 * mm), Spacer(1, 3), _p(tx("Montaj notları / uygunsuzluklar:"), 8, "Dj-B"), _lines(3, 5 * mm), Spacer(1, 4), sign]))
    if plan.drawing_mode in (core.DRAWING_LIST, core.DRAWING_BOTH):
        story += _list_story(ctx, atts, base_url)
    out = BytesIO()
    _doc(out, later).build(story)
    return out.getvalue()


def _has_colour(page: Any) -> bool:
    img = page.render(scale=0.5).to_pil().convert("HSV")
    h = img.split()[1].histogram()
    return sum(h[48:]) > 8


def _black_and_white(data: bytes) -> bytes:
    """A drawing with colour in it goes in as a grayscale image; a black one stays vector and sharp."""
    src = pdfium.PdfDocument(data)
    if not any(_has_colour(src[i]) for i in range(len(src))):
        return data
    out = BytesIO()
    c: Canvas | None = None
    for i in range(len(src)):
        page = src[i]
        w, h = page.get_size()
        scale = min(MAX_RASTER_DPI / 72, 5000 / max(w, h))
        img: Image.Image = page.render(scale=scale, grayscale=True).to_pil().convert("L")
        c = c or Canvas(out, pagesize=(w, h))
        c.setPageSize((w, h))
        c.drawImage(ImageReader(img), 0, 0, w, h)
        c.showPage()
    assert c is not None
    c.save()
    return out.getvalue()


def _overlay(w: float, h: float, footer: str, number: str, stamp: str) -> Any:
    buf = BytesIO()
    c = Canvas(buf, pagesize=(w, h))
    if stamp:
        c.setFillColor(colors.white)
        width = pdfmetrics.stringWidth(stamp, "Dj-B", 8) + 8
        c.rect(6 * mm, h - 6 * mm - 12, width, 13, stroke=1, fill=1)
        c.setFillColor(BLACK)
        c.setFont("Dj-B", 8)
        c.drawString(6 * mm + 4, h - 6 * mm - 8, stamp)
        c.setFillColor(colors.white)
        c.rect(0, 0, w, 6 * mm + 3, stroke=0, fill=1)
    c.setFillColor(BLACK)
    c.setFont("Dj", 7)
    c.drawString(MARGIN, 6 * mm, footer)
    c.drawRightString(w - MARGIN, 6 * mm, number)
    c.showPage()
    c.save()
    return PdfReader(BytesIO(buf.getvalue())).pages[0]


# ---------- backs: printed double-sided, a QR page always lands on the back of the sheet before it ----------

def _size(page: Any) -> tuple[float, float]:
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    return (h, w) if (page.get("/Rotate") or 0) % 180 else (w, h)


def _blank(w: float = A4[0], h: float = A4[1]) -> Any:
    return PageObject.create_blank_page(width=w, height=h)


def _on_front(pages: list[tuple[Any, str]]) -> None:
    if len(pages) % 2:
        pages.append((_blank(), ""))


def _on_back(pages: list[tuple[Any, str]], page: Any) -> None:
    if len(pages) % 2 == 0:
        pages.append((_blank(*_size(page)), ""))
    pages.append((page, ""))


def _back_of_drawing(w: float, h: float, url: str, part_no: str, action: str, info: str) -> Any:
    """One large code in the middle of a page the size of the drawing."""
    _fonts()
    buf = BytesIO()
    c = Canvas(buf, pagesize=(w, h))
    size = min(70 * mm, w * 0.5, h * 0.5)
    renderPDF.draw(_qr(url, size), c, (w - size) / 2, (h - size) / 2)
    y = (h + size) / 2 + 8 * mm
    c.setFillColor(BLACK)
    c.setFont("Dj-B", 16)
    c.drawCentredString(w / 2, y, part_no)
    y = (h - size) / 2 - 8 * mm
    c.setFont("Dj-B", 11)
    c.drawCentredString(w / 2, y, tx("Bitince okutun: {0}", action))
    c.setFont("Dj", 8)
    c.drawCentredString(w / 2, y - 5 * mm, tx("Okutunca teknik resimle birlikte onay ekranı açılır."))
    if info:
        c.drawCentredString(w / 2, y - 9 * mm, info)
    c.showPage()
    c.save()
    return PdfReader(BytesIO(buf.getvalue())).pages[0]


def _title_top(cells: bytes, cols: int, rows: int) -> int:
    """The row of the title block's top line: the first long line in the lower sheet that starts at the right frame.
    The block's own cells can be empty, so they must not count as free room."""
    for y in range(int(rows * 0.6), rows):
        line = cells[y * cols:(y + 1) * cols]
        x = cols - 1
        while x > cols - 16 and not line[x]:
            x -= 1
        run = 0
        while x >= 0 and line[x]:
            run, x = run + 1, x - 1
        if run >= 40:
            return y
    return rows


def _free_spot(page: Any) -> tuple[float, float] | None:
    """Where a code fits on a drawing with nothing under it: the empty place nearest the bottom right corner, which is
    right above the title block. Only the lower right of the sheet counts, so a code never sits among the views."""
    w, h = page.get_size()
    gray = page.render(scale=min(150 / 72, 6000 / max(w, h)), grayscale=True).to_pil().convert("L")
    cols, rows = int(w / mm), int(h / mm)
    # One cell per millimetre; averaging keeps a single dark pixel above zero, so a thin line still marks its cell
    cells = gray.point(lambda v: 255 if v < INK else 0).resize((cols, rows), Image.BOX).tobytes()
    side = round(FRONT_QR / mm) + 2 * FRONT_CLEAR
    sums = [[0] * (cols + 1) for _ in range(rows + 1)]
    for y in range(rows):
        line, above, here = cells[y * cols:(y + 1) * cols], sums[y], sums[y + 1]
        for x in range(cols):
            here[x + 1] = here[x] + above[x + 1] - above[x] + (1 if line[x] else 0)
    right, bottom = cols - FRONT_EDGE_X - side, min(rows - FRONT_EDGE_Y, _title_top(cells, cols, rows)) - side
    spots = [(x, y) for y in range(int(rows * 0.4), bottom + 1) for x in range(cols // 2, right + 1)
             if sums[y + side][x + side] - sums[y][x + side] - sums[y + side][x] + sums[y][x] == 0]
    if not spots:
        return None
    x, y = min(spots, key=lambda s: (right - s[0]) ** 2 + (bottom - s[1]) ** 2)
    return (x + FRONT_CLEAR) * w / cols, h - (y + side - FRONT_CLEAR) * h / rows


def _free_spots(data: bytes) -> list[tuple[float, float] | None]:
    doc = pdfium.PdfDocument(data)
    return [_free_spot(doc[i]) for i in range(len(doc))]


def _put_qr(page: Any, url: str, spot: tuple[float, float]) -> None:
    """Stamp a code on an already upright page. The spot counts from the visible box, as the render that found it did."""
    buf = BytesIO()
    c = Canvas(buf, pagesize=(FRONT_QR, FRONT_QR))
    renderPDF.draw(_qr(url, FRONT_QR), c, 0, 0)
    c.showPage()
    c.save()
    box = page.cropbox
    page.merge_transformed_page(PdfReader(BytesIO(buf.getvalue())).pages[0],
                                Transformation().translate(float(box.left) + spot[0], float(box.bottom) + spot[1]))


def _cell(url: str, title: str, action: str, info: str = "") -> list[Any]:
    return [_qr(url, 32 * mm), Spacer(1, 1), _p(title, 8, "Dj-B", alignment=TA_CENTER), _p(action, 8, alignment=TA_CENTER),
            _p(info, 6.5, "Dj-I", alignment=TA_CENTER)]


def _code_pages(title: str, cells: list[list[Any]]) -> list[Any]:
    """A grid of codes on as many pages as it takes."""
    if not cells:
        return []
    rows = [(cells[i:i + 3] + [[], []])[:3] for i in range(0, len(cells), 3)]
    t = Table(rows, colWidths=_widths([1, 1, 1]))
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, BLACK), ("INNERGRID", (0, 0), (-1, -1), 0.5, BLACK), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    buf = BytesIO()
    _doc(buf).build([_p(title, 11, "Dj-B", alignment=TA_CENTER), _p(tx("Okutunca teknik resimle birlikte onay ekranı açılır."), 8, alignment=TA_CENTER),
                     Spacer(1, 6), t])
    return list(PdfReader(BytesIO(buf.getvalue())).pages)


def _part_cell(ctx: Context, plan: AssemblyPlan, part_no: str, base_url: str) -> list[Any]:
    return _cell(marks.plan_part_url(base_url, plan.id, part_no), part_no, tx(marks.done_label(ctx, part_no)))


def _foy_back(ctx: Context, plan: AssemblyPlan, f: Foy, base_url: str, drawn: set[str]) -> list[Any]:
    cells = [_cell(marks.step_url(base_url, plan.id, f.item_id, s.no), s.part_no, tx("Montaj tamam"), tx("ADIM {0}/{1}", s.no, s.total)) for s in f.steps]
    parts = dict.fromkeys(r.part_no for r in f.part_rows if r.part_no not in drawn)
    cells += [_part_cell(ctx, plan, p, base_url) for p in parts]
    return _code_pages(f"{tx('MONTAJ FÖYÜ')}: {f.part_no}", cells)


def build(ctx: Context, plan: AssemblyPlan, doc: Doc, base_url: str, only: str | None = None, qr: str = "back") -> bytes:
    """The whole plan, or with `only` one föy with its drawings. `qr` is "back" for double-sided printing; "front" prints
    single-sided with the code on the drawing, or on the next page when the drawing has no empty place; "none" has no codes."""
    _fonts()
    backs, codes = qr == "back", qr != "none"
    pages: list[tuple[Any, str]] = []
    stamps: dict[int, tuple[str, tuple[float, float]]] = {}

    def place(page: Any) -> None:
        if backs:
            _on_back(pages, page)
        else:
            pages.append((page, ""))

    if only is None:
        front = BytesIO()
        d = _doc(front)
        d.build([*_plan_story(ctx, plan, doc), PageBreak(), *_pick_story(plan, doc)])
        pages += [(p, "") for p in PdfReader(BytesIO(front.getvalue())).pages]
        singles = dict.fromkeys(r.part_no for f in doc.foys if f.single for r in f.part_rows)
        for back in _code_pages(tx("Tekil parçalar"), [_part_cell(ctx, plan, p, base_url) for p in singles]) if codes else []:
            place(back)
    for f in doc.foys:
        if f.single or (only is not None and f.part_no != only):
            continue
        atts = _attachments(ctx, f) if plan.drawing_mode != core.DRAWING_NONE else []
        sheets: list[tuple[Attached, Any, list[tuple[float, float] | None]]] = []
        if plan.drawing_mode in (core.DRAWING_PAGES, core.DRAWING_BOTH):
            for a in atts:
                if a.path is None:
                    continue
                try:
                    data = _black_and_white(a.path.read_bytes())
                    reader = PdfReader(BytesIO(data))
                    sheets.append((a, reader, _free_spots(data) if qr == "front" else [None] * len(reader.pages)))
                except Exception:  # a damaged drawing must not cost the whole document; the sheet still lists it
                    continue
        if backs:
            _on_front(pages)
        pages += [(p, "") for p in PdfReader(BytesIO(_foy_pdf(ctx, plan, f, atts, base_url))).pages]
        for back in _foy_back(ctx, plan, f, base_url, {s[0].part_no for s in sheets}) if codes else []:
            place(back)
        for a, reader, spots in sheets:
            stamp = f"{f.part_no} · {tx('ADIM {0}/{1}', a.step_no, a.step_total)} · {a.part_no}"
            url = marks.plan_part_url(base_url, plan.id, a.part_no)
            for p, spot in zip(reader.pages, spots):
                if backs:
                    _on_front(pages)
                if spot is not None:
                    stamps[len(pages)] = (url, spot)
                pages.append((p, stamp))
                if codes and spot is None:
                    place(_back_of_drawing(*_size(p), url, a.part_no, tx(marks.done_label(ctx, a.part_no)), tx("Plan {0}", plan.no)))
    if backs:
        _on_front(pages)
    writer = PdfWriter()
    title = footer_title(ctx)
    for i, (page, stamp) in enumerate(pages, 1):
        added = writer.add_page(page)
        added.transfer_rotation_to_content()
        w, h = float(added.mediabox.width), float(added.mediabox.height)
        added.merge_page(_overlay(w, h, title, tx("Sayfa {0} / {1}", i, len(pages)), stamp))
        if i - 1 in stamps:
            _put_qr(added, *stamps[i - 1])
    writer.add_metadata({"/Title": tx("Montaj planı {0}", plan.no)})
    return _write(writer, backs)


def _write(writer: PdfWriter, duplex: bool = True) -> bytes:
    if duplex:
        writer.create_viewer_preferences()
        writer.viewer_preferences.duplex = "/DuplexFlipLongEdge"
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def drawings_with_qr(ctx: Context, part_nos: list[str], base_url: str, front: bool = False) -> bytes | None:
    """The drawings in colour, each page with its code on the back, or with `front` on the page itself where it has an
    empty place and otherwise on the next page. None when no part has a PDF drawing."""
    _fonts()
    writer = PdfWriter()
    for part_no in dict.fromkeys(part_nos):
        if part_no not in ctx.cat:
            continue
        d, _ = pick_drawing(ctx, part_no)
        v = next((x for x in d.versions if x.version_no == d.current_version), None) if d is not None else None
        if d is None or v is None or d.ext.lower().lstrip(".") != "pdf" or not Path(v.storage_path).exists():
            continue
        try:
            data = Path(v.storage_path).read_bytes()
            sources = list(PdfReader(BytesIO(data)).pages)
            spots = _free_spots(data) if front else [None] * len(sources)
        except Exception:  # one damaged file must not cost the rest
            continue
        url = marks.part_url(base_url, ctx.project.id, part_no)
        for p, spot in zip(sources, spots):
            size = _size(p)
            added = writer.add_page(p)
            if spot is not None:
                added.transfer_rotation_to_content()
                _put_qr(added, url, spot)
            else:
                writer.add_page(_back_of_drawing(*size, url, part_no, tx(marks.done_label(ctx, part_no)), ctx.project.name))
    return _write(writer, not front) if len(writer.pages) else None


@dataclass
class Code:
    url: str
    title: str
    name: str
    action: str
    qty: float
    place: str


def plan_codes(ctx: Context, plan: AssemblyPlan, doc: Doc, base_url: str, only: str | None = None) -> list[Code]:
    """Every code of the plan or of one föy: each step, then each part once."""
    out: list[Code] = []
    seen: set[str] = set()

    def part(part_no: str, place: str) -> None:
        if part_no in seen:
            return
        seen.add(part_no)
        p = ctx.cat.get(part_no)
        pick = next((x for x in doc.picks if x.part_no == part_no), None)
        out.append(Code(marks.plan_part_url(base_url, plan.id, part_no), part_no, p.name if p is not None else "",
                        tx(marks.done_label(ctx, part_no)), pick.need + pick.extra if pick is not None else 0, place))

    for f in doc.foys:
        if only is not None and f.part_no != only:
            continue
        if f.single:
            for r in f.part_rows:
                part(r.part_no, tx("Tekil parçalar"))
            continue
        for s in f.steps:
            place = f"{f.part_no} · {tx('ADIM {0}/{1}', s.no, s.total)}"
            step_part = ctx.cat.get(s.part_no)
            out.append(Code(marks.step_url(base_url, plan.id, f.item_id, s.no), s.part_no, step_part.name if step_part is not None else "",
                            tx("Montaj tamam"), s.make, place))
            for r in s.rows:
                if not r.is_sub:
                    part(r.part_no, place)
    return out


def part_codes(ctx: Context, part_nos: list[str], base_url: str) -> list[Code]:
    """Codes of chosen parts, whatever their drawing is: a DWG, a picture or none at all."""
    return [Code(marks.part_url(base_url, ctx.project.id, p), p, ctx.cat[p].name, tx(marks.done_label(ctx, p)), ctx.totals.get(p, 0), ctx.project.name)
            for p in dict.fromkeys(part_nos) if p in ctx.cat]


def _text_on(c: Canvas, text: str, style: ParagraphStyle, x: float, top: float, width: float, height: float) -> float:
    """Draw what fits and return the y below it. Long part numbers wrap; a block that does not fit is left out."""
    p = Paragraph(escape(text), style)
    _, used = p.wrap(width, height)
    if used > height:
        return top
    p.drawOn(c, x, top - used)
    return top - used - 0.6 * mm


def _label(c: Canvas, code: Code, x: float, y: float) -> None:
    size = LABEL_H - 9 * mm
    renderPDF.draw(_qr(code.url, size), c, x + 5 * mm, y + 4.5 * mm)
    left = x + 5 * mm + size + 2 * mm
    width = x + LABEL_W - 4 * mm - left
    top = y + LABEL_H - 4 * mm
    bottom = y + 3 * mm
    top = _text_on(c, code.title, _style(8.5, "Dj-B"), left, top, width, top - bottom)
    top = _text_on(c, tx("Bitince okutun: {0}", code.action), _style(7, "Dj-B"), left, top, width, top - bottom)
    top = _text_on(c, f"{core.n(code.qty)} {tx('adet')} · {code.place}", _style(6), left, top, width, top - bottom)
    _text_on(c, code.name[:60], _style(6, "Dj-I"), left, top, width, top - bottom)


def labels(title: str, codes: list[Code]) -> bytes:
    """A4 sheets of 3 x 8 stickers of 70 x 37 mm: on the part, the box or an already printed drawing."""
    _fonts()
    buf = BytesIO()
    c = Canvas(buf, pagesize=A4)
    c.setTitle(title)
    per_page = LABEL_COLS * LABEL_ROWS
    gap = (A4[1] - LABEL_ROWS * LABEL_H) / 2
    for i, code in enumerate(codes):
        if i and i % per_page == 0:
            c.showPage()
        row, col = divmod(i % per_page, LABEL_COLS)
        x, y = col * LABEL_W, A4[1] - gap - (row + 1) * LABEL_H
        c.setStrokeColor(colors.lightgrey)
        c.setLineWidth(0.25)
        c.rect(x, y, LABEL_W, LABEL_H)
        _label(c, code, x, y)
    c.save()
    return buf.getvalue()


def code_list(title: str, codes: list[Code]) -> bytes:
    """One table to keep beside the work: the drawings stay as they are and need no second side."""
    _fonts()
    head = [_p(h, 7, "Dj-B", alignment=TA_CENTER) for h in ("QR", tx("Parça No"), tx("Adet"), tx("Bitince okutun"), tx("Yer"))]
    rows = [head] + [[_qr(c.url, 22 * mm), [_p(c.title, 9, "Dj-B"), _p(c.name, 7)], _p(core.n(c.qty), 9, alignment=TA_CENTER),
                      _p(f"{EMPTY} {c.action}", 8), _p(c.place, 7)] for c in codes]
    t = Table(rows, colWidths=_widths([15, 37, 8, 20, 20]), repeatRows=1)
    t.setStyle(_grid())
    buf = BytesIO()
    _doc(buf).build([_p(title, 11, "Dj-B", alignment=TA_CENTER), _p(tx("Okutunca teknik resimle birlikte onay ekranı açılır."), 8, alignment=TA_CENTER),
                     Spacer(1, 6), t])
    return buf.getvalue()


def codes_pdf(layout: str, title: str, codes: list[Code]) -> bytes:
    return labels(title, codes) if layout == "labels" else code_list(title, codes)
