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
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from ..core import numbers as num
from ..core.status import KIND_IMALAT, PROG_DONE, PROG_RUN, PROG_WAIT
from ..models import (Employee, FastenerSetting, Invoice, Project, PurchaseOrder, PurchaseOrderLine, PurchaseReceipt,
                      StockItem, StockMove, SyncState, TimeEntry, Tracking, User, WorkOrder, WorkOrderMaterial)
from . import audit, fx, system
from .state import FASTENER_ORDER_STATUSES, ProjectView
from .tracking import apply_changes, tracking_of
from app.core.i18n import tx

EPS = 1e-9

PO_STATUS = {"draft": "Taslak", "sent": "Gönderildi", "partial": "Kısmi teslim",
             "received": "Teslim alındı", "closed": "Eksik kapatıldı", "cancelled": "İptal"}
PO_OPEN = ("draft", "sent", "partial")      # closed is not open: what was never delivered is no longer on order
WO_STATUS = {"planned": "Planlandı", "in_progress": "Üretimde", "done": "Tamamlandı", "closed": "Kısa kapatıldı",
             "cancelled": "İptal"}
WO_OPEN = ("planned", "in_progress")
WO_FINAL = ("done", "closed", "cancelled")
MOVE_KINDS = {"assembly": "Montajda kullanıldı", "assembly_return": "Montajdan dönüş", "in": "Giriş", "out": "Çıkış", "count": "Sayım", "receipt": "Satın alma girişi",
              "production": "Üretim girişi", "issue": "Projeye çıkış", "issue_return": "Projeden dönüş",
              "supplier_return": "Tedarikçiye iade", "sale": "Satış sevki", "sale_return": "Satış iadesi"}
OUT_KINDS = ("out", "issue", "supplier_return", "sale", "assembly")
ISSUE_KINDS = ("issue", "issue_return")     # their signed sum is what a project holds
ITEM_KINDS = {"part": "Parça", "fastener": "Bağlantı elemanı", "other": "Diğer"}
STOCK_REF = "STOK"      # ref of issues taken from free stock (costed at the stock's average cost)


def _num(v: float) -> float:
    return num.qty(v + 0.0)


def lock_order(db: Session, order: Any) -> None:
    """Row lock on a purchase or sales order, then fresh values: two users acting on one order queue up here."""
    model = type(order)
    db.flush()
    db.execute(update(model).where(model.id == order.id).values(status=model.status))
    db.refresh(order)
    for line in order.lines:
        db.refresh(line)


def next_no(db: Session, model: Any) -> str:
    """SA-2026-0001 style numbers, counting per year; the prefix comes from Sistem Ayarları."""
    # Holds a write lock until commit: two people creating at once get consecutive numbers, not a UNIQUE error
    db.execute(update(SyncState).where(SyncState.id == 1).values(rev=SyncState.rev))
    base = f"{system.prefix(db, model)}-{date.today().year}-"
    used = [n[len(base):] for n in db.scalars(select(model.no).where(model.no.like(f"{base}%")))]
    last = max((int(n) for n in used if n.isdigit()), default=0)
    return f"{base}{last + 1:04d}"


# ---------- stock ----------
def stock_item(db: Session, code: str, name: str = "", kind: str = "part", unit: str = "") -> StockItem:
    item = db.scalar(select(StockItem).where(StockItem.code == code))
    if item is None:
        item = StockItem(code=code, name=name, kind=kind if kind in ITEM_KINDS else "other", unit=unit or system.system(db)["production"]["unit"],
                         qty=0.0, min_qty=0.0)
        db.add(item)
        db.flush()
    elif name and not item.name:
        item.name = name
    return item


