"""Database models.

Part status lives on Tracking (project + part number) so it survives BOM
version changes. BomRow rows are immutable snapshots of an uploaded CSV.
ERP modules (purchase orders, stock, work orders, sales, invoices, payments,
employees and time entries) attach to Project / Firm through their own tables
and refer to parts by part number (fasteners by their type|std|size key), so
they never touch the BOM snapshots.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


ROLE_ADMIN = "admin"
ROLE_DESIGNER = "designer"      # Tasarımcı
ROLE_PLANNER = "planner"        # Planlama / Satın alma
ROLE_VIEWER = "viewer"          # İzleyici
ROLES = [ROLE_ADMIN, ROLE_DESIGNER, ROLE_PLANNER, ROLE_VIEWER]
ROLE_LABELS = {ROLE_ADMIN: "Admin", ROLE_DESIGNER: "Tasarımcı",
               ROLE_PLANNER: "Planlama/Satın alma", ROLE_VIEWER: "İzleyici"}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_VIEWER)
    # Per-module overrides of the role defaults, see app/permissions.py; None = role defaults only
    permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Self sign-up waiting for an admin: cannot log in until approved (then pending=False, active=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Bumped on password change/reset and deactivation; tokens carry it ("tv"), older tokens stop working
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    root_part_no: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("bom_versions.id", use_alter=True, ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Ürün ağacı work in progress: {tree, rev, by, at}; sent trees become BOM versions
    bom_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Part(Base):
    """Part master: one row per unique part number, shared across projects."""
    __tablename__ = "parts"
    id: Mapped[int] = mapped_column(primary_key=True)
    part_no: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    # A purchased assembly keeps this flag on every upload
    is_purchased_assembly: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BomVersion(Base):
    """An uploaded BOM CSV. Only rejected and undone versions can be deleted. status: pending | approved | undone | rejected."""
    __tablename__ = "bom_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str] = mapped_column(String(500), default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_by: Mapped[str] = mapped_column(String(64), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    previous_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compare_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stats_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Tracking snapshot taken right before approval, used to undo
    undo_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    rows: Mapped[list["BomRow"]] = relationship(back_populates="version", cascade="all, delete-orphan",
                                                order_by="BomRow.seq")


class BomRow(Base):
    __tablename__ = "bom_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("bom_versions.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(64))
    depth: Mapped[int] = mapped_column(Integer)
    parent_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str] = mapped_column(String(300))
    part_no: Mapped[str] = mapped_column(String(200))
    ext: Mapped[str] = mapped_column(String(16), default="")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    multiplier: Mapped[int] = mapped_column(Integer, default=1)
    total_qty: Mapped[int] = mapped_column(Integer, default=1)
    material: Mapped[str] = mapped_column(String(200), default="")
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    rev: Mapped[str] = mapped_column(String(32), default="")
    procurement: Mapped[str] = mapped_column(String(64), default="")
    coating: Mapped[str] = mapped_column(String(200), default="")
    parent_part_no: Mapped[str | None] = mapped_column(String(200), nullable=True)
    main_group: Mapped[str] = mapped_column(String(200), default="")
    in_purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    is_purchased_assembly: Mapped[bool] = mapped_column(Boolean, default=False)
    nonstandard: Mapped[bool] = mapped_column(Boolean, default=False)
    row_type: Mapped[str] = mapped_column(String(48))
    fastener_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fastener_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fastener_desc: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fastener_std: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fastener_size: Mapped[str | None] = mapped_column(String(100), nullable=True)

    version: Mapped[BomVersion] = relationship(back_populates="rows")

    __table_args__ = (Index("ix_bom_rows_version_seq", "version_id", "seq"),
                      Index("ix_bom_rows_part_no", "part_no"))


class Tracking(Base):
    """Per project + part status that carries over between BOM versions."""
    __tablename__ = "tracking"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    part_no: Mapped[str] = mapped_column(String(200))
    procurement_override: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[str] = mapped_column(String(32), default="Bekliyor")
    note: Mapped[str] = mapped_column(Text, default="")
    t35_note: Mapped[str] = mapped_column(Text, default="")
    manufacturer: Mapped[str] = mapped_column(String(100), default="")
    material_status: Mapped[str] = mapped_column(String(64), default="")
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Shown dimmed in the lists; quantities and statuses do not change
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), default="")

    __table_args__ = (UniqueConstraint("project_id", "part_no", name="uq_tracking_project_part"),)


class PartName(Base):
    """Human name of a part. Shared by all projects, so a number is named once."""
    __tablename__ = "part_names"
    part_no: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), default="")


class MissingRow(Base):
    """Eksik / fazla adet satırı: extra quantity to produce, with its own progress."""
    __tablename__ = "missing_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    part_no: Mapped[str] = mapped_column(String(200), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(String(300), default="")
    progress: Mapped[str] = mapped_column(String(32), default="Bekliyor")
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartAlias(Base):
    """alias (e.g. T01_2000_0002-P) -> canonical part_no (T01_2000_0002)."""
    __tablename__ = "part_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(200), unique=True)
    part_no: Mapped[str] = mapped_column(String(200), index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FastenerRule(Base):
    """Admin-editable fastener name pattern (see core.fastener.DEFAULT_RULES)."""
    __tablename__ = "fastener_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    pattern: Mapped[str] = mapped_column(String(500))
    type: Mapped[str] = mapped_column(String(100))
    desc: Mapped[str] = mapped_column(String(200), default="")
    std: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[str] = mapped_column(String(100), default="")
    d: Mapped[str] = mapped_column(String(50), default="")
    l: Mapped[str] = mapped_column(String(50), default="")
    maps: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FastenerSetting(Base):
    """Per project + fastener item (key = type|std|size) ordering info."""
    __tablename__ = "fastener_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(200))
    spare_pct: Mapped[float] = mapped_column(Float, default=10.0)
    supplier: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(20), default="Adet")
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_status: Mapped[str] = mapped_column(String(32), default="Sipariş Verilmedi")
    note: Mapped[str] = mapped_column(Text, default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_fastener_setting"),)


class Firm(Base):
    """Cari kart: manufacturers, suppliers and customers. kind: manufacturer | supplier | both | customer."""
    __tablename__ = "firms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="manufacturer")
    contact: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Supplier card (tedarikçi kartı)
    phone: Mapped[str] = mapped_column(String(50), default="", server_default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    address: Mapped[str] = mapped_column(Text, default="", server_default="")
    tax_office: Mapped[str] = mapped_column(String(100), default="", server_default="")
    tax_no: Mapped[str] = mapped_column(String(30), default="", server_default="")
    lead_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Setting(Base):
    """Key/value business rules: t35_config, part_no_patterns, material_status_choices, ..."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | None] = mapped_column(JSON, nullable=True)


