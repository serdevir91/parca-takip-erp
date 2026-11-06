"""Compare any spreadsheet with the project's parts (SPEC §9.1).

The file does not have to come from this system. Columns are guessed from their titles and from the
values under them, the result is a preview, and `excel_import.apply` writes what the user selects.
An export of this system is recognised by its 'Anahtar' column and goes through `excel_import.preview`.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from ..core.normalize import strip_cad_ext, tr_lower, tr_sort_key
from ..core.status import KIND_HAZIR, KIND_IMALAT, PROG_DONE, PROG_RUN, PROG_WAIT, PROGRESS_CHOICES
from ..core.xlsxguard import check_xlsx
from ..models import Project
from .excel_export import H_KEY, H_PNO, H_PROG
from .excel_import import KIND_TRACKING, Diff, ImportError_, _Ctx, _txt, preview
from app.core.i18n import tx

FILE_TYPES = (".xlsx", ".xlsm", ".xls", ".csv")
MAX_ROWS, MAX_COLS = 50_000, 200
HEADER_SCAN_ROWS = 30
DETECT_ROWS = 5_000
MIN_VALUES, MIN_RATIO = 3, 0.6            # a column without a known title needs this many known values

F_PART, F_STATUS, F_ORDER, F_TEMIN = "part_no", "status", "order", "temin"
TEXT_FIELDS = {"manufacturer": "manufacturer", "material_status": "material_status", "t35_note": "t35_note",
               "note": "note"}

HEADERS: dict[str, tuple[str, ...]] = {
    F_PART: ("parca no", "parca numarasi", "parca kodu", "parca kod", "stok kodu", "stok no", "malzeme kodu",
             "malzeme no", "urun kodu", "urun no", "resim no", "teknik resim no", "dosya adi", "part no",
             "part number", "part code", "item no", "item code", "item number", "kod", "kodu", "pn", "p n"),
    F_ORDER: ("siparis durumu", "siparis", "tedarik durumu", "satin alma durumu", "satinalma durumu", "order status",
              "purchase status"),
    F_STATUS: ("durum", "durumu", "ilerleme", "uretim durumu", "imalat durumu", "parca durumu", "is durumu", "uretim",
               "asama", "statu", "status", "state", "progress"),
    F_TEMIN: ("temin sekli", "temin turu", "temin", "tedarik sekli", "tedarik", "uretim sekli", "imalat sekli",
              "imalat turu", "islem", "operasyon", "proses", "process", "procurement", "make buy"),
    "material_status": ("malzeme durumu", "material status"),
    "t35_note": ("durum notu", "status note"),
    "manufacturer": ("uretici", "firma", "tedarikci", "fason firma", "manufacturer", "supplier", "vendor"),
    "note": ("not", "notlar", "aciklama", "note", "notes", "comment", "comments", "remark", "remarks"),
}
TITLE_FIELD = {t: f for f, titles in HEADERS.items() for t in titles}
TITLES_LONGEST = sorted((t for t in TITLE_FIELD if len(t) >= 5), key=len, reverse=True)

# Checked in this order, so a negative or future form wins over the word it contains
PROGRESS_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (PROG_WAIT, ("bekliyor", "beklemede", "bekleniyor", "uretilmedi", "uretilmemis", "verilmedi", "edilmedi",
                 "yapilmadi", "montajlanmadi", "baslanmadi", "baslamadi", "gelmedi", "alinmadi", "verilecek",
                 "edilecek", "yapilacak", "uretilecek", "alinacak", "kesilecek", "planlanacak", "planlandi", "yok",
                 "hayir", "no", "none", "pending", "waiting", "not started", "todo", "to do")),
    (PROG_DONE, ("tamam", "tamamlandi", "bitti", "bitmis", "uretildi", "uretilmis", "imal edildi", "islendi",
                 "yapildi", "teslim edildi", "teslim alindi", "teslim", "geldi", "alindi", "montajlandi",
                 "monte edildi", "kesildi", "bukuldu", "kaynatildi", "hazir", "stokta", "ok", "evet", "yes", "done",
                 "finished", "completed", "complete", "delivered", "received", "assembled", "produced")),
    (PROG_RUN, ("devam", "uretimde", "uretiliyor", "imalatta", "imal ediliyor", "isleniyor", "islemde", "kesimde",
                "bukumde", "kaynakta", "montajda", "boyada", "fasonda", "siparis", "yolda", "kargoda", "tedarik",
                "baslandi", "basladi", "in progress", "ongoing", "ordered", "on order", "wip", "started")),
)
CHECK_MARKS, CROSS_MARKS = "✓✔☑", "✗✘☒"

TEMIN_WORDS: dict[str, tuple[str, ...]] = {
    "Lazer Kesim": ("lazer", "laser", "lazer kesme", "laser cutting", "laser cut"),
    "Büküm": ("bukum", "bukme", "abkant", "bending"),
    "Kaynak": ("kaynak", "kaynakli", "welding"),
    "Talaşlı İmalat": ("talasli", "talasli imalat", "cnc", "torna", "tornalama", "freze", "frezeleme", "machining"),
    "Montaj": ("montaj", "assembly"),
    "Boya": ("boya", "boyama", "toz boya", "painting"),
    "Isıl İşlem": ("isil islem", "heat treatment"),
    KIND_IMALAT: ("imalat", "uretim", "manufacturing", "make"),
    KIND_HAZIR: ("hazir", "hazir alim", "satin alma", "satinalma", "satin alinacak", "ticari", "katalog", "buy",
                 "purchase", "purchased"),
    "Fason İmalat": ("fason", "fason imalat", "subcontract"),
    "Standart Parça": ("standart", "standart parca", "standard part"),
    "Stoktan Karşılama": ("stok", "stoktan", "stoktan karsilama"),
    "Müşteri Malı": ("musteri", "musteri mali"),
}
TEMIN_BY_WORD = {w: name for name, words in TEMIN_WORDS.items() for w in words}
BUY_WORDS = ("satin", "hazir", "fason", "ticari", "tedarik", "buy", "purchase")

_ASCII = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def norm(v: Any) -> str:
    """Lower case ASCII words: titles and values compare the same however they were typed."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", tr_lower(_txt(v)).translate(_ASCII)).split())