def move(db: Session, user: User | None, item: StockItem, kind: str, qty: float, *, project_id: int | None = None,
         ref: str = "", note: str = "", unit_cost: float | None = None) -> StockMove:
    """Book a stock move. qty is positive; OUT_KINDS subtract, count sets the counted quantity."""
    if kind not in MOVE_KINDS:
        raise HTTPException(400, tx("Geçersiz hareket türü: {0}", kind))
    # Take the row lock before reading the balance, so parallel moves queue up instead of losing each other
    db.flush()
    db.execute(update(StockItem).where(StockItem.id == item.id).values(qty=StockItem.qty))
    db.refresh(item)
    if kind == "count":
        if qty < 0:
            raise HTTPException(400, tx("Sayım miktarı negatif olamaz"))
        delta = qty - item.qty
    else:
        if qty <= 0:
            raise HTTPException(400, tx("Miktar sıfırdan büyük olmalı"))
        delta = -qty if kind in OUT_KINDS else qty
    if item.qty + delta < -EPS:
        raise HTTPException(400, tx("{0}: stokta yeterli miktar yok (stok {1}, istenen {2})", item.code, num.text(item.qty), num.text(qty)))
    if delta > 0 and unit_cost is not None:
        have = max(item.qty, 0.0)
        old_cost = item.unit_cost if item.unit_cost is not None else unit_cost
        item.unit_cost = round((have * old_cost + delta * unit_cost) / (have + delta), 4)
    elif kind == "supplier_return" and unit_cost is not None and item.unit_cost is not None and item.qty + delta > EPS:
        # Goods leave at their purchase cost, so the average goes back to what it was without them
        item.unit_cost = round(max(item.qty * item.unit_cost + delta * unit_cost, 0.0) / (item.qty + delta), 4)
    item.qty = _num(item.qty + delta)
    m = StockMove(item_id=item.id, kind=kind, qty=_num(delta), balance=item.qty, project_id=project_id, ref=ref,
                  note=note, username=user.username if user else "",
                  unit_cost=unit_cost if unit_cost is not None or kind == "issue_return" else item.unit_cost)
    db.add(m)
    return m


