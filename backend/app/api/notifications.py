"""Bildirim merkezi: worked out from the live data for each user's modules, so nothing goes stale.

Only dismissals are stored. A key carries what the warning is about (a due date, a quantity), so the same
record warns again when that changes.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core import numbers as num
from ..models import (ROLE_ADMIN, AttendanceRequest, BomVersion, Employee, Invoice, LeaveRequest, NotificationRead, Project,
                      PurchaseOrder, SalesOrder, StockItem, User, WorkOrder)
from ..auth import is_https
from ..permissions import can
from ..services import commerce, erp
from ..services.settings import signup_enabled
from . import chat
from .deps import any_user, get_db
from .leave import KINDS

router = APIRouter(tags=["notifications"])

ADMIN_KIND = "Yönetim"
DUE_SOON_DAYS = 7
DECIDED_DAYS = 14
LIMIT = 200
DECISION = {"approved": "onaylandı", "rejected": "reddedildi"}


def _item(key: str, kind: str, title: str, detail: str, link: str, when: date | None = None,
          urgent: bool = False) -> dict[str, Any]:
    return {"key": key, "kind": kind, "title": title, "detail": detail, "link": link,
            "date": when.isoformat() if when else None, "urgent": urgent}


def _purchasing(db: Session, today: date) -> list[dict[str, Any]]:
    orders = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(("sent", "partial")),
                                                    PurchaseOrder.due_date < today))
    return [_item(f"po:{p.id}:{p.due_date}", "Satın alma", f"Geciken sipariş {p.no}",
                  f"{p.firm_name}, {(today - p.due_date).days} gün gecikti", "/purchasing", p.due_date, True)
            for p in orders]


def _stock(db: Session) -> list[dict[str, Any]]:
    low = db.scalars(select(StockItem).where(StockItem.min_qty > 0, StockItem.qty < StockItem.min_qty))
    return [_item(f"low:{i.id}:{i.qty:g}", "Stok", f"Düşük stok {i.code}",
                  f"{i.name}: {num.text(i.qty)} kaldı, en az {num.text(i.min_qty)}", "/stock") for i in low]


def _finance(db: Session, today: date) -> list[dict[str, Any]]:
    invoices = list(db.scalars(select(Invoice).where(Invoice.status == "issued", Invoice.due_date.is_not(None),
                                                     Invoice.due_date <= today + timedelta(days=DUE_SOON_DAYS))))
    paid = commerce.paid_by_invoice(db, [i.id for i in invoices])
    credited = commerce.credited_by_invoice(db, [i.id for i in invoices])
    out = []
    for inv in invoices:
        r = commerce.inv_out(inv, paid.get(inv.id, 0.0), False, credited=credited.get(inv.id, 0.0))
        if r["remaining"] <= 0:
            continue
        late = inv.due_date < today
        out.append(_item(f"inv:{inv.id}:{inv.due_date}:{late}", "Finans",
                         f"{'Vadesi geçen' if late else 'Vadesi yaklaşan'} fatura {inv.no or inv.id}",
                         f"{inv.firm_name}: {num.text(r['remaining'])} {inv.currency}", "/finance", inv.due_date, late))
    return out


def _sales(db: Session, today: date) -> list[dict[str, Any]]:
    orders = db.scalars(select(SalesOrder).where(SalesOrder.status.in_(commerce.SO_SHIPPING), SalesOrder.due_date < today))
    return [_item(f"so:{s.id}:{s.due_date}", "Satış", f"Geciken teslimat {s.no}",
                  f"{s.firm_name}, {(today - s.due_date).days} gün gecikti", "/sales", s.due_date, True)
            for s in orders]


def _workorders(db: Session, today: date) -> list[dict[str, Any]]:
    orders = db.scalars(select(WorkOrder).where(WorkOrder.status.in_(erp.WO_OPEN), WorkOrder.due_date < today))
    return [_item(f"wo:{w.id}:{w.due_date}", "İş emri", f"Geciken iş emri {w.no}",
                  f"{w.part_no}, {(today - w.due_date).days} gün gecikti", "/work-orders", w.due_date, True)
            for w in orders]


def _approvals(db: Session) -> list[dict[str, Any]]:
    names = dict(db.execute(select(Employee.id, Employee.name)).all())
    out = [_item(f"leave:{r.id}", "Onay bekliyor", f"İzin talebi: {names.get(r.employee_id, '')}",
                 f"{KINDS.get(r.kind, r.kind)}, {r.start_date:%d.%m.%Y} - {r.end_date:%d.%m.%Y}", "/attendance",
                 r.start_date)
           for r in db.scalars(select(LeaveRequest).where(LeaveRequest.status == "pending"))]
    out += [_item(f"fix:{r.id}", "Onay bekliyor", f"Mesai düzeltme: {names.get(r.employee_id, '')}",
                  f"{r.work_date:%d.%m.%Y}", "/attendance", r.work_date)
            for r in db.scalars(select(AttendanceRequest).where(AttendanceRequest.status == "pending"))]
    return out


def _boms(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(BomVersion.id, BomVersion.project_id, Project.name)
                      .join(Project, Project.id == BomVersion.project_id)
                      .where(BomVersion.status == "pending", Project.archived.is_(False)))
    return [_item(f"bom:{vid}", "Onay bekliyor", f"BOM onayı: {name}", "Yeni sürüm onay bekliyor", f"/p/{pid}/bom")
            for vid, pid, name in rows]


def _mine(db: Session, me: User, today: date) -> list[dict[str, Any]]:
    """Answers to this user's own requests."""
    ids = list(db.scalars(select(Employee.id).where(Employee.user_id == me.id)))
    if not ids:
        return []
    since = today - timedelta(days=DECIDED_DAYS)
    out = []
    for model, title in ((LeaveRequest, "İzin talebiniz"), (AttendanceRequest, "Mesai düzeltme talebiniz")):
        rows = db.scalars(select(model).where(model.employee_id.in_(ids), model.status.in_(tuple(DECISION)),
                                              model.decided_at >= since))
        out += [_item(f"my:{model.__tablename__}:{r.id}:{r.status}", "Talebim", f"{title} {DECISION[r.status]}",
                      r.decision_note or "", "/attendance", urgent=r.status == "rejected") for r in rows]
    return out