def _blank(v: Any) -> bool:
    s = _txt(v)
    return not norm(s) and not any(c in s for c in CHECK_MARKS + CROSS_MARKS)


def read_progress(raw: Any) -> str | None:
    """The progress a status cell means, or None when the word is not known."""
    s = _txt(raw)
    if any(c in s for c in CHECK_MARKS):
        return PROG_DONE
    if any(c in s for c in CROSS_MARKS):
        return PROG_WAIT
    if s in PROGRESS_CHOICES:
        return s
    pct = re.fullmatch(r"%?\s*(\d+(?:[.,]\d+)?)\s*%?", s) if "%" in s else None
    if pct:
        v = float(pct[1].replace(",", "."))
        return PROG_WAIT if v <= 0 else PROG_DONE if v >= 100 else PROG_RUN
    text = f" {norm(s)} "
    for value, words in PROGRESS_WORDS:
        if any(f" {w} " in text for w in words):
            return value
    return None


def read_temin(raw: Any, choices: list[str]) -> str:
    """The temin type a cell means. A name that is not a known type comes back as typed."""
    n = norm(raw)
    known = {norm(c): c for c in choices}
    return known.get(n) or TEMIN_BY_WORD.get(n) or _txt(raw)


def guess_kind(name: str) -> str:
    n = norm(name)
    return KIND_HAZIR if any(w in n for w in BUY_WORDS) else KIND_IMALAT


# ---------- reading ----------
@dataclass
class Table:
    name: str
    rows: list[list[Any]]

    def at(self, row: int, col: int) -> Any:
        """1-based, like the row and column numbers shown to the user."""
        line = self.rows[row - 1]
        return line[col - 1] if 0 < col <= len(line) else None


def _cell(c: Any) -> Any:
    v = c.value
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "%" in (getattr(c, "number_format", "") or ""):
        return f"{v * 100:g}%"
    return v


