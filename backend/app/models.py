"""Database models.

Part status lives on Tracking (project + part number) so it survives BOM
version changes. BomRow rows are immutable snapshots of an uploaded CSV.
Future modules (purchase orders, stock, work orders, costing) attach to
Part / Firm / Project through new tables without touching these.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String,
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
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_VIEWER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
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
    """An uploaded BOM CSV. Never deleted. status: pending | approved | undone | rejected."""
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), default="")

    __table_args__ = (UniqueConstraint("project_id", "part_no", name="uq_tracking_project_part"),)


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

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_fastener_setting"),)


class Firm(Base):
    """Manufacturers / suppliers. kind: manufacturer | supplier | both."""
    __tablename__ = "firms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="manufacturer")
    contact: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


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
