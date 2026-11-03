"""ERP logic: stock ledger, purchase orders, work orders, requirement planning (MRP) and project cost.

How it ties into part tracking (spec §5 statuses):
- A sent purchase order or a started work order moves the project part from Bekliyor to Devam ediyor
  (Hazır Alım: "Sipariş Verildi") and the project fastener to "Sipariş Verildi".
- Goods bought or made for a project go into stock and are issued to the project at once (receipt or
  production move + issue move), so stock only holds what no project has claimed yet.
- When everything the BOM needs has been issued to the project, the part becomes Tamamlandı and the
  fastener "Teslim Edildi".
These functions do not commit; the API layer commits.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.status import KIND_IMALAT, PROG_DONE, PROG_RUN, PROG_WAIT
from ..models import (Employee, FastenerSetting, Project, PurchaseOrder, PurchaseOrderLine, StockItem, StockMove,
                      TimeEntry, Tracking, User, WorkOrder)
from . import audit
from .state import FASTENER_ORDER_STATUSES, ProjectView
from .tracking import apply_changes, tracking_of

EPS = 1e-9

PO_STATUS = {"draft": "Taslak", "sent": "Gönderildi", "partial": "Kısmi teslim",
             "received": "Teslim alındı", "cancelled": "İptal"}
PO_OPEN = ("draft", "sent", "partial")
WO_STATUS = {"planned": "Planlandı", "in_progress": "Üretimde", "done": "Tamamlandı", "cancelled": "İptal"}
WO_OPEN = ("planned", "in_progress")
MOVE_KINDS = {"in": "Giriş", "out": "Çıkış", "count": "Sayım", "receipt": "Satın alma girişi",
              "production": "Üretim girişi", "issue": "Projeye çıkış"}
ITEM_KINDS = {"part": "Parça", "fastener": "Bağlantı elemanı", "other": "Diğer"}
STOCK_REF = "STOK"      # ref of issues taken from free stock (costed at the stock's average cost)


def _num(v: float) -> float:
    return round(v + 0.0, 6)


def next_no(db: Session, model: Any, prefix: str) -> str:
    """SA-2026-0001 style numbers, counting per year (model: any table with a `no` column)."""
    base = f"{prefix}-{date.today().year}-"
    used = [n[len(base):] for n in db.scalars(select(model.no).where(model.no.like(f"{base}%")))]
    last = max((int(n) for n in used if n.isdigit()), default=0)
    return f"{base}{last + 1:04d}"


# ---------- stock ----------
def stock_item(db: Session, code: str, name: str = "", kind: str = "part", unit: str = "Adet") -> StockItem:
    item = db.scalar(select(StockItem).where(StockItem.code == code))
    if item is None:
        item = StockItem(code=code, name=name, kind=kind if kind in ITEM_KINDS else "other", unit=unit or "Adet",
                         qty=0.0, min_qty=0.0)
        db.add(item)
        db.flush()
    elif name and not item.name:
        item.name = name
    return item


def move(db: Session, user: User | None, item: StockItem, kind: str, qty: float, *, project_id: int | None = None,
         ref: str = "", note: str = "", unit_cost: float | None = None) -> StockMove:
    """Book a stock move. qty is positive; out/issue subtract, count sets the counted quantity."""
    if kind not in MOVE_KINDS:
        raise HTTPException(400, f"Geçersiz hareket türü: {kind}")
    if kind == "count":
        if qty < 0:
            raise HTTPException(400, "Sayım miktarı negatif olamaz")
        delta = qty - item.qty
    else:
        if qty <= 0:
            raise HTTPException(400, "Miktar sıfırdan büyük olmalı")
        delta = -qty if kind in ("out", "issue") else qty
    if item.qty + delta < -EPS:
        raise HTTPException(400, f"{item.code}: stokta yeterli miktar yok (stok {item.qty:g}, istenen {qty:g})")
    if delta > 0 and unit_cost is not None:
        have = max(item.qty, 0.0)
        old_cost = item.unit_cost if item.unit_cost is not None else unit_cost
        item.unit_cost = round((have * old_cost + delta * unit_cost) / (have + delta), 4)
    item.qty = _num(item.qty + delta)
    m = StockMove(item_id=item.id, kind=kind, qty=_num(delta), balance=item.qty, project_id=project_id, ref=ref,
                  note=note, username=user.username if user else "",
                  unit_cost=unit_cost if unit_cost is not None else item.unit_cost)
    db.add(m)
    return m


def stock_out(i: StockItem) -> dict[str, Any]:
    return {"id": i.id, "code": i.code, "name": i.name, "kind": i.kind, "kind_label": ITEM_KINDS.get(i.kind, i.kind),
            "unit": i.unit, "qty": i.qty, "min_qty": i.min_qty, "unit_cost": i.unit_cost,
            "value": round(i.qty * i.unit_cost, 2) if i.unit_cost is not None else None,
            "low": i.min_qty > 0 and i.qty < i.min_qty, "location": i.location, "note": i.note,
            "updated_at": i.updated_at.isoformat() if i.updated_at else None}


def move_out(m: StockMove, item: StockItem | None = None, project_name: str | None = None) -> dict[str, Any]:
    return {"id": m.id, "ts": m.ts.isoformat() if m.ts else None, "kind": m.kind,
            "kind_label": MOVE_KINDS.get(m.kind, m.kind), "qty": m.qty, "balance": m.balance,
            "unit_cost": m.unit_cost, "project_id": m.project_id, "project_name": project_name, "ref": m.ref,
            "note": m.note, "username": m.username,
            "code": item.code if item else None, "name": item.name if item else None}


# ---------- tracking hooks ----------
def _tracking(db: Session, project_id: int, part_no: str) -> Tracking:
    t = tracking_of(db, project_id, part_no)
    if t is None:
        t = Tracking(project_id=project_id, part_no=part_no, progress=PROG_WAIT, note="", t35_note="",
                     manufacturer="", material_status="")
        db.add(t)
        db.flush()
    return t


def _fastener_setting(db: Session, project_id: int, key: str) -> FastenerSetting:
    fs = db.scalar(select(FastenerSetting).where(FastenerSetting.project_id == project_id, FastenerSetting.key == key))
    if fs is None:
        fs = FastenerSetting(project_id=project_id, key=key, spare_pct=10.0, supplier="", unit="Adet",
                             order_status=FASTENER_ORDER_STATUSES[0], note="")
        db.add(fs)
        db.flush()
    return fs


def mark_ordered(db: Session, user: User, project_id: int, code: str, kind: str, *, firm: str = "",
                 unit_price: float | None = None, manufacturer: str = "") -> None:
    """An order or work order exists: Bekliyor -> Devam ediyor, fastener -> Sipariş Verildi."""
    if not code:
        return
    if kind == "fastener":
        fs = _fastener_setting(db, project_id, code)
        changes: dict[str, Any] = {}
        if fs.order_status == FASTENER_ORDER_STATUSES[0]:
            changes["order_status"] = FASTENER_ORDER_STATUSES[1]
        if firm and not fs.supplier:
            changes["supplier"] = firm
        if unit_price is not None and fs.unit_price is None:
            changes["unit_price"] = unit_price
        audit.record_changes(db, user, fs, changes, "fastener", code, project_id)
    elif kind == "part":
        t = _tracking(db, project_id, code)
        changes = {}
        if t.progress == PROG_WAIT:
            changes["progress"] = PROG_RUN
        if manufacturer and not t.manufacturer:
            changes["manufacturer"] = manufacturer
        apply_changes(db, user, t, changes)


def _mark_delivered(db: Session, user: User, project_id: int, code: str, kind: str) -> None:
    if kind == "fastener":
        fs = _fastener_setting(db, project_id, code)
        audit.record_changes(db, user, fs, {"order_status": FASTENER_ORDER_STATUSES[2]}, "fastener", code, project_id)
    elif kind == "part":
        apply_changes(db, user, _tracking(db, project_id, code), {"progress": PROG_DONE})


def sync_delivery(db: Session, user: User, project: Project, codes: set[str]) -> int:
    """Mark the given codes delivered when the issued quantity covers the BOM requirement."""
    if not codes:
        return 0
    db.flush()
    n = 0
    for r in requirements(db, project, raw=True):
        if r["code"] in codes and r["required"] > 0 and r["issued"] + EPS >= r["required"]:
            _mark_delivered(db, user, project.id, r["code"], r["kind"])
            n += 1
    return n


def issue_from_stock(db: Session, user: User, project: Project, code: str, qty: float, note: str = "") -> StockMove:
    item = db.scalar(select(StockItem).where(StockItem.code == code))
    if item is None:
        raise HTTPException(404, f"{code}: stok kartı yok")
    m = move(db, user, item, "issue", qty, project_id=project.id, ref=STOCK_REF, note=note)
    if item.kind == "part":
        t = _tracking(db, project.id, code)
        apply_changes(db, user, t, {"material_status": "Stoktan"} if not t.material_status else {})
    sync_delivery(db, user, project, {code})
    return m


# ---------- purchase orders ----------
def po_out(po: PurchaseOrder, with_lines: bool = True, project_name: str | None = None) -> dict[str, Any]:
    total = sum(l.qty * l.unit_price for l in po.lines if l.unit_price is not None)
    received_value = sum(l.received_qty * l.unit_price for l in po.lines if l.unit_price is not None)
    qty = sum(l.qty for l in po.lines)
    rec = sum(min(l.received_qty, l.qty) for l in po.lines)
    out: dict[str, Any] = {
        "id": po.id, "no": po.no, "firm_id": po.firm_id, "firm_name": po.firm_name, "project_id": po.project_id,
        "project_name": project_name, "status": po.status, "status_label": PO_STATUS.get(po.status, po.status),
        "order_date": po.order_date.isoformat() if po.order_date else None,
        "due_date": po.due_date.isoformat() if po.due_date else None,
        "overdue": bool(po.due_date and po.due_date < date.today() and po.status in ("sent", "partial")),
        "currency": po.currency, "note": po.note, "created_at": po.created_at.isoformat() if po.created_at else None,
        "created_by": po.created_by, "line_count": len(po.lines), "total": round(total, 2),
        "received_value": round(received_value, 2), "received_pct": round(100 * rec / qty, 1) if qty else 0.0,
        "missing_price": sum(1 for l in po.lines if l.unit_price is None),
    }
    if with_lines:
        out["lines"] = [line_out(l) for l in po.lines]
    return out


def line_out(l: PurchaseOrderLine) -> dict[str, Any]:
    return {"id": l.id, "seq": l.seq, "code": l.code, "kind": l.kind, "kind_label": ITEM_KINDS.get(l.kind, l.kind),
            "description": l.description, "unit": l.unit, "qty": l.qty, "received_qty": l.received_qty,
            "remaining": max(0.0, _num(l.qty - l.received_qty)), "unit_price": l.unit_price,
            "amount": round(l.qty * l.unit_price, 2) if l.unit_price is not None else None}


def set_lines(po: PurchaseOrder, lines: list[dict[str, Any]]) -> None:
    po.lines.clear()
    for i, l in enumerate(lines, 1):
        if l["qty"] <= 0:
            raise HTTPException(400, f"Satır {i}: miktar sıfırdan büyük olmalı")
        if not (l.get("code") or "").strip() and not (l.get("description") or "").strip():
            raise HTTPException(400, f"Satır {i}: kod veya açıklama gerekli")
        po.lines.append(PurchaseOrderLine(seq=i, code=(l.get("code") or "").strip(), kind=l.get("kind") or "part",
                                          description=(l.get("description") or "").strip(),
                                          unit=l.get("unit") or "Adet", qty=float(l["qty"]), received_qty=0.0,
                                          unit_price=l.get("unit_price")))


def set_po_status(db: Session, user: User, po: PurchaseOrder, status: str) -> None:
    if status not in ("draft", "sent", "cancelled"):
        raise HTTPException(400, "Durum taslak, gönderildi veya iptal olabilir; teslimat mal kabul ile işlenir")
    received = any(l.received_qty > EPS for l in po.lines)
    if po.status == status:
        return
    if po.status in ("received", "cancelled"):
        raise HTTPException(400, f"{PO_STATUS[po.status]} durumundaki sipariş değiştirilemez")
    if status == "draft" and received:
        raise HTTPException(400, "Mal kabulü yapılmış sipariş taslağa döndürülemez")
    if status == "sent":
        if not po.lines:
            raise HTTPException(400, "Satırı olmayan sipariş gönderilemez")
        if po.order_date is None:
            po.order_date = date.today()
        if po.project_id:
            for l in po.lines:
                mark_ordered(db, user, po.project_id, l.code, l.kind, firm=po.firm_name, unit_price=l.unit_price,
                             manufacturer=po.firm_name if l.kind == "part" else "")
    audit.record(db, user, "purchase_order", po.no, "status", po.status, status, po.project_id)
    po.status = status


def receive(db: Session, user: User, po: PurchaseOrder, items: list[tuple[PurchaseOrderLine, float]],
            note: str = "") -> None:
    """Mal kabul: book the received quantities into stock (and to the project for project orders)."""
    if po.status not in ("sent", "partial"):
        raise HTTPException(400, "Mal kabul yalnızca gönderilmiş siparişte yapılır")
    codes: set[str] = set()
    for line, qty in items:
        if qty <= 0:
            continue
        line.received_qty = _num(line.received_qty + qty)
        audit.record(db, user, "purchase_order", po.no, f"teslim {line.code or line.description}",
                     None, qty, po.project_id)
        if not line.code:
            continue
        item = stock_item(db, line.code, line.description, line.kind, line.unit)
        move(db, user, item, "receipt", qty, project_id=po.project_id, ref=po.no, note=note, unit_cost=line.unit_price)
        if po.project_id:
            move(db, user, item, "issue", qty, project_id=po.project_id, ref=po.no, note=note)
            codes.add(line.code)
    po.status = "received" if all(l.received_qty + EPS >= l.qty for l in po.lines) else "partial"
    if po.project_id and codes:
        project = db.get(Project, po.project_id)
        if project is not None:
            sync_delivery(db, user, project, codes)


# ---------- work orders ----------
def wo_out(w: WorkOrder, project_name: str | None = None) -> dict[str, Any]:
    return {"id": w.id, "no": w.no, "project_id": w.project_id, "project_name": project_name, "part_no": w.part_no,
            "description": w.description, "qty": w.qty, "done_qty": w.done_qty,
            "remaining": max(0.0, _num(w.qty - w.done_qty)), "firm_name": w.firm_name,
            "subcontract": bool(w.firm_name), "status": w.status, "status_label": WO_STATUS.get(w.status, w.status),
            "start_date": w.start_date.isoformat() if w.start_date else None,
            "due_date": w.due_date.isoformat() if w.due_date else None,
            "overdue": bool(w.due_date and w.due_date < date.today() and w.status in WO_OPEN),
            "unit_cost": w.unit_cost, "total_cost": round(w.qty * w.unit_cost, 2) if w.unit_cost is not None else None,
            "note": w.note, "created_at": w.created_at.isoformat() if w.created_at else None,
            "created_by": w.created_by}


def set_wo_status(db: Session, user: User, w: WorkOrder, status: str) -> None:
    if status not in ("planned", "in_progress", "cancelled"):
        raise HTTPException(400, "Durum planlandı, üretimde veya iptal olabilir; tamamlama üretim girişi ile yapılır")
    if w.status == status:
        return
    if w.status in ("done", "cancelled"):
        raise HTTPException(400, f"{WO_STATUS[w.status]} durumundaki iş emri değiştirilemez")
    if status == "planned" and w.done_qty > EPS:
        raise HTTPException(400, "Üretim girişi yapılmış iş emri planlandıya döndürülemez")
    if status == "in_progress":
        if w.start_date is None:
            w.start_date = date.today()
        if w.project_id:
            mark_ordered(db, user, w.project_id, w.part_no, "part", manufacturer=w.firm_name)
    audit.record(db, user, "work_order", w.no, "status", w.status, status, w.project_id)
    w.status = status


def complete_work(db: Session, user: User, w: WorkOrder, qty: float, note: str = "") -> None:
    """Üretim girişi: finished parts into stock (and to the project)."""
    if w.status not in WO_OPEN:
        raise HTTPException(400, "Yalnızca açık iş emrine üretim girişi yapılır")
    if qty <= 0:
        raise HTTPException(400, "Miktar sıfırdan büyük olmalı")
    if w.status == "planned":
        set_wo_status(db, user, w, "in_progress")
    w.done_qty = _num(w.done_qty + qty)
    audit.record(db, user, "work_order", w.no, "done_qty", None, w.done_qty, w.project_id)
    item = stock_item(db, w.part_no, w.description, "part")
    move(db, user, item, "production", qty, project_id=w.project_id, ref=w.no, note=note, unit_cost=w.unit_cost)
    if w.project_id:
        move(db, user, item, "issue", qty, project_id=w.project_id, ref=w.no, note=note)
    if w.done_qty + EPS >= w.qty:
        audit.record(db, user, "work_order", w.no, "status", w.status, "done", w.project_id)
        w.status = "done"
    if w.project_id:
        project = db.get(Project, w.project_id)
        if project is not None:
            sync_delivery(db, user, project, {w.part_no})


# ---------- requirement planning (MRP) ----------
def _bom_items(pv: ProjectView) -> dict[str, dict[str, Any]]:
    """What the current BOM needs: purchased/manufactured parts and fasteners (assemblies are built in-house)."""
    items: dict[str, dict[str, Any]] = {}
    for p in pv.parts(include_in_purchased=False):
        if not p["counted"] or (p["is_assembly"] and not p["is_purchased_assembly"]):
            continue
        items[p["part_no"]] = {
            "code": p["part_no"], "kind": "part", "description": p["file_name"], "unit": "Adet",
            "required": float(p["total_qty"]), "procurement": p["procurement"], "status": p["status"],
            "status_color": p["status_color"], "progress": p["progress"],
            "main_group": (p["main_groups"] or [""])[0], "material": p["material"],
            "manufacturer": p["manufacturer"], "unit_price": None,
            "done": p["progress"] == PROG_DONE,
        }
    for f in pv.fasteners():
        desc = " ".join(x for x in (f["type"], f["std"], f["size"]) if x)
        items[f["key"]] = {
            "code": f["key"], "kind": "fastener", "description": desc or f["desc"], "unit": f["unit"],
            "required": float(f["order_qty"]), "procurement": "Hazır Alım", "status": f["order_status"],
            "status_color": f["status_color"], "progress": None, "main_group": (f["groups"] or [""])[0],
            "material": "", "manufacturer": f["supplier"], "unit_price": f["unit_price"],
            "done": f["order_status"] == FASTENER_ORDER_STATUSES[2],
        }
    return items


def requirements(db: Session, project: Project, raw: bool = False) -> list[dict[str, Any]]:
    """Need vs supply per item: required, issued, on order, in production, free stock, shortage.
    A part marked Tamamlandı by hand (no ERP issue) counts as covered."""
    items = _bom_items(ProjectView.load(db, project))
    if not items:
        return []
    issued: dict[str, float] = defaultdict(float)
    for code, q in db.execute(select(StockItem.code, func.sum(StockMove.qty)).join(StockItem)
                              .where(StockMove.project_id == project.id, StockMove.kind == "issue")
                              .group_by(StockItem.code)):
        issued[code] = -float(q or 0)
    on_order: dict[str, float] = defaultdict(float)
    open_pos: dict[str, list[str]] = defaultdict(list)
    for l, no in db.execute(select(PurchaseOrderLine, PurchaseOrder.no).join(PurchaseOrder)
                            .where(PurchaseOrder.project_id == project.id, PurchaseOrder.status.in_(PO_OPEN))):
        on_order[l.code] += max(0.0, l.qty - l.received_qty)
        if no not in open_pos[l.code]:
            open_pos[l.code].append(no)
    in_prod: dict[str, float] = defaultdict(float)
    open_wos: dict[str, list[str]] = defaultdict(list)
    for w in db.scalars(select(WorkOrder).where(WorkOrder.project_id == project.id, WorkOrder.status.in_(WO_OPEN))):
        in_prod[w.part_no] += max(0.0, w.qty - w.done_qty)
        open_wos[w.part_no].append(w.no)
    stock = {i.code: i for i in db.scalars(select(StockItem).where(StockItem.code.in_(list(items))))}

    out = []
    for code, it in items.items():
        st = stock.get(code)
        free = max(st.qty, 0.0) if st else 0.0
        req = it["required"]
        covered = req if it["done"] and not raw else min(req, issued[code])
        net = max(0.0, _num(req - covered - on_order[code] - in_prod[code]))
        from_stock = min(net, free)
        shortage = _num(net - from_stock)
        if shortage <= EPS and from_stock <= EPS:
            action = ""
        elif from_stock > EPS:
            action = "stock"
        elif it["kind"] == "part" and it["procurement"] == KIND_IMALAT:
            action = "work_order"
        else:
            action = "purchase"
        out.append({**it, "issued": _num(issued[code]), "on_order": _num(on_order[code]),
                    "in_production": _num(in_prod[code]), "stock": _num(free), "net_need": net,
                    "from_stock": _num(from_stock), "shortage": shortage, "action": action,
                    "unit_cost": st.unit_cost if st else None,
                    "purchase_orders": open_pos.get(code, []), "work_orders": open_wos.get(code, [])})
    return out


# ---------- project cost ----------
def project_costs(db: Session, project: Project, show_people: bool = True) -> dict[str, Any]:
    """Committed (ordered/planned) vs actual (received/produced/issued) cost, by source, firm and main group."""
    pv = ProjectView.load(db, project)
    groups = {code: it["main_group"] or "(Kök)" for code, it in _bom_items(pv).items()}
    rows: list[dict[str, Any]] = []      # {source, firm, group, committed, actual}
    missing_price = 0
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id,
                                                     PurchaseOrder.status != "cancelled")):
        for l in po.lines:
            if l.unit_price is None:
                missing_price += 1
                continue
            rows.append({"source": "Satın alma", "firm": po.firm_name or "(Firma yok)",
                         "group": groups.get(l.code, "(BOM dışı)"), "committed": l.qty * l.unit_price,
                         "actual": min(l.received_qty, l.qty) * l.unit_price})
    for w in db.scalars(select(WorkOrder).where(WorkOrder.project_id == project.id, WorkOrder.status != "cancelled")):
        if w.unit_cost is None:
            missing_price += 1
            continue
        rows.append({"source": "Fason iş emri" if w.firm_name else "İç üretim", "firm": w.firm_name or "(İç üretim)",
                     "group": groups.get(w.part_no, "(BOM dışı)"), "committed": w.qty * w.unit_cost,
                     "actual": min(w.done_qty, w.qty) * w.unit_cost})
    for m, code in db.execute(select(StockMove, StockItem.code).join(StockItem)
                              .where(StockMove.project_id == project.id, StockMove.kind == "issue",
                                     StockMove.ref == STOCK_REF)):
        if m.unit_cost is None:
            missing_price += 1
            continue
        v = -m.qty * m.unit_cost
        rows.append({"source": "Stoktan", "firm": "(Stok)", "group": groups.get(code, "(BOM dışı)"),
                     "committed": v, "actual": v})
    wo_parts = dict(db.execute(select(WorkOrder.id, WorkOrder.part_no)
                               .where(WorkOrder.project_id == project.id)).all())
    for t, emp in db.execute(select(TimeEntry, Employee.name).join(Employee)
                             .where(TimeEntry.project_id == project.id)):
        if t.hourly_cost is None:
            missing_price += 1
            continue
        v = t.hours * t.hourly_cost
        # Without hr rights labour is one anonymous line, so a person's wage cannot be worked out
        rows.append({"source": "İşçilik", "firm": emp if show_people else "İşçilik",
                     "group": groups.get(wo_parts.get(t.work_order_id or 0, ""), "(Genel işçilik)"),
                     "committed": v, "actual": v})

    def roll(key: str) -> list[dict[str, Any]]:
        acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            acc[r[key]][0] += r["committed"]
            acc[r[key]][1] += r["actual"]
        return sorted(({"name": k, "committed": round(c, 2), "actual": round(a, 2)} for k, (c, a) in acc.items()),
                      key=lambda x: -x["committed"])

    estimate = sum(f["total_price"] for f in pv.fasteners() if f["total_price"] is not None)
    return {"currency": "TRY", "committed": round(sum(r["committed"] for r in rows), 2),
            "actual": round(sum(r["actual"] for r in rows), 2), "missing_price": missing_price,
            "fastener_estimate": round(estimate, 2),
            "by_source": roll("source"), "by_firm": roll("firm"), "by_group": roll("group")}