class Drawing(Base):
    """A technical drawing file name. Same name re-uploaded = new DrawingVersion."""
    __tablename__ = "drawings"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    filename_key: Mapped[str] = mapped_column(String(300), unique=True)  # casefolded
    base_name: Mapped[str] = mapped_column(String(300))
    ext: Mapped[str] = mapped_column(String(16))
    rev: Mapped[str | None] = mapped_column(String(32), nullable=True)
    part_no: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    match_via: Mapped[str | None] = mapped_column(String(20), nullable=True)  # exact|alias|rev-stripped|manual
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    # project the file was first uploaded from; used only to scope the "unmatched" list
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions: Mapped[list["DrawingVersion"]] = relationship(back_populates="drawing",
                                                            cascade="all, delete-orphan",
                                                            order_by="DrawingVersion.version_no")


class DrawingVersion(Base):
    __tablename__ = "drawing_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    drawing_id: Mapped[int] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))
    thumb_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    drawing: Mapped[Drawing] = relationship(back_populates="versions")


class ControlIssue(Base):
    """Control list item. Auto issues use key 'kind|part_no'; manual ones 'manual|<id>'."""
    __tablename__ = "control_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(100))
    part_no: Mapped[str] = mapped_column(String(300), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    levels: Mapped[list] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    status: Mapped[str] = mapped_column(String(16), default="Açık")   # Açık | Çözüldü
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    present: Mapped[bool] = mapped_column(Boolean, default=True)      # auto issue still detected
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_by: Mapped[str] = mapped_column(String(64), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_control_issue_key"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    entity: Mapped[str] = mapped_column(String(50))          # tracking | missing | bom | drawing | ...
    entity_id: Mapped[str] = mapped_column(String(300))      # usually part_no
    field: Mapped[str] = mapped_column(String(100), default="")
    old: Mapped[str | None] = mapped_column(Text, nullable=True)
    new: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(50), default="update")

    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)


# ---------- ERP: stock, purchasing, work orders ----------
class StockItem(Base):
    """Stock card. code = part number, or the fastener key (type|std|size)."""
    __tablename__ = "stock_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    kind: Mapped[str] = mapped_column(String(20), default="part")      # part | fastener | other
    unit: Mapped[str] = mapped_column(String(20), default="Adet")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    min_qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)   # moving average
    location: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    reorder_qty: Mapped[float] = mapped_column(Float, default=0.0)            # 0 = fill up to min_qty
    preferred_firm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # no FK: added by ALTER on SQLite


