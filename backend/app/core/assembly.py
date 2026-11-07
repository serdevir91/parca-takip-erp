"""Assembly sheets: the pure planning logic behind Montaj Föyü (no database here).

Quantities are kept per part, not per BOM row, so one part used in two assemblies cannot be counted twice. `allocate`
hands out what is on hand to the open plans in order and every status on a sheet is derived from that result. Reservations are
therefore computed, never stored: after any change to a quantity or the plan order the sheets are right by construction.

`check` runs the seven consistency rules on a `Sheet`, which is either made from a document (`sheet_of`) or read back
from an edited workbook, so generation and feedback go through the same code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .i18n import tx
from .numbers import text as num_text
from .status import KIND_HAZIR, KIND_IMALAT, PROG_DONE, PROG_RUN, PROG_WAIT, STATUS_MAP

EPS = 1e-6
DRAFT, PUBLISHED, DONE = "Taslak", "Yayınlandı", "Tamamlandı"
PLAN_STATUSES = (DRAFT, PUBLISHED, DONE)
DRAWING_NONE, DRAWING_PAGES, DRAWING_LIST, DRAWING_BOTH = "none", "pages", "list", "both"
DRAWING_MODES = (DRAWING_NONE, DRAWING_PAGES, DRAWING_LIST, DRAWING_BOTH)
READY, PARTIAL, RUNNING, MISSING = "ready", "partial", "run", "none"
ERROR, WARNING, INFO = "error", "warning", "info"


def n(v: float) -> str:
    return num_text(v)


@dataclass
class Part:
    part_no: str
    procurement: str = ""
    kind: str = ""                 # KIND_IMALAT, KIND_HAZIR or empty
    material: str = ""
    rev: str = ""
    name: str = ""
    is_asm: bool = False           # has a step of its own
    progress: str = PROG_WAIT
    children: list[tuple[str, float]] = field(default_factory=list)
    fasteners: list[str] = field(default_factory=list)
    needs_drawing: bool = False
    has_drawing: bool = False
    drawing_rev: str = ""
    rev_mismatch: bool = False


@dataclass
class PlanItem:
    id: int
    part_no: str
    qty: float


@dataclass
class Extra:
    id: int
    part_no: str
    qty: float
    assembly_no: str = ""
    note: str = ""


@dataclass
class PlanInput:
    id: int
    items: list[PlanItem]
    extras: list[Extra] = field(default_factory=list)
    mounted: dict[tuple[int, str, str], float] = field(default_factory=dict)   # (item, path, part) -> qty
    steps_done: set[tuple[int, str]] = field(default_factory=set)              # (item, path)


@dataclass
class Row:
    item_id: int
    foy: str
    path: str
    step_no: int
    poz: int
    part_no: str
    qty: float
    need: float
    is_sub: bool = False
    sub_step: int = 0
    procurement: str = ""
    kind: str = ""
    material: str = ""
    rev: str = ""
    allocated: float = 0
    mounted: bool = False
    state: str = MISSING
    notes: list[dict[str, Any]] = field(default_factory=list)

    def note(self, text: str, warn: bool = False) -> None:
        self.notes.append({"text": text, "warn": warn})


@dataclass
class Step:
    no: int
    total: int
    part_no: str
    path: str
    is_top: bool
    parent: str
    per_parent: float
    make: float
    done: bool = False
    rows: list[Row] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(r.state == READY for r in self.rows)


@dataclass
class Foy:
    item_id: int
    part_no: str
    qty: float
    name: str
    rev: str
    steps: list[Step]
    fasteners: list[str]
    single: bool = False            # a lone part that goes straight on the main assembly

    @property
    def rows(self) -> list[Row]:
        return [r for s in self.steps for r in s.rows]

    @property
    def part_rows(self) -> list[Row]:
        return [r for r in self.rows if not r.is_sub]

    @property
    def done(self) -> bool:
        if self.single:
            return self.rows[0].mounted
        return self.steps[-1].done

    @property
    def ready(self) -> bool:
        """An assembly can start when its direct parts are there and its sub-assemblies are built."""
        return self.rows[0].state == READY if self.single else self.steps[-1].ready

    @property
    def percent(self) -> int:
        need = sum(r.need for r in self.rows)
        return round(100 * sum(min(r.allocated, r.need) for r in self.rows) / need) if need else 100


@dataclass
class Pick:
    part_no: str
    procurement: str
    kind: str
    material: str
    rev: str
    uses: dict[str, float]          # montaj -> quantity per one montaj
    need: float = 0
    extra: float = 0
    ready: float = 0
    extra_ready: float = 0
    status: str = ""
    progress: str = PROG_WAIT

    @property
    def short(self) -> float:
        return self.need - self.ready


@dataclass
class Doc:
    plan_id: int
    foys: list[Foy]
    picks: list[Pick]
    extras: list[Extra]

    @property
    def plan_total(self) -> float:
        return sum(sum(r.need for r in f.part_rows) for f in self.foys)

    @property
    def pick_total(self) -> float:
        return sum(p.need for p in self.picks)

    @property
    def extra_total(self) -> float:
        return sum(e.qty for e in self.extras)

    @property
    def percent(self) -> int:
        rows = [r for f in self.foys for r in f.rows]
        need = sum(r.need for r in rows)
        return round(100 * sum(min(r.allocated, r.need) for r in rows) / need) if need else 0

    def pick(self, part_no: str) -> Pick | None:
        return next((p for p in self.picks if p.part_no == part_no), None)

    def foy(self, part_no: str) -> Foy | None:
        return next((f for f in self.foys if f.part_no == part_no), None)


def _walk(cat: dict[str, Part], part_no: str, path: str, per1: float, parent: str, per_parent: float,
          seen: tuple[str, ...], out: list[tuple[Part, str, float, str, float]]) -> None:
    """Post-order: the deepest sub-assembly first, the main assembly last. `seen` stops a BOM that contains itself."""
    node = cat[part_no]
    for child, q in node.children:
        c = cat.get(child)
        if c is not None and c.is_asm and child not in seen:
            _walk(cat, child, f"{path}/{child}", per1 * q, part_no, q, (*seen, child), out)
    out.append((node, path, per1, parent, per_parent))


def _subtree_parts(cat: dict[str, Part], part_no: str, seen: frozenset[str] = frozenset()) -> set[str]:
    found: set[str] = set()
    for child, _ in cat[part_no].children:
        c = cat.get(child)
        if c is not None and c.is_asm and child not in seen:
            found |= _subtree_parts(cat, child, seen | {child})
        else:
            found.add(child)
    return found


def _double_counted(cat: dict[str, Part], steps: list[Step]) -> dict[tuple[str, str], str]:
    """(step assembly, part) -> where the part also sits, for parts listed directly and inside a sub-assembly."""
    found: dict[tuple[str, str], str] = {}
    for s in steps:
        for sub in (r for r in s.rows if r.is_sub):
            below = _subtree_parts(cat, sub.part_no)
            for r in s.rows:
                if not r.is_sub and r.part_no in below:
                    found[(s.part_no, r.part_no)] = sub.part_no
                    for inner in steps:
                        if any(x.part_no == r.part_no for x in inner.rows) and inner.part_no != s.part_no:
                            found[(inner.part_no, r.part_no)] = sub.part_no
    return found


def _state(row: Row, progress: str) -> str:
    if row.mounted or row.allocated >= row.need - EPS:
        return READY
    if row.allocated > EPS:
        return PARTIAL
    return RUNNING if progress == PROG_RUN and not row.is_sub else MISSING


def _foy(cat: dict[str, Part], plan: PlanInput, item: PlanItem) -> Foy:
    node = cat.get(item.part_no) or Part(item.part_no)
    if not node.is_asm:
        row = Row(item.id, item.part_no, "", 1, 10, item.part_no, 1, item.qty, procurement=node.procurement,
                  kind=node.kind, material=node.material, rev=node.rev)
        step = Step(1, 1, item.part_no, "", True, "", 1, item.qty, rows=[row])
        return Foy(item.id, item.part_no, item.qty, node.name, node.rev, [step], [], single=True)
    order: list[tuple[Part, str, float, str, float]] = []
    _walk(cat, item.part_no, item.part_no, 1, "", 1, (item.part_no,), order)
    number = {path: i for i, (_, path, *_rest) in enumerate(order, 1)}
    steps: list[Step] = []
    fasteners: list[str] = []
    for i, (asm, path, per1, parent, per_parent) in enumerate(order, 1):
        make = per1 * item.qty
        step = Step(i, len(order), asm.part_no, path, i == len(order), parent, per_parent, make,
                    done=(item.id, path) in plan.steps_done)
        for j, (child, q) in enumerate(asm.children, 1):
            c = cat.get(child) or Part(child)
            sub_path = f"{path}/{child}"
            step.rows.append(Row(item.id, item.part_no, path, i, j * 10, child, q, q * make, is_sub=c.is_asm,
                                 sub_step=number.get(sub_path, 0), procurement=c.procurement, kind=c.kind,
                                 material=c.material, rev=c.rev))
        steps.append(step)
        fasteners += asm.fasteners
    return Foy(item.id, item.part_no, item.qty, node.name, node.rev, steps, list(dict.fromkeys(fasteners)))


def _row_notes(cat: dict[str, Part], foy: Foy, doubles: dict[tuple[str, str], str], extras: dict[str, Extra]) -> None:
    for s in foy.steps:
        for r in s.rows:
            part = cat.get(r.part_no) or Part(r.part_no)
            if r.is_sub:
                r.note(tx("Adım {0}'de hazırlanır", r.sub_step))
            if r.state == PARTIAL:
                r.note(tx("{0} / {1} hazır", n(r.allocated), n(r.need)))
            where = doubles.get((s.part_no, r.part_no))
            if where:
                r.note(tx("Hem {0} içinde hem doğrudan listelenmiş – çift sayım kontrol et", where), True)
            e = extras.get(f"{foy.part_no}|{r.part_no}")
            if e is not None:
                done = getattr(e, "ready", 0) >= e.qty - EPS
                text = "+{0} ek adet (toplam gerekli {1})" if done else "+{0} ek adet üretilmedi (toplam gerekli {1})"
                r.note(tx(text, n(e.qty), n(r.need + e.qty)), True)
            if part.rev_mismatch:
                r.note(tx("Resim Rev {0}, BOM Rev {1}", part.drawing_rev, part.rev), True)
            elif not r.is_sub and part.needs_drawing and not part.has_drawing:
                r.note(tx("Teknik resim yok"), True)


def _status_text(p: Pick) -> str:
    table = STATUS_MAP.get(p.kind)
    if p.ready >= p.need - EPS:
        base = tx(table[PROG_DONE]) if table else tx("Hazır")
        return tx("{0} ({1} + {2} ek)", base, n(p.need - p.extra), n(p.extra)) if p.extra else base
    bom_need = p.need - p.extra
    if p.extra and p.ready >= bom_need - EPS:
        base = tx(table[PROG_DONE]) if table else tx("Hazır")
        return tx("{0}; +{1} ek adet üretilmedi", base, n(p.short))
    if p.ready > EPS:
        return tx("Kısmen hazır ({0} / {1})", n(p.ready), n(p.need))
    return tx(table.get(p.progress, table[PROG_WAIT])) if table else tx("Temin seçilmedi")


def _picks(cat: dict[str, Part], foys: list[Foy], extras: list[Extra]) -> list[Pick]:
    picks: dict[str, Pick] = {}

    def pick(part_no: str) -> Pick:
        if part_no not in picks:
            c = cat.get(part_no) or Part(part_no)
            picks[part_no] = Pick(part_no, c.procurement, c.kind, c.material, c.rev, {}, progress=c.progress)
        return picks[part_no]

    for f in foys:
        for r in f.part_rows:
            p = pick(r.part_no)
            per_one = r.need / f.qty if f.qty else 0
            key = "" if f.single else f.part_no
            p.uses[key] = p.uses.get(key, 0) + per_one
            p.need += r.need
            p.ready += r.need if r.mounted else min(r.allocated, r.need)
    for e in extras:
        p = pick(e.part_no)
        p.need += e.qty
        p.extra += e.qty
        got = getattr(e, "ready", 0)
        p.ready += got
        p.extra_ready += got
    for p in picks.values():
        p.status = _status_text(p)

    def order(p: Pick) -> tuple:
        kind = 0 if p.kind == KIND_IMALAT else 1 if p.kind == KIND_HAZIR else 2
        return (1 if p.short <= EPS else 0, kind, p.part_no)
    return sorted(picks.values(), key=order)


def allocate(cat: dict[str, Part], plans: list[PlanInput], available: dict[str, float]) -> dict[int, Doc]:
    """Give out `available` plan by plan, item by item. Extra quantities come after the plan's BOM needs."""
    left = dict(available)
    docs: dict[int, Doc] = {}
    for plan in plans:
        foys = [_foy(cat, plan, item) for item in plan.items]
        for f in foys:
            for s in f.steps:
                for r in s.rows:
                    mark = plan.mounted.get((f.item_id, s.path, r.part_no))
                    r.mounted = mark is not None
                    if r.mounted:
                        r.allocated = r.need   # already taken out of `available` through used_qty
                    else:
                        r.allocated = max(min(left.get(r.part_no, 0), r.need), 0)
                        left[r.part_no] = left.get(r.part_no, 0) - r.allocated
                    r.state = _state(r, (cat.get(r.part_no) or Part(r.part_no)).progress)
        by_row: dict[str, Extra] = {}
        for e in plan.extras:
            got = max(min(left.get(e.part_no, 0), e.qty), 0)
            left[e.part_no] = left.get(e.part_no, 0) - got
            e.ready = got  # type: ignore[attr-defined]
            home = next((f for f in foys if any(r.part_no == e.part_no for r in f.part_rows)
                         and (not e.assembly_no or f.part_no == e.assembly_no)), None)
            if home is not None:
                by_row[f"{home.part_no}|{e.part_no}"] = e
        for f in foys:
            _row_notes(cat, f, _double_counted(cat, f.steps), by_row)
        docs[plan.id] = Doc(plan.id, foys, _picks(cat, foys, plan.extras), plan.extras)
    return docs