def _trimmed(line: list[Any]) -> list[Any]:
    """Without the blank cells the reader pads a row with up to MAX_COLS."""
    while line and line[-1] in (None, ""):
        line.pop()
    return line


def _read_xlsx(path: str | Path) -> list[Table]:
    check_xlsx(path)
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        out = []
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            ws.reset_dimensions()               # many tools write a wrong size into the file
            out.append(Table(ws.title, [_trimmed([_cell(c) for c in row])
                                        for row in ws.iter_rows(max_row=MAX_ROWS, max_col=MAX_COLS)]))
        return out
    finally:
        wb.close()


def _read_xls(path: str | Path) -> list[Table]:
    import xlrd

    book = xlrd.open_workbook(str(path), on_demand=True)
    try:
        return [Table(sh.name, [sh.row_values(r)[:MAX_COLS] for r in range(min(sh.nrows, MAX_ROWS))])
                for sh in book.sheets() if sh.visibility == 0]
    finally:
        book.release_resources()


def _read_csv(path: str | Path) -> list[Table]:
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1254", errors="replace")
    first = text.split("\n", 1)[0]
    delimiter = max(";,\t|", key=first.count)
    rows = [line[:MAX_COLS] for _, line in zip(range(MAX_ROWS), csv.reader(io.StringIO(text), delimiter=delimiter))]
    return [Table("CSV", rows)]


def read_tables(path: str | Path) -> list[Table]:
    ext = Path(path).suffix.lower()
    reader = {".csv": _read_csv, ".xls": _read_xls}.get(ext, _read_xlsx)
    try:
        tables = reader(path)
    except Exception as e:                                      # noqa: BLE001 - any parse failure
        raise ImportError_(tx("Excel dosyası okunamadı")) from e
    tables = [t for t in tables if any(not _blank(v) for row in t.rows for v in row)]
    if not tables:
        raise ImportError_(tx("Dosyada veri bulunamadı"))
    return tables


# ---------- matching rows to parts ----------
class Matcher:
    """Finds the part a cell names: the exact number, an alias, or the same number typed differently
    (case, spaces, dashes, a CAD file extension). `SKIP` is a known item that has no tracking fields."""
    SKIP = object()

    def __init__(self, ctx: _Ctx):
        self.exact: dict[str, Any] = {}
        self.loose: dict[str, set[Any]] = {}
        for r in ctx.view.rows:
            if r.fastener_key:
                self._add(r.part_no, self.SKIP)
        for m in ctx.view.missing:
            self._add(m.part_no, self.SKIP)
        for p in ctx.skip:
            self._add(p, self.SKIP)
        for p in ctx.parts:
            self._add(p, p)
        for alias, p in ctx.view.aliases.items():
            if p in ctx.parts:
                self._add(alias, p)

    @staticmethod
    def _loose(s: str) -> str:
        return norm(strip_cad_ext(s)).replace(" ", "")

    def _add(self, name: str, target: Any) -> None:
        self.exact[name] = target
        self.loose.setdefault(self._loose(name), set()).add(target)

    def find(self, raw: Any) -> Any:
        s = _txt(raw)
        if s in self.exact:
            return self.exact[s]
        hits = self.loose.get(self._loose(s), set())
        real = hits - {self.SKIP}
        if len(real) == 1:
            return next(iter(real))
        return self.SKIP if hits and not real else None


# ---------- guessing the layout ----------
def _title_field(title: str) -> str | None:
    if title in TITLE_FIELD:
        return TITLE_FIELD[title]
    return next((TITLE_FIELD[t] for t in TITLES_LONGEST if title.startswith(t + " ")), None)


def _find_header(t: Table) -> int:
    """The row with the most known titles; 0 when the sheet has no title row."""
    best, score = 0, 0
    for i, row in enumerate(t.rows[:HEADER_SCAN_ROWS], 1):
        n = sum(1 for v in row if _title_field(norm(v)))
        if n > score:
            best, score = i, n
    return best