def _admin(db: Session, secure: bool) -> list[dict[str, Any]]:
    """Settings an admin should look at. Nothing here changes them. Their kind puts them on a banner as well."""
    out = []
    if not secure:
        out.append(_item("admin:https-off", ADMIN_KIND, "HTTPS kapalı",
                         "Şifreler ve belgeler yerel ağda şifresiz gidiyor. Yönetim > HTTPS sekmesinden açın.",
                         "/admin?tab=https", urgent=True))
    if signup_enabled(db):
        out.append(_item("admin:signup-on", ADMIN_KIND, "Hesap isteği açık",
                         "Giriş ekranında herkes hesap isteyebilir. İstemiyorsanız Yönetim > Kullanıcılar sekmesinden "
                         "kapatın.", "/admin?tab=users", urgent=True))
    return out


def collect(db: Session, me: User, secure: bool = True) -> list[dict[str, Any]]:
    today = date.today()
    out = _mine(db, me, today)
    if me.role == ROLE_ADMIN:
        out += _admin(db, secure)
    if can(me, "purchasing"):
        out += _purchasing(db, today)
    if can(me, "stock"):
        out += _stock(db)
    if can(me, "finance"):
        out += _finance(db, today)
    if can(me, "sales"):
        out += _sales(db, today)
    if can(me, "workorders"):
        out += _workorders(db, today)
    if can(me, "attendance", "edit"):
        out += _approvals(db)
    if can(me, "projects", "edit"):
        out += _boms(db)
    return out


@router.get("/notifications")
def notifications(request: Request, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    read = set(db.scalars(select(NotificationRead.key).where(NotificationRead.user_id == me.id)))
    every = collect(db, me, is_https(request))
    items = [i for i in every if i["key"] not in read]
    items.sort(key=lambda i: (not i["urgent"], i["date"] or "9999", i["key"]))
    # The bell can be cleared; the banner stays until the setting behind it changes
    return {"count": len(items), "items": items[:LIMIT], "warnings": [i for i in every if i["kind"] == ADMIN_KIND]}


@router.get("/notifications/feed")
def feed(request: Request, after: int = 0, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """What the desktop and phone turn into system notifications: new messages after `after`, and the open items
    of the bell. Each device remembers the keys it has announced. Nothing is marked as read here."""
    out = chat.feed(db, me, after) if can(me, "chat") else {"last_id": 0, "messages": []}
    read = set(db.scalars(select(NotificationRead.key).where(NotificationRead.user_id == me.id)))
    items = [i for i in collect(db, me, is_https(request)) if i["key"] not in read and i["kind"] != ADMIN_KIND]
    return {**out, "items": [{k: i[k] for k in ("key", "kind", "title", "detail", "link")} for i in items[:LIMIT]]}


class ReadIn(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=LIMIT)


@router.post("/notifications/read")
def mark_read(body: ReadIn, request: Request, me: User = Depends(any_user),
              db: Session = Depends(get_db)) -> dict[str, bool]:
    live = {i["key"] for i in collect(db, me, is_https(request))}
    # Dismissals of warnings that no longer exist have done their job; the rest stays
    db.execute(delete(NotificationRead).where(NotificationRead.user_id == me.id, NotificationRead.key.not_in(live)))
    have = set(db.scalars(select(NotificationRead.key).where(NotificationRead.user_id == me.id)))
    db.add_all(NotificationRead(user_id=me.id, key=k) for k in (set(body.keys) & live) - have)
    db.commit()
    return {"ok": True}