def short_no(part_no: str) -> str:
    """T01_0600_0002 -> 0600_0002, the way people write it on the plan."""
    head, sep, rest = part_no.partition("_")
    return rest if sep else part_no


def extra_shortage_text(doc: Doc, foy: Foy) -> str:
    """The plan page note: parts of this montaj whose extra quantity is still missing, grouped by quantity."""
    groups: dict[float, list[str]] = {}
    for e in doc.extras:
        if e.qty - getattr(e, "ready", 0) > EPS and any(r.part_no == e.part_no for r in foy.part_rows) \
                and (not e.assembly_no or e.assembly_no == foy.part_no):
            groups.setdefault(e.qty, []).append(short_no(e.part_no))
    return "; ".join(tx("{0} için +{1} ek adet üretilmedi", tx(" ve ").join(ps), n(q)) for q, ps in groups.items())


# ---------- consistency rules (spec 6) ----------

@dataclass
class SheetRow:
    foy: str
    step_no: int
    part_no: str
    need: float
    box: str                 # READY, RUNNING, MISSING, "" (nothing marked) or "multi"
    ready_qty: float
    state: str = ""


@dataclass
class SheetPick:
    part_no: str
    need: float
    ready: float
    short: float
    status: str = ""
    extra_text: float | None = None    # the "+ 2 ek" written in the use column