def _columns(t: Table, header: int) -> int:
    return max((len(r) for r in t.rows[header:header + DETECT_ROWS]), default=0)


def _detect(t: Table, m: Matcher, ctx: _Ctx) -> dict[str, Any]:
    header = _find_header(t)
    width = max(_columns(t, header), len(t.rows[header - 1]) if header else 0)
    titles = {c: norm(t.at(header, c)) for c in range(1, width + 1)} if header else {}
    fields = {c: _title_field(n) for c, n in titles.items() if n}
    sample = t.rows[header:header + DETECT_ROWS]

    hits: dict[int, set[Any]] = {}
    for line in sample:
        for c, v in enumerate(line, 1):
            if not _blank(v):
                hit = m.find(v)
                if hit is not None and hit is not Matcher.SKIP:
                    hits.setdefault(c, set()).add(hit)
    cols: dict[str, int] = {}
    if hits:
        cols[F_PART] = max(hits, key=lambda c: (len(hits[c]), fields.get(c) == F_PART, -c))
    else:
        cols[F_PART] = next((c for c, f in fields.items() if f == F_PART), 0)
    for c, f in fields.items():
        if f and f != F_PART and c != cols[F_PART]:
            cols.setdefault(f, c)

    def values(c: int) -> list[Any]:
        return [line[c - 1] for line in sample if c <= len(line) and not _blank(line[c - 1])]

    free = [c for c in range(1, width + 1) if c not in cols.values()]
    if F_TEMIN not in cols:
        known = {norm(x) for x in ctx.temins} | set(TEMIN_BY_WORD)
        for c in free:
            vals = values(c)
            if len(vals) >= MIN_VALUES and sum(norm(v) in known for v in vals) / len(vals) >= MIN_RATIO:
                cols[F_TEMIN] = c
                free.remove(c)
                break
    if F_STATUS not in cols and F_ORDER not in cols:
        for c in free:
            vals = values(c)
            if len(vals) >= MIN_VALUES and sum(read_progress(v) is not None for v in vals) / len(vals) >= MIN_RATIO:
                cols[F_STATUS] = c
                break
    return {"name": t.name, "header": header, "cols": cols, "use": bool(hits),
            "headers": [{"col": c, "title": _txt(t.at(header, c)) if header else ""} for c in range(1, width + 1)]}


def _merge(layout: dict[str, Any], given: Any) -> dict[str, Any]:
    """The user's corrections over the guess. Column numbers outside the sheet count as not used."""
    if not isinstance(given, dict):
        return layout
    width = len(layout["headers"])
    if isinstance(given.get("cols"), dict):
        layout["cols"] = {f: c for f, c in given["cols"].items()
                          if (f in HEADERS) and isinstance(c, int) and 0 < c <= width}
    if isinstance(given.get("use"), bool):
        layout["use"] = given["use"]
    return layout


# ---------- the comparison ----------
def _is_export(t: Table) -> bool:
    return any({H_KEY, H_PNO, H_PROG} <= {_txt(v) for v in row} for row in t.rows[:15])