class StockMove(Base):
    """Stock ledger. qty is the signed change; issue = handed to a project (consumed)."""
    __tablename__ = "stock_moves"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("stock_items.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(20))       # erp.MOVE_KINDS
    qty: Mapped[float] = mapped_column(Float)
    balance: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    ref: Mapped[str] = mapped_column(String(100), default="")   # SA-2026-0001, IE-2026-0001, ...
    note: Mapped[str] = mapped_column(Text, default="")
    username: Mapped[str] = mapped_column(String(64), default="")


class PurchaseOrder(Base):
    """Satın alma siparişi. status: draft | sent | partial | received | closed | cancelled."""
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    no: Mapped[str] = mapped_column(String(30), unique=True)
    firm_id: Mapped[int | None] = mapped_column(ForeignKey("firms.id", ondelete="SET NULL"), nullable=True)
    firm_name: Mapped[str] = mapped_column(String(200), default="")     # kept if the firm is deleted
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="TRY")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    rate: Mapped[float | None] = mapped_column(Float, nullable=True)   # base currency per 1 unit, fixed on the document
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="PurchaseOrderLine.seq")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(200), default="", index=True)  # part_no / fastener key / free
    kind: Mapped[str] = mapped_column(String(20), default="part")           # part | fastener | other
    description: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(20), default="Adet")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    received_qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class PurchaseReceipt(Base):
    """One goods receipt or reversal (negative qty) of a purchase order line."""
    __tablename__ = "purchase_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_lines.id", ondelete="SET NULL"), nullable=True)
    qty: Mapped[float] = mapped_column(Float)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(300), default="")


class WorkOrder(Base):
    """İş emri for a manufactured part. firm_name empty = in-house, else fason (subcontract).
    status: planned | in_progress | done | cancelled."""
    __tablename__ = "work_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    no: Mapped[str] = mapped_column(String(30), unique=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"),
                                                   nullable=True, index=True)
    part_no: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    done_qty: Mapped[float] = mapped_column(Float, default=0.0)
    firm_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkOrderMaterial(Base):
    """Material a work order needs; issued_qty came out of stock onto the order's project."""
    __tablename__ = "work_order_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    wo_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(200), default="", index=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(20), default="Adet")
    planned_qty: Mapped[float] = mapped_column(Float, default=0.0)
    issued_qty: Mapped[float] = mapped_column(Float, default=0.0)


class WorkOrderOp(Base):
    """One step of a work order's route. status: pending | in_progress | done."""
    __tablename__ = "work_order_ops"
    id: Mapped[int] = mapped_column(primary_key=True)
    wo_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120), default="")
    planned_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    done_by: Mapped[str] = mapped_column(String(64), default="")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")


class SyncState(Base):
    """One row (id=1). rev goes up after every successful write request, so open screens on other
    computers know to refetch (GET /api/sync)."""
    __tablename__ = "sync_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SalesOrder(Base):
    """Teklif / satış siparişi. status: draft | quoted | confirmed | partial | delivered | cancelled | lost."""
    __tablename__ = "sales_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    no: Mapped[str] = mapped_column(String(30), unique=True)
    firm_id: Mapped[int | None] = mapped_column(ForeignKey("firms.id", ondelete="SET NULL"), nullable=True)
    firm_name: Mapped[str] = mapped_column(String(200), default="")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)     # teklif geçerlilik
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)        # teslim tarihi
    currency: Mapped[str] = mapped_column(String(8), default="TRY")
    tax_rate: Mapped[float] = mapped_column(Float, default=20.0)              # KDV %
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="SalesOrderLine.seq")


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    so_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(20), default="Adet")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_qty: Mapped[float] = mapped_column(Float, default=0.0)
    order: Mapped[SalesOrder] = relationship(back_populates="lines")


class SalesDelivery(Base):
    """One delivery (sevk) or return (negative qty) of a sales order line."""
    __tablename__ = "sales_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    so_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("sales_order_lines.id", ondelete="SET NULL"), nullable=True)
    qty: Mapped[float] = mapped_column(Float)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(300), default="")