@dataclass
class Sheet:
    picks: list[SheetPick]
    rows: list[SheetRow]
    plan_total: float
    pick_total: float


def sheet_of(doc: Doc) -> Sheet:
    def box(r: Row) -> str:
        return RUNNING if r.state == PARTIAL else r.state
    rows = [SheetRow(f.part_no, r.step_no, r.part_no, r.need, box(r), min(r.allocated, r.need), r.state)
            for f in doc.foys for r in f.part_rows]
    picks = [SheetPick(p.part_no, p.need, p.ready, p.short, p.status, p.extra or None) for p in doc.picks]
    return Sheet(picks, rows, doc.plan_total, doc.pick_total)


def _issue(code: int, severity: str, part_no: str, message: str, **more: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "part_no": part_no, "message": message, **more}


def _not_ready_texts() -> set[str]:
    raw = [s for table in STATUS_MAP.values() for k, s in table.items() if k != PROG_DONE]
    raw += ["Gelmedi", "Siparişte", "Üretimde"]
    return {x.casefold() for s in raw for x in (s, tx(s))}


def check(sheet: Sheet, doc: Doc, cat: dict[str, Part]) -> list[dict[str, Any]]:
    """The seven rules. `doc` is what the system holds, `sheet` what the document says."""
    out: list[dict[str, Any]] = []
    rows_of: dict[str, list[SheetRow]] = {}
    for r in sheet.rows:
        rows_of.setdefault(r.part_no, []).append(r)
    not_ready = _not_ready_texts()
    asked: set[str] = set()
    for p in sheet.picks:
        base = doc.pick(p.part_no)
        rows = rows_of.get(p.part_no, [])
        if abs(p.need - p.ready - p.short) > EPS:                                                           # 1
            out.append(_issue(1, ERROR, p.part_no, tx("Gerekli − Hazır ≠ Eksik: {0} − {1} ≠ {2}", n(p.need), n(p.ready), n(p.short))))
        boxes = {r.box for r in rows}
        extra = base.extra if base else 0
        total = sum(r.ready_qty for r in rows)
        if len(boxes) > 1 and (total > p.ready + EPS or total < p.ready - extra - EPS):                     # 2
            places = ", ".join(f"{r.foy}: {_box_text(r.box)}" for r in rows)
            out.append(_issue(2, ERROR, p.part_no, tx("Toplam hazır {0}, föylerde {1} görünüyor ({2})", n(p.ready), n(total), places)))
        if p.need > EPS and p.ready >= p.need - EPS:
            for r in rows:
                if r.box == MISSING:                                                                        # 3
                    out.append(_issue(3, ERROR, p.part_no, tx("Toplama listesinde tamamı hazır ({0} / {1}) ama {2} föyünde hâlâ gelmedi görünüyor", n(p.ready), n(p.need), r.foy)))
            if p.status and any(t in p.status.casefold() for t in not_ready) and ";" not in p.status:        # 6
                out.append(_issue(6, ERROR, p.part_no, tx("Durum \"{0}\" yazıyor ama hazır = gerekli ({1})", p.status, n(p.need))))
        for r in rows:
            if r.box == "multi":                                                                            # 6
                out.append(_issue(6, ERROR, p.part_no, tx("{0} föyünde birden fazla durum kutusu işaretli", r.foy)))
        if base is not None and abs(p.need - base.need) > EPS:                                               # 5
            asked.add(p.part_no)
            delta = p.need - base.need
            if delta > 0:
                out.append(_issue(5, WARNING, p.part_no, tx("Gerekli {0} yazılmış, sistemde {1}: +{2} ek adet olarak mı kaydedilsin?", n(p.need), n(base.need), n(delta)),
                                  action={"type": "extra", "part_no": p.part_no, "qty": delta}))
            else:
                out.append(_issue(5, ERROR, p.part_no, tx("Gerekli {0} yazılmış, sistemde {1}: BOM'dan az olamaz", n(p.need), n(base.need))))
        if p.extra_text is not None and abs(p.extra_text - extra) > EPS:                                     # 4
            out.append(_issue(4, WARNING, p.part_no, tx("Bu parça için +{0} ek yazılmış, sistemde {1}. Ek adet doğru parçada mı?", n(p.extra_text), n(extra))))
    for f in doc.foys:
        for r in f.part_rows:
            shown = next((x for x in sheet.rows if x.foy == f.part_no and x.part_no == r.part_no and x.step_no == r.step_no), None)
            if shown is not None and abs(shown.need - r.need) > EPS and r.part_no not in asked:              # 5
                asked.add(r.part_no)
                delta = shown.need - r.need
                if delta > 0:
                    out.append(_issue(5, WARNING, r.part_no, tx("Gerekli {0} yazılmış, sistemde {1}: +{2} ek adet olarak mı kaydedilsin?", n(shown.need), n(r.need), n(delta)),
                                      action={"type": "extra", "part_no": r.part_no, "qty": delta}))
                else:
                    out.append(_issue(5, ERROR, r.part_no, tx("Gerekli {0} yazılmış, sistemde {1}: BOM'dan az olamaz", n(shown.need), n(r.need))))
    for e in doc.extras:                                                                                     # 4
        homes = [f for f in doc.foys if any(r.part_no == e.part_no for r in f.part_rows)]
        if not homes:
            out.append(_issue(4, ERROR, e.part_no, tx("{0} için girilen +{1} ek adet bu plandaki hiçbir montajda geçmiyor", e.part_no, n(e.qty)), extra_id=e.id))
        elif e.assembly_no and not any(f.part_no == e.assembly_no for f in homes):
            out.append(_issue(4, ERROR, e.part_no, tx("{0} için girilen ek adet {1} montajına bağlı ama parça orada yok", e.part_no, e.assembly_no), extra_id=e.id))
    gap = sheet.pick_total - sheet.plan_total                                                                # 7
    if abs(gap) > EPS:
        accepted = doc.extra_total + sum(i["action"]["qty"] for i in out if i.get("action"))
        if abs(gap - accepted) <= EPS:
            out.append(_issue(7, INFO, "", tx("Toplama toplamı plan toplamından {0} fazla: fark ek adetlerden geliyor", n(gap))))
        else:
            out.append(_issue(7, ERROR, "", tx("Plan toplamı {0}, toplama listesi {1}: fark ek adetlerle açıklanmıyor", n(sheet.plan_total), n(sheet.pick_total))))
    return out


def _box_text(box: str) -> str:
    return {READY: tx("hazır"), RUNNING: tx("üretimde / siparişte"), MISSING: tx("gelmedi"), "multi": tx("çelişkili")}.get(box, tx("boş"))
