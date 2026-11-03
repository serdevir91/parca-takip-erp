"""Ana sayfa: one call with the KPIs and to-do lists of every module the user may see."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (AuditLog, BomVersion, Invoice, Project, PurchaseOrder, SalesOrder, StockItem, TimeEntry, User,
                      WorkOrder)
from ..permissions import can
from ..services import commerce, erp
from .deps import any_user, get_db

router = APIRouter(tags=["overview"])

ENTITY_LABELS = {"tracking": "Parça", "bom": "BOM", "drawing": "Teknik resim", "purchase_order": "Satın alma",
                 "work_order": "İş emri", "stock": "Stok", "sales_order": "Satış", "invoice": "Fatura",
                 "payment": "Ödeme", "employee": "Personel", "time_entry": "Zaman", "firm": "Cari kart",
                 "user": "Kullanıcı", "project": "Proje", "photo": "Fotoğraf"}


def _count(db: Session, q: Any) -> int:
    return db.scalar(select(func.count()).select_from(q.subquery())) or 0


@router.get("/overview")
def overview(me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    today = date.today()
    out: dict[str, Any] = {"user": me.full_name or me.username, "today": today.isoformat()}
    if can(me, "projects"):
        out["projects"] = {
            "active": _count(db, select(Project.id).where(Project.archived.is_(False))),
            "pending_boms": _count(db, select(BomVersion.id).where(BomVersion.status == "pending")),
        }
    if can(me, "purchasing"):
        open_pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(erp.PO_OPEN))))
        late = [erp.po_out(p, False) for p in open_pos if p.due_date and p.due_date < today and p.status != "draft"]
        out["purchasing"] = {"open": len(open_pos), "overdue": len(late),
                             "open_value": round(sum(erp.po_out(p, False)["total"] for p in open_pos), 2),
                             "late": sorted(late, key=lambda p: p["due_date"])[:6]}
    if can(me, "workorders"):
        wos = list(db.scalars(select(WorkOrder).where(WorkOrder.status.in_(erp.WO_OPEN))))
        out["workorders"] = {"open": len(wos), "in_progress": sum(1 for w in wos if w.status == "in_progress"),
                             "overdue": sum(1 for w in wos if w.due_date and w.due_date < today)}
    if can(me, "stock"):
        low = list(db.scalars(select(StockItem).where(StockItem.min_qty > 0, StockItem.qty < StockItem.min_qty)
                              .order_by(StockItem.code)))
        out["stock"] = {"items": _count(db, select(StockItem.id)), "low": len(low),
                        "value": round(db.scalar(select(func.sum(StockItem.qty * StockItem.unit_cost))
                                                 .where(StockItem.qty > 0)) or 0.0, 2),
                        "low_items": [erp.stock_out(i) for i in low[:6]]}
    if can(me, "sales"):
        sos = list(db.scalars(select(SalesOrder).where(SalesOrder.status.in_(commerce.SO_OPEN))))
        rows = [commerce.so_out(s, False) for s in sos]
        out["sales"] = {"quotes": sum(1 for s in sos if s.status in ("draft", "quoted")),
                        "quote_value": round(sum(r["total"] for r in rows if r["status"] != "confirmed"), 2),
                        "confirmed": sum(1 for s in sos if s.status == "confirmed"),
                        "confirmed_value": round(sum(r["total"] for r in rows if r["status"] == "confirmed"), 2),
                        "late": sum(1 for r in rows if r["late"])}
    if can(me, "finance"):
        bal = commerce.balances(db)
        invs = list(db.scalars(select(Invoice).where(Invoice.status == "issued")))
        paid = commerce.paid_by_invoice(db, [i.id for i in invs])
        due = [commerce.inv_out(i, paid.get(i.id, 0.0), False) for i in invs]
        due = [r for r in due if r["remaining"] > 0 and r["due_date"] and r["due_date"] <= (today + timedelta(days=7)).isoformat()]
        out["finance"] = {"receivable": round(sum(b["receivable"] for b in bal), 2),
                          "payable": round(sum(b["payable"] for b in bal), 2),
                          "overdue_receivable": round(sum(b["overdue_receivable"] for b in bal), 2),
                          "overdue_payable": round(sum(b["overdue_payable"] for b in bal), 2),
                          "due_soon": sorted(due, key=lambda r: r["due_date"])[:8]}
    if can(me, "hr"):
        since = today.replace(day=1)
        hours = db.scalar(select(func.sum(TimeEntry.hours)).where(TimeEntry.work_date >= since)) or 0.0
        out["hr"] = {"month_hours": round(hours, 2)}
    # last 30 days of activity, per day, for the trend chart; recent entries for the feed
    since = today - timedelta(days=29)
    per_day: dict[str, int] = defaultdict(int)
    for ts in db.scalars(select(AuditLog.ts).where(AuditLog.ts >= since)):
        per_day[ts.date().isoformat()] += 1
    out["activity"] = [{"date": (since + timedelta(days=i)).isoformat(),
                        "count": per_day[(since + timedelta(days=i)).isoformat()]} for i in range(30)]
    names = dict(db.execute(select(Project.id, Project.name)).all())
    out["recent"] = [{"ts": a.ts.isoformat(), "user": a.username, "entity": ENTITY_LABELS.get(a.entity, a.entity),
                      "entity_id": a.entity_id, "field": a.field, "action": a.action, "new": a.new,
                      "project": names.get(a.project_id or 0)}
                     for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(12))]
    return out