class Invoice(Base):
    """Fatura. kind: sales (satış, bizim kestiğimiz) | purchase (alış, tedarikçinin faturası).
    status: draft | issued | cancelled; paid/partial/overdue come from the payments."""
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="sales", index=True)
    no: Mapped[str] = mapped_column(String(40), default="", index=True)     # supplier's number for purchase
    firm_id: Mapped[int | None] = mapped_column(ForeignKey("firms.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    firm_name: Mapped[str] = mapped_column(String(200), default="")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id", ondelete="SET NULL"),
                                                       nullable=True)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"),
                                                          nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="TRY")
    tax_rate: Mapped[float] = mapped_column(Float, default=20.0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.seq")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(20), default="Adet")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    source_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # sales or purchase order line
    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class Payment(Base):
    """Tahsilat (direction in, from a customer) or ödeme (direction out, to a supplier)."""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    direction: Mapped[str] = mapped_column(String(4), default="in", index=True)
    firm_id: Mapped[int | None] = mapped_column(ForeignKey("firms.id", ondelete="SET NULL"), nullable=True,
                                                index=True)
    firm_name: Mapped[str] = mapped_column(String(200), default="")
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="TRY")
    method: Mapped[str] = mapped_column(String(30), default="Havale/EFT")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    rate: Mapped[float | None] = mapped_column(Float, nullable=True)


class ExchangeRate(Base):
    """Value of one unit of a currency in the base currency on a day. source: tcmb | manual."""
    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("rate_date", "currency", name="uq_exchange_rate"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(8))
    rate: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(10), default="manual")


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(100), default="")
    department: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    hourly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)   # ₺/saat, işçilik maliyeti
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    annual_leave_days: Mapped[float | None] = mapped_column(Float, nullable=True)   # None = company default


class TimeEntry(Base):
    """Çalışma saati: who worked how long on which project / work order. Cost = hours * hourly_cost
    at entry time (kept, so later rate changes do not rewrite history)."""
    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    hours: Mapped[float] = mapped_column(Float, default=0.0)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id", ondelete="SET NULL"),
                                                      nullable=True, index=True)
    hourly_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attendance(Base):
    """Mesai: one shift of one employee. Times are the server's wall clock with no zone, as on a time sheet;
    work_date is the day the shift began, so a night shift belongs to its first day. No clock_out = still open."""
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    clock_in: Mapped[datetime] = mapped_column(DateTime)
    clock_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    updated_by: Mapped[str] = mapped_column(String(64), default="")   # a manager who corrected the shift


class LeaveRequest(Base):
    """İzin ve rapor. kind: annual | sick | excuse | unpaid. status: pending | approved | rejected | cancelled.
    days counts working days, fixed when the request is made."""
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="annual")
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    days: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[str] = mapped_column(String(64), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(300), default="")


class AttendanceRequest(Base):
    """A worker's request to add or correct a shift. Wall-clock times like Attendance.
    status: pending | approved | rejected | cancelled."""
    __tablename__ = "attendance_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    attendance_id: Mapped[int | None] = mapped_column(ForeignKey("attendance.id", ondelete="SET NULL"), nullable=True)
    work_date: Mapped[date] = mapped_column(Date)
    clock_in: Mapped[datetime] = mapped_column(DateTime)
    clock_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[str] = mapped_column(String(64), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(300), default="")


class UserPref(Base):
    """Per-user screen settings (saved views, column layouts, theme), so they follow the user between devices."""
    __tablename__ = "user_prefs"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class NotificationRead(Base):
    """A notification the user dismissed. Notifications are worked out on request; only this is stored."""
    __tablename__ = "notification_reads"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectTemplate(Base):
    """A reusable product tree: payload is the node list a new project starts from."""
    __tablename__ = "project_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    note: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[object] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Photo(Base):
    """A product photo, attached to a part number (global like drawings) or a stock item (by id)."""
    __tablename__ = "photos"
    __table_args__ = (Index("ix_photos_entity", "entity", "entity_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(20))        # part | stock
    entity_key: Mapped[str] = mapped_column(String(200))   # part_no or stock item id
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(500))
    # Small JPEG made by the browser at upload time; the original is served when it is missing
    thumb_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    caption: Mapped[str] = mapped_column(String(300), default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatRoom(Base):
    """A conversation: kind "direct" (exactly two users, dm_key "<low id>:<high id>") or "group"."""
    __tablename__ = "chat_rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="group")
    name: Mapped[str] = mapped_column(String(120), default="")
    dm_key: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Time of the last message, for sorting the room list
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["ChatMember"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class ChatMember(Base):
    __tablename__ = "chat_members"
    __table_args__ = (UniqueConstraint("room_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)   # may rename the group and manage members
    last_read_id: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    room: Mapped[ChatRoom] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class ChatMessage(Base):
    """kind: text (may carry one file), system (member changes, written by the server)."""
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_room", "room_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(120), default="")   # display name at send time
    kind: Mapped[str] = mapped_column(String(10), default="text")
    body: Mapped[str] = mapped_column(Text, default="")
    file_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumb_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