def stock_out(i: StockItem) -> dict[str, Any]:
    return {"id": i.id, "rev": i.edit_rev, "code": i.code, "name": i.name, "kind": i.kind, "kind_label": ITEM_KINDS.get(i.kind, i.kind),
            "unit": i.unit, "qty": i.qty, "min_qty": i.min_qty, "unit_cost": i.unit_cost,
            "value": num.money(i.qty * i.unit_cost) if i.unit_cost is not None else None,
            "low": i.min_qty > 0 and i.qty < i.min_qty, "location": i.location, "note": i.note,
            "reorder_qty": i.reorder_qty, "preferred_firm_id": i.preferred_firm_id,
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
        prod = system.system(db)["production"]
        fs = FastenerSetting(project_id=project_id, key=key, spare_pct=prod["spare_pct"], supplier="", unit=prod["unit"],
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


def sync_undelivered(db: Session, user: User, project: Project, codes: set[str]) -> None:
    """Goods went back: a part or fastener that no longer has what the BOM needs is on its way again."""
    if not codes:
        return
    db.flush()
    for r in requirements(db, project, raw=True):
        if r["code"] not in codes or not r["done"] or r["issued"] + EPS >= r["required"]:
            continue
        if r["kind"] == "fastener":
            audit.record_changes(db, user, _fastener_setting(db, project.id, r["code"]),
                                 {"order_status": FASTENER_ORDER_STATUSES[1]}, "fastener", r["code"], project.id)
        else:
            apply_changes(db, user, _tracking(db, project.id, r["code"]), {"progress": PROG_RUN})


def project_held(db: Session, project_id: int, item_id: int) -> float:
    """What a project holds of a stock item: issued to it and not returned."""
    return -float(db.scalar(select(func.sum(StockMove.qty))
                            .where(StockMove.item_id == item_id, StockMove.project_id == project_id,
                                   StockMove.kind.in_(ISSUE_KINDS))) or 0)


def issue_from_stock(db: Session, user: User, project: Project, code: str, qty: float, note: str = "") -> StockMove:
    item = db.scalar(select(StockItem).where(StockItem.code == code))
    if item is None:
        raise HTTPException(404, tx("{0}: stok kartı yok", code))
    m = move(db, user, item, "issue", qty, project_id=project.id, ref=STOCK_REF, note=note)
    if item.kind == "part":
        t = _tracking(db, project.id, code)
        apply_changes(db, user, t, {"material_status": "Stoktan"} if not t.material_status else {})
    sync_delivery(db, user, project, {code})
    return m


# ---------- purchase orders ----------
def po_out(po: PurchaseOrder, with_lines: bool = True, project_name: str | None = None,
           book: fx.Book | None = None) -> dict[str, Any]:
    rate = book.doc(po.currency, po.rate, po.order_date, po.created_at) if book else po.rate
    total = sum(num.money(l.qty * l.unit_price) for l in po.lines if l.unit_price is not None)
    received_value = sum(num.money(l.received_qty * l.unit_price) for l in po.lines if l.unit_price is not None)
    qty = sum(l.qty for l in po.lines)
    rec = sum(min(l.received_qty, l.qty) for l in po.lines)
    out: dict[str, Any] = {
        "id": po.id, "no": po.no, "firm_id": po.firm_id, "firm_name": po.firm_name, "project_id": po.project_id,
        "project_name": project_name, "status": po.status, "status_label": PO_STATUS.get(po.status, po.status),
        "order_date": po.order_date.isoformat() if po.order_date else None,
        "due_date": po.due_date.isoformat() if po.due_date else None,
        "overdue": bool(po.due_date and po.due_date < date.today() and po.status in ("sent", "partial")),
        "currency": po.currency, "rate": po.rate, "note": po.note,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "created_by": po.created_by, "line_count": len(po.lines), "total": num.money(total), "rev": po.edit_rev,
        "needs_rate": bool(book) and rate is None,
        "base_total": num.money(total * rate) if rate is not None else None,
        "received_value": num.money(received_value), "received_pct": num.pct(100 * rec / qty) if qty else 0.0,
        "missing_price": sum(1 for l in po.lines if l.unit_price is None),
    }
    if with_lines:
        out["lines"] = [line_out(l) for l in po.lines]
    return out


def line_out(l: PurchaseOrderLine) -> dict[str, Any]:
    return {"id": l.id, "seq": l.seq, "code": l.code, "kind": l.kind, "kind_label": ITEM_KINDS.get(l.kind, l.kind),
            "description": l.description, "unit": l.unit, "qty": l.qty, "received_qty": l.received_qty,
            "remaining": max(0.0, _num(l.qty - l.received_qty)), "unit_price": l.unit_price,
            "amount": num.money(l.qty * l.unit_price) if l.unit_price is not None else None}


def set_lines(po: PurchaseOrder, lines: list[dict[str, Any]]) -> None:
    po.lines.clear()
    for i, l in enumerate(lines, 1):
        if _num(l["qty"]) <= 0:
            raise HTTPException(400, tx("Satır {0}: miktar sıfırdan büyük olmalı", i))
        if not (l.get("code") or "").strip() and not (l.get("description") or "").strip():
            raise HTTPException(400, tx("Satır {0}: kod veya açıklama gerekli", i))
        po.lines.append(PurchaseOrderLine(seq=i, code=(l.get("code") or "").strip(), kind=l.get("kind") or "part",
                                          description=(l.get("description") or "").strip(),
                                          unit=l.get("unit") or "Adet", qty=_num(float(l["qty"])), received_qty=0.0,
                                          unit_price=l.get("unit_price")))


def fill_po_rate(db: Session, po: PurchaseOrder) -> float | None:
    """A document with no rate takes the table's rate of its date and keeps it from then on."""
    if po.rate is None:
        po.rate = fx.rate_on(db, po.currency, fx.first_day(po.order_date, po.created_at))
    return po.rate


def set_po_status(db: Session, user: User, po: PurchaseOrder, status: str) -> None:
    if status not in ("draft", "sent", "cancelled"):
        raise HTTPException(400, tx("Durum taslak, gönderildi veya iptal olabilir; teslimat mal kabul ile işlenir"))
    lock_order(db, po)
    received = any(l.received_qty > EPS for l in po.lines)
    if po.status == status:
        return
    if po.status in ("received", "closed", "cancelled"):
        raise HTTPException(400, tx("{0} durumundaki sipariş değiştirilemez", PO_STATUS[po.status]))
    if status == "cancelled" and received:
        raise HTTPException(400, tx("Mal kabulü yapılmış sipariş iptal edilemez. Kalanı bırakmak için siparişi eksik kapatın, malı geri vermek için mal kabulü geri alın."))
    if status == "draft" and received:
        raise HTTPException(400, tx("Mal kabulü yapılmış sipariş taslağa döndürülemez"))
    if status == "draft" and db.scalar(select(Invoice.id).where(Invoice.purchase_order_id == po.id,
                                                                Invoice.status != "cancelled").limit(1)):
        raise HTTPException(400, tx("Faturası girilmiş sipariş taslağa döndürülemez"))
    if status == "sent":
        if not po.lines:
            raise HTTPException(400, tx("Satırı olmayan sipariş gönderilemez"))
        if po.order_date is None:
            po.order_date = date.today()
        fill_po_rate(db, po)
        if po.project_id:
            for l in po.lines:
                mark_ordered(db, user, po.project_id, l.code, l.kind, firm=po.firm_name, unit_price=l.unit_price,
                             manufacturer=po.firm_name if l.kind == "part" else "")
    audit.record(db, user, "purchase_order", po.no, "status", po.status, status, po.project_id)
    po.status = status


def _base_cost(db: Session, po: PurchaseOrder, line: PurchaseOrderLine) -> float | None:
    """Unit price in the base currency: stock average cost never holds a foreign amount."""
    if line.unit_price is None:
        return None
    rate = fill_po_rate(db, po)
    if rate is None:
        raise HTTPException(400, tx("{0}: {1} kuru bilinmiyor, stok maliyeti hesaplanamaz. Siparişe kur yazın veya Fatura ve ödeme > Kurlar ekranından kur girin.", po.no, po.currency))
    return round(line.unit_price * rate, 6)


def _set_receipt_status(po: PurchaseOrder) -> None:
    if po.status == "closed":
        return
    if all(l.received_qty + EPS >= l.qty for l in po.lines):
        po.status = "received"
    else:
        po.status = "partial" if any(l.received_qty > EPS for l in po.lines) else "sent"


def receive(db: Session, user: User, po: PurchaseOrder, items: list[tuple[PurchaseOrderLine, float]],
            note: str = "", rate: float | None = None) -> None:
    """Mal kabul: book the received quantities into stock (and to the project for project orders).
    rate is typed on the receipt screen for a foreign currency order that has none."""
    lock_order(db, po)
    if po.status not in ("sent", "partial"):
        raise HTTPException(400, tx("Mal kabul yalnızca gönderilmiş siparişte yapılır"))
    if rate is not None and rate != po.rate:
        if fx.norm(po.currency) == fx.base_currency(db):
            raise HTTPException(400, tx("{0} ana para birimi, kur girilmez", po.currency))
        if any(l.received_qty > EPS for l in po.lines):
            raise HTTPException(400, tx("Mal kabulü yapılmış siparişin kuru değiştirilemez"))
        audit.record(db, user, "purchase_order", po.no, "rate", po.rate, rate, po.project_id)
        po.rate = rate
    over = 1 + system.system(db)["commerce"]["over_receipt_pct"] / 100
    codes: set[str] = set()
    for line, qty in items:
        if qty <= 0:
            continue
        room = _num(line.qty * over - line.received_qty)
        if qty > room + EPS:
            raise HTTPException(400, tx("{0}: en fazla {1} {2} daha teslim alınabilir (sipariş {3}, teslim alınan {4})", line.code or line.description, num.text(max(room, 0.0)), line.unit, num.text(line.qty), num.text(line.received_qty)))
        line.received_qty = _num(line.received_qty + qty)
        db.add(PurchaseReceipt(po_id=po.id, line_id=line.id, qty=qty, username=user.username if user else "",
                               note=note[:300]))
        audit.record(db, user, "purchase_order", po.no, f"teslim {line.code or line.description}",
                     None, qty, po.project_id)
        if not line.code:
            continue
        item = stock_item(db, line.code, line.description, line.kind, line.unit)
        move(db, user, item, "receipt", qty, project_id=po.project_id, ref=po.no, note=note,
             unit_cost=_base_cost(db, po, line))
        if po.project_id:
            move(db, user, item, "issue", qty, project_id=po.project_id, ref=po.no, note=note)
            codes.add(line.code)
    _set_receipt_status(po)
    if po.project_id and codes:
        project = db.get(Project, po.project_id)
        if project is not None:
            sync_delivery(db, user, project, codes)


def _receipt_cost(db: Session, po: PurchaseOrder, line: PurchaseOrderLine, item: StockItem) -> float | None:
    """The cost the goods came in at. An order received before rates existed has no rate: its stock move knows."""
    if po.rate is not None or line.unit_price is None:
        return _base_cost(db, po, line)
    return db.scalar(select(StockMove.unit_cost).where(StockMove.item_id == item.id, StockMove.kind == "receipt",
                                                       StockMove.ref == po.no)
                     .order_by(StockMove.id.desc()).limit(1))


def reverse_receipt(db: Session, user: User, po: PurchaseOrder, items: list[tuple[PurchaseOrderLine, float]],
                    note: str = "") -> None:
    """Mal kabul geri alma / mal iadesi: the goods leave at the cost they came in, the order reopens as needed.
    A project order first takes them back from the project, so stock and the project both net to zero."""
    lock_order(db, po)
    if po.status not in ("partial", "received", "closed"):
        raise HTTPException(400, tx("Bu siparişte geri alınacak mal kabulü yok"))
    codes: set[str] = set()
    for line, qty in items:
        if qty <= 0:
            continue
        label = line.code or line.description
        if qty > line.received_qty + EPS:
            raise HTTPException(400, tx("{0}: teslim alınan {1}, en fazla bu kadar geri alınabilir", label, num.text(line.received_qty)))
        line.received_qty = _num(line.received_qty - qty)
        db.add(PurchaseReceipt(po_id=po.id, line_id=line.id, qty=-qty, username=user.username if user else "",
                               note=note[:300]))
        audit.record(db, user, "purchase_order", po.no, f"geri alma {label}", None, qty, po.project_id)
        if not line.code:
            continue
        item = db.scalar(select(StockItem).where(StockItem.code == line.code))
        if item is None:
            raise HTTPException(400, tx("{0}: stok kartı yok, mal stokta değil", label))
        cost = _receipt_cost(db, po, line, item)
        if po.project_id:
            held = project_held(db, po.project_id, item.id)
            if held + EPS < qty:
                raise HTTPException(400, tx("{0}: projede yeterli miktar yok (projede {1}, istenen {2})", label, num.text(held), num.text(qty)))
            move(db, user, item, "issue_return", qty, project_id=po.project_id, ref=po.no, note=note, unit_cost=cost)
            codes.add(line.code)
        move(db, user, item, "supplier_return", qty, project_id=po.project_id, ref=po.no, note=note, unit_cost=cost)
    _set_receipt_status(po)
    if po.project_id and codes:
        project = db.get(Project, po.project_id)
        if project is not None:
            sync_undelivered(db, user, project, codes)


def close_po(db: Session, user: User, po: PurchaseOrder, note: str = "") -> None:
    """Siparişi eksik kapat: what was received stays, the rest is no longer on order."""
    lock_order(db, po)
    if po.status != "partial":
        raise HTTPException(400, tx("Yalnızca kısmi teslim alınmış sipariş eksik kapatılır; hiç teslim alınmadıysa iptal edin"))
    audit.record(db, user, "purchase_order", po.no, "status", po.status, "closed", po.project_id)
    po.status = "closed"
    if note.strip():
        po.note = f"{po.note}\nEksik kapatıldı: {note.strip()}".strip()


# ---------- work orders ----------
def wo_out(w: WorkOrder, project_name: str | None = None, ops: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    """ops = (steps done, steps in total). A closed order stops at what was made, so nothing remains of it."""
    qty = w.done_qty if w.status == "closed" else w.qty
    return {"id": w.id, "rev": w.edit_rev, "no": w.no, "project_id": w.project_id, "project_name": project_name, "part_no": w.part_no,
            "description": w.description, "qty": w.qty, "done_qty": w.done_qty,
            "remaining": max(0.0, _num(qty - w.done_qty)), "firm_name": w.firm_name,
            "subcontract": bool(w.firm_name), "status": w.status, "status_label": WO_STATUS.get(w.status, w.status),
            "start_date": w.start_date.isoformat() if w.start_date else None,
            "due_date": w.due_date.isoformat() if w.due_date else None,
            "overdue": bool(w.due_date and w.due_date < date.today() and w.status in WO_OPEN),
            "unit_cost": w.unit_cost, "total_cost": num.money(qty * w.unit_cost) if w.unit_cost is not None else None,
            "note": w.note, "created_at": w.created_at.isoformat() if w.created_at else None,
            "created_by": w.created_by, "ops_done": ops[0], "ops_total": ops[1]}


def lock_wo(db: Session, w: WorkOrder) -> None:
    """Row lock, then a fresh read: parallel work on one order queues up instead of acting on a stale status."""
    db.flush()
    db.execute(update(WorkOrder).where(WorkOrder.id == w.id).values(status=WorkOrder.status))
    db.refresh(w)


def set_wo_status(db: Session, user: User, w: WorkOrder, status: str) -> None:
    if status not in ("planned", "in_progress", "cancelled", "closed"):
        raise HTTPException(400, tx("Durum planlandı, üretimde, iptal veya kısa kapatıldı olabilir; tamamlama üretim girişi ile yapılır"))
    lock_wo(db, w)
    if w.status == status:
        return
    if w.status in WO_FINAL:
        raise HTTPException(400, tx("{0} durumundaki iş emri değiştirilemez", WO_STATUS[w.status]))
    if status == "planned" and w.done_qty > EPS:
        raise HTTPException(400, tx("Üretim girişi yapılmış iş emri planlandıya döndürülemez"))
    if status == "cancelled":
        if w.done_qty > EPS:
            raise HTTPException(400, tx("Üretim girişi yapılmış iş emri iptal edilemez; kısa kapatın"))
        if db.scalar(select(WorkOrderMaterial.id).where(WorkOrderMaterial.wo_id == w.id,
                                                        WorkOrderMaterial.issued_qty > EPS).limit(1)):
            raise HTTPException(400, tx("Malzeme çıkılmış iş emri iptal edilemez; malzemeyi iade edin veya kısa kapatın"))
    if status == "in_progress":
        if w.start_date is None:
            w.start_date = date.today()
        if w.project_id:
            mark_ordered(db, user, w.project_id, w.part_no, "part", manufacturer=w.firm_name)
    audit.record(db, user, "work_order", w.no, "status", w.status, status, w.project_id)
    w.status = status


def complete_work(db: Session, user: User, w: WorkOrder, qty: float, note: str = "") -> list[dict[str, Any]]:
    """Üretim girişi: finished parts into stock (and to the project). Materials go out in proportion to done_qty;
    returns what could not be issued, which never stops the completion."""
    from . import womaterials   # needs this module's stock functions

    lock_wo(db, w)
    if w.status not in WO_OPEN:
        raise HTTPException(400, tx("Yalnızca açık iş emrine üretim girişi yapılır"))
    if qty <= 0:
        raise HTTPException(400, tx("Miktar sıfırdan büyük olmalı"))
    if w.status == "planned":
        set_wo_status(db, user, w, "in_progress")
    w.done_qty = _num(w.done_qty + qty)
    audit.record(db, user, "work_order", w.no, "done_qty", None, w.done_qty, w.project_id)
    warnings, material_value = womaterials.consume(db, user, w)
    unit_cost = w.unit_cost if material_value <= EPS else (w.unit_cost or 0.0) + material_value / qty
    item = stock_item(db, w.part_no, w.description, "part")
    move(db, user, item, "production", qty, project_id=w.project_id, ref=w.no, note=note, unit_cost=unit_cost)
    if w.project_id:
        move(db, user, item, "issue", qty, project_id=w.project_id, ref=w.no, note=note)
    if w.done_qty + EPS >= w.qty:
        audit.record(db, user, "work_order", w.no, "status", w.status, "done", w.project_id)
        w.status = "done"
    if w.project_id:
        project = db.get(Project, w.project_id)
        if project is not None:
            sync_delivery(db, user, project, {w.part_no})
    return warnings


# ---------- requirement planning (MRP) ----------
def _bom_items(pv: ProjectView) -> dict[str, dict[str, Any]]:
    """What the current BOM needs: purchased/manufactured parts and fasteners (assemblies are built in-house)."""
    items: dict[str, dict[str, Any]] = {}
    unit = pv.fastener_defaults["unit"]
    for p in pv.parts(include_in_purchased=False):
        if not p["counted"] or (p["is_assembly"] and not p["is_purchased_assembly"]):
            continue
        items[p["part_no"]] = {
            "code": p["part_no"], "kind": "part", "description": p["file_name"], "unit": unit,
            "required": float(p["total_qty"]), "procurement": p["procurement"], "status": p["status"],
            "status_color": p["status_color"], "progress": p["progress"],
            "main_group": (p["main_groups"] or [""])[0], "material": p["material"],
            "manufacturer": p["manufacturer"], "unit_price": None,
            "done": p["progress"] == PROG_DONE, "hidden": p["hidden"], "part_name": p["part_name"],
            "make": p["status_kind"] == KIND_IMALAT,
            "plan": bool((pv.temin.get(p["procurement"]) or {"order": True})["order"]),
        }
    for f in pv.fasteners():
        desc = " ".join(x for x in (f["type"], f["std"], f["size"]) if x)
        items[f["key"]] = {
            "code": f["key"], "kind": "fastener", "description": desc or f["desc"], "unit": f["unit"],
            "required": float(f["order_qty"]), "procurement": "Hazır Alım", "status": f["order_status"],
            "status_color": f["status_color"], "progress": None, "main_group": (f["groups"] or [""])[0],
            "material": "", "manufacturer": f["supplier"], "unit_price": f["unit_price"],
            "done": f["order_status"] == FASTENER_ORDER_STATUSES[2], "hidden": f["hidden"], "part_name": "",
            "make": False, "plan": True,
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
                              .where(StockMove.project_id == project.id, StockMove.kind.in_(ISSUE_KINDS))
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
        elif not it["plan"]:
            action = ""
        elif it["make"]:
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
    """Committed (ordered/planned) vs actual (received/produced/issued) cost, by source, firm and main group, all in
    the base currency. Orders whose rate is unknown stay out of the totals and are listed under `unconverted`."""
    pv = ProjectView.load(db, project)
    groups = {code: it["main_group"] or tx("(Kök)") for code, it in _bom_items(pv).items()}
    rows: list[dict[str, Any]] = []      # {source, firm, group, committed, actual}
    missing_price = 0
    book = fx.Book(db)
    unconverted: dict[str, dict[str, Any]] = {}
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id,
                                                     PurchaseOrder.status != "cancelled")):
        rate = book.doc(po.currency, po.rate, po.order_date, po.created_at)
        for l in po.lines:
            if l.unit_price is None:
                missing_price += 1
                continue
            got = min(l.received_qty, l.qty)
            # A closed order will bring nothing more, so it commits only what was received
            committed = (got if po.status == "closed" else l.qty) * l.unit_price
            actual = got * l.unit_price
            if rate is None:
                u = unconverted.setdefault(po.currency, {"currency": po.currency, "committed": 0.0, "actual": 0.0,
                                                         "documents": []})
                u["committed"] += committed
                u["actual"] += actual
                if po.no not in u["documents"]:
                    u["documents"].append(po.no)
                continue
            rows.append({"source": "Satın alma", "firm": po.firm_name or "(Firma yok)",
                         "group": groups.get(l.code, tx("(BOM dışı)")), "committed": committed * rate,
                         "actual": actual * rate})
    for w in db.scalars(select(WorkOrder).where(WorkOrder.project_id == project.id, WorkOrder.status != "cancelled")):
        if w.unit_cost is None:
            missing_price += 1
            continue
        rows.append({"source": "Fason iş emri" if w.firm_name else "İç üretim", "firm": w.firm_name or "(İç üretim)",
                     "group": groups.get(w.part_no, tx("(BOM dışı)")),
                     "committed": (w.done_qty if w.status == "closed" else w.qty) * w.unit_cost,
                     "actual": min(w.done_qty, w.qty) * w.unit_cost})
    for m, code in db.execute(select(StockMove, StockItem.code).join(StockItem)
                              .where(StockMove.project_id == project.id,
                                     or_(and_(StockMove.kind.in_(ISSUE_KINDS), StockMove.ref == STOCK_REF),
                                         StockMove.kind.in_(("sale", "sale_return"))))):
        if m.unit_cost is None:
            missing_price += 1
            continue
        v = -m.qty * m.unit_cost
        rows.append({"source": "Stoktan", "firm": tx("(Stok)"), "group": groups.get(code, tx("(BOM dışı)")),
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
                     "group": groups.get(wo_parts.get(t.work_order_id or 0, ""), tx("(Genel işçilik)")),
                     "committed": v, "actual": v})

    def roll(key: str) -> list[dict[str, Any]]:
        acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            acc[r[key]][0] += r["committed"]
            acc[r[key]][1] += r["actual"]
        return sorted(({"name": k, "committed": num.money(c), "actual": num.money(a)} for k, (c, a) in acc.items()),
                      key=lambda x: -x["committed"])

    estimate = sum(f["total_price"] for f in pv.fasteners() if f["total_price"] is not None)
    return {"currency": book.base, "committed": num.money(sum(r["committed"] for r in rows)),
            "actual": num.money(sum(r["actual"] for r in rows)), "missing_price": missing_price,
            "unconverted": [{**u, "committed": num.money(u["committed"]), "actual": num.money(u["actual"])}
                            for u in unconverted.values()],
            "fastener_estimate": num.money(estimate),
            "by_source": roll("source"), "by_firm": roll("firm"), "by_group": roll("group")}