def compare(db: Session, project: Project, path: str | Path, config: dict[str, Any], can_add_temin: bool) -> dict[str, Any]:
    """Compare the file with the DB. Nothing is written."""
    tables = read_tables(path)
    if any(_is_export(t) for t in tables):
        return {**preview(db, project, path), "mode": "export", "layouts": [], "matched": 0, "not_in_file": [],
                "unresolved": [], "new_temins": []}
    ctx = _Ctx(db, project)
    if ctx.view.version is None:
        raise ImportError_(tx("Projede onaylı BOM sürümü yok"))
    matcher = Matcher(ctx)
    diff = Diff(ctx)
    given = config.get("sheets") if isinstance(config.get("sheets"), dict) else {}
    values = config.get("values") if isinstance(config.get("values"), dict) else {}
    progress_map = values.get("progress") if isinstance(values.get("progress"), dict) else {}
    temin_map = values.get("temin") if isinstance(values.get("temin"), dict) else {}
    by_norm = {"manufacturer": {norm(x): x for x in ctx.manufacturers},
               "material_status": {norm(x): x for x in ctx.material}}

    layouts: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    unresolved: Counter[str] = Counter()
    new_temins: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    rows_read = 0

    known_temins = list(ctx.temins)

    def temin_of(raw: Any, sheet: str, row: int, label: str) -> str | None:
        text = _txt(raw)
        name = temin_map[text] if text in temin_map else read_temin(raw, known_temins)
        if not name:                              # the user chose to ignore this value
            return None
        if name not in known_temins:
            problem = (tx("Bu temin şekli listede yok. Yönetici ekleyebilir.") if not can_add_temin else
                       tx("Temin şekli adı boş olamaz ve 64 karakteri geçemez") if len(name) > 64 else None)
            if problem:
                diff.invalid.append({"sheet": sheet, "row": row, "key": label, "field": "Temin Şekli", "value": text,
                                     "message": problem})
                return None
            item = new_temins.setdefault(text, {"raw": text, "name": name, "kind": guess_kind(name), "count": 0})
            item["count"] += 1
            if name not in ctx.temins:
                ctx.temins.append(name)
        return name

    def progress_of(raw: Any) -> str | None:
        text = _txt(raw)
        if text in progress_map:
            return progress_map[text] or None
        value = read_progress(raw)
        if value is None:
            unresolved[text] += 1
        return value

    def read_row(t: Table, r: int, cols: dict[str, int], part: str) -> None:
        def cell(field: str) -> Any:
            return t.at(r, cols[field]) if field in cols else None

        procurement = ctx.parts[part]["procurement"]
        if not _blank(cell(F_TEMIN)):
            name = temin_of(cell(F_TEMIN), t.name, r, part)
            if name:
                diff.take(KIND_TRACKING, part, "procurement_override", name, t.name, r, part)
                procurement = name
        # A purchased item is judged by its order column, anything else by its production status
        order = (F_ORDER, F_STATUS) if ctx.view.base_kind(procurement) == KIND_HAZIR else (F_STATUS, F_ORDER)
        raw = next((cell(f) for f in order if not _blank(cell(f))), None)
        value = progress_of(raw) if raw is not None else None
        if value:
            diff.take(KIND_TRACKING, part, "progress", value, t.name, r, part)
        for f, target in TEXT_FIELDS.items():
            if not _blank(cell(f)):
                diff.take(KIND_TRACKING, part, target, by_norm.get(f, {}).get(norm(cell(f)), cell(f)), t.name, r, part)

    for t in tables:
        layout = _merge(_detect(t, matcher, ctx), given.get(t.name))
        part_col = layout["cols"].get(F_PART, 0)
        matched: set[str] = set()
        count = 0
        if layout["use"] and part_col:
            for r in range(layout["header"] + 1, len(t.rows) + 1):
                raw = t.at(r, part_col)
                if _blank(raw):
                    continue
                count += 1
                hit = matcher.find(raw)
                if hit is None:
                    unknown.append({"sheet": t.name, "row": r, "part_no": _txt(raw)})
                elif hit is not Matcher.SKIP:
                    matched.add(hit)
                    read_row(t, r, layout["cols"], hit)
        seen |= matched
        layouts.append({**layout, "rows": count, "matched": len(matched)})

    not_in_file = [{"part_no": k, "name": p.get("part_name") or "", "status": p.get("status") or "",
                    "procurement": p.get("procurement") or ""}
                   for k, p in sorted(ctx.parts.items(), key=lambda kv: tr_sort_key(kv[0])) if k not in seen]
    return {"mode": "any", "sheets": [x["name"] for x in layouts if x["use"]], "rows": sum(x["rows"] for x in layouts),
            "matched": len(seen), "changes": diff.changes(), "unknown": unknown, "invalid": diff.invalid,
            "not_in_file": not_in_file, "layouts": layouts, "version_id": ctx.view.version.id,
            "unresolved": [{"value": v, "count": n} for v, n in unresolved.most_common()],
            "new_temins": list(new_temins.values())}
