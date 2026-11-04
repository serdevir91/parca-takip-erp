"""Command line tools: python -m app.cli <command>

  seed          demo database from the sample files (main assembly + T01_0004 sub-assembly)
  backup        take a backup now (--daemon: every day at --at HH:MM, used by the compose service)
  restore FILE  restore a backup tar (overwrites database and data directory)
  create-admin  create an admin user or reset an existing user to admin with a new password
  migrate       bring the database schema up to date (alembic upgrade head)
  serve         Docker-free run: migrate, then web server (API + built frontend) and daily backup
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from .auth import hash_password
from .config import get_settings
from .db import SessionLocal, engine
from .models import ROLE_ADMIN, Part, Project, Tracking, User
from .services import audit, backup as backup_svc, fx, system
from .services.bootstrap import seed_defaults

log = logging.getLogger("erp.cli")

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SEED_DIR = BACKEND_DIR / "tests" / "data"
MAIN_PROJECT = "Örnek Makine (Demo)"
SUB_PROJECT = "T01_0004 Alt Montaj (Demo)"
PURCHASED_DEMO = ["TSDacikboy"]


def _prepare_db() -> None:
    """SQLite dev databases get their tables from the models; PostgreSQL from Alembic."""
    if get_settings().database_url.startswith("sqlite"):
        from .db import Base
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_defaults(db)


# ---------- seed ----------
def _upload_and_approve(db: Session, project: Project, path: Path, user: User | None, note: str) -> None:
    from .services.bomimport import approve, upload_bom
    v = upload_bom(db, project, path.name, path.read_bytes(), user, note=note)
    cj = v.compare_json or {}
    removed, added = set(cj.get("removed") or []), set(cj.get("added") or [])
    # "-P" renames inherit the old status, as a user would confirm on the compare screen
    pairs = [{"removed": a[:-2], "added": a} for a in sorted(added) if a.endswith("-P") and a[:-2] in removed]
    approve(db, v, user, alias_accept=pairs)
    db.flush()


def _apply_t35(db: Session, project: Project, path: Path, user: User | None) -> int:
    from .core.status import PROG_DONE
    from .core.t35 import build_preview, read_t35
    from .services.settings import t35_config
    from .services.state import ProjectView
    pv = ProjectView.load(db, project)
    parts = {p["part_no"]: {"rev": p.get("rev") or "", "total_qty": p.get("total_qty"),
                            "produced": (pv.tracking.get(p["part_no"]) or Tracking()).progress == PROG_DONE}
             for p in pv.parts(include_in_purchased=False)}
    preview = build_preview(read_t35(path.read_bytes()), parts, t35_config(db), pv.aliases)
    n = 0
    for u in preview.updates:
        t = pv.tracking.get(u["part_no"])
        if t is None:
            continue
        changes = {"progress": u["progress"]}
        if u.get("manufacturer"):
            changes["manufacturer"] = u["manufacturer"]
        if u.get("material_status"):
            changes["material_status"] = u["material_status"]
        note = u.get("note") or ""
        if u.get("marked"):
            note = (note + " | " if note else "") + "Dış listede kırmızı işaretli"
        if note:
            changes["t35_note"] = note
        n += audit.record_changes(db, user, t, changes, "tracking", t.part_no, project.id) and 1
    return n


def _seed_erp(db, project: Project, user: User | None) -> None:
    """Demo ERP data: a partly received purchase order, a running work order and a low stock card."""
    from datetime import date, timedelta

    from .models import Firm, PurchaseOrder, WorkOrder
    from .services import erp

    firms = {}
    for name, kind, lead in (("Demo Tedarik A.Ş.", "supplier", 10), ("Demo Fason Talaşlı İmalat", "manufacturer", 15)):
        f = db.scalar(select(Firm).where(Firm.name == name))
        if f is None:
            f = Firm(name=name, kind=kind, contact="Satış", phone="0212 555 00 00", email="satis@example.com",
                     lead_days=lead, note="Örnek veri")
            db.add(f)
            db.flush()
        firms[kind] = f
    need = erp.requirements(db, project)
    buy = [r for r in need if r["action"] == "purchase"][:4]
    make = [r for r in need if r["action"] == "work_order"][:2]
    if buy:
        po = PurchaseOrder(no=erp.next_no(db, PurchaseOrder), firm_id=firms["supplier"].id,
                           firm_name=firms["supplier"].name, project_id=project.id, status="draft",
                           due_date=date.today() + timedelta(days=10), created_by=user.username if user else "",
                           note="Örnek sipariş")
        erp.set_lines(po, [{"code": r["code"], "kind": r["kind"], "description": r["description"], "unit": r["unit"],
                            "qty": r["shortage"], "unit_price": 25.0 + 10 * i} for i, r in enumerate(buy)])
        db.add(po)
        db.flush()
        erp.set_po_status(db, user, po, "sent")
        erp.receive(db, user, po, [(po.lines[0], po.lines[0].qty)], "Demo irsaliye")
    for i, r in enumerate(make):
        w = WorkOrder(no=erp.next_no(db, WorkOrder), project_id=project.id, part_no=r["code"],
                      description=r["description"], qty=r["shortage"], done_qty=0.0,
                      firm_name=firms["manufacturer"].name if i else "", status="planned", unit_cost=150.0,
                      due_date=date.today() + timedelta(days=7 + i), created_by=user.username if user else "")
        db.add(w)
        db.flush()
        if i == 0:
            erp.set_wo_status(db, user, w, "in_progress")
    item = erp.stock_item(db, "DEMO-SARF-001", "Kesme yağı (örnek)", "other", "Litre")
    if item.qty == 0:
        item.min_qty = 20
        erp.move(db, user, item, "in", 8, note="Açılış", unit_cost=95.0)
    _seed_commerce(db, project, user, po if buy else None, make)


def _seed_commerce(db, project: Project, user: User | None, po, made: list) -> None:
    """Demo sales, invoices, payments and work hours (needs a user for the document authors)."""
    from datetime import date, timedelta

    from .models import Employee, Firm, Payment, SalesOrder, TimeEntry, WorkOrder
    from .services import commerce

    if user is None:
        return
    today = date.today()
    cust = db.scalar(select(Firm).where(Firm.name == "Demo Makine Müşterisi Ltd."))
    if cust is None:
        cust = Firm(name="Demo Makine Müşterisi Ltd.", kind="customer", contact="Satın alma", phone="0216 444 00 00",
                    email="satinalma@example.com", tax_office="Ümraniye", tax_no="9876543210", note="Örnek veri")
        db.add(cust)
        db.flush()
    lines = [{"code": project.root_part_no or "MAKINE", "description": f"{project.name} makinesi", "qty": 1,
              "unit_price": 850000.0},
             {"description": "Montaj ve devreye alma", "unit": "Gün", "qty": 5, "unit_price": 12000.0}]
    orders = []
    for status, disc, days in (("confirmed", 5.0, 30), ("quoted", 0.0, 15)):
        so = SalesOrder(no=commerce.next_no(db, SalesOrder), firm_id=cust.id, firm_name=cust.name,
                        project_id=project.id, status="draft", order_date=today - timedelta(days=12),
                        valid_until=today + timedelta(days=days), due_date=today + timedelta(days=45),
                        discount_pct=disc, created_by=user.username, note="Örnek veri")
        commerce.set_so_lines(so, lines if status == "confirmed" else lines[1:])
        db.add(so)
        db.flush()
        commerce.set_so_status(db, user, so, "quoted")
        if status == "confirmed":
            commerce.set_so_status(db, user, so, "confirmed")
        orders.append(so)
    inv = commerce.invoice_from_so(db, user, orders[0])
    inv.status, inv.due_date = "issued", today + timedelta(days=20)
    db.add(Payment(direction="in", firm_id=cust.id, firm_name=cust.name, invoice_id=inv.id,
                   pay_date=today - timedelta(days=2), amount=300000.0, method="Havale/EFT", note="Avans",
                   created_by=user.username))
    if po is not None:
        pinv = commerce.invoice_from_po(db, user, po, "TDR-2026-0412", 20.0)
        pinv.status, pinv.due_date = "issued", today - timedelta(days=3)
    people = []
    for name, title, dept, rate in (("Ahmet Yılmaz", "Montaj ustası", "Üretim", 320.0),
                                    ("Elif Kaya", "Tasarım mühendisi", "Mühendislik", 480.0),
                                    ("Murat Demir", "CNC operatörü", "Üretim", 290.0)):
        e = db.scalar(select(Employee).where(Employee.name == name))
        if e is None:
            e = Employee(name=name, title=title, department=dept, hourly_cost=rate,
                         start_date=today - timedelta(days=400), note="Örnek veri")
            db.add(e)
            db.flush()
        people.append(e)
    wo = db.scalar(select(WorkOrder).where(WorkOrder.project_id == project.id).order_by(WorkOrder.id))
    for d in range(1, 8):
        day = today - timedelta(days=d)
        if day.weekday() >= 5:
            continue
        for i, e in enumerate(people):
            db.add(TimeEntry(employee_id=e.id, work_date=day, hours=8.0 if i != 1 else 6.0, project_id=project.id,
                             work_order_id=wo.id if wo and i == 2 else None, hourly_cost=e.hourly_cost,
                             note="Örnek veri", created_by=user.username))


def seed(data_dir: Path, force: bool = False) -> None:
    _prepare_db()
    files = {
        "old": data_dir / "BOM_T01_0000_0000_2026-10-31.csv",
        "new": data_dir / "BOM_T01_0000_0000_2026-11-02.csv",
        "t35": data_dir / "T-35_Guncel_Durumu.xlsx",
        "v": [data_dir / f"BOM_T01_0004_0000_v{i}.csv" for i in (1, 2, 3)],
    }
    missing = [str(p) for p in [files["old"], files["new"], files["t35"], *files["v"]] if not p.is_file()]
    if missing:
        raise SystemExit("Örnek dosyalar bulunamadı: " + ", ".join(missing))
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.role == ROLE_ADMIN, User.active.is_(True)).order_by(User.id))
        for pno in PURCHASED_DEMO:
            p = db.scalar(select(Part).where(Part.part_no == pno))
            if p is None:
                db.add(Part(part_no=pno, is_purchased_assembly=True))
            else:
                p.is_purchased_assembly = True
        db.flush()
        for name in (MAIN_PROJECT, SUB_PROJECT):
            old = db.scalar(select(Project).where(Project.name == name))
            if old is not None:
                if not force:
                    print(f"'{name}' zaten var, atlandı (yeniden oluşturmak için --force)")
                    continue
                db.delete(old)
                db.flush()
            if name == MAIN_PROJECT:
                p = Project(name=name, root_part_no="T01_0000_0000", description="Örnek veri: ana montaj")
                db.add(p)
                db.flush()
                _upload_and_approve(db, p, files["old"], user, "Demo: ilk sürüm")
                _upload_and_approve(db, p, files["new"], user, "Demo: güncel sürüm")
                n = _apply_t35(db, p, files["t35"], user)
                print(f"'{name}' oluşturuldu: 2 BOM sürümü, T-35 listesinden {n} parça güncellendi")
            else:
                p = Project(name=name, root_part_no="T01_0004_0000", description="Örnek veri: 3 sürümlü alt montaj")
                db.add(p)
                db.flush()
                for i, f in enumerate(files["v"], 1):
                    _upload_and_approve(db, p, f, user, f"Demo: v{i}")
                _seed_erp(db, p, user)
                print(f"'{name}' oluşturuldu: 3 BOM sürümü, örnek sipariş, iş emri, stok, satış, fatura, personel")
            audit.record(db, user, "project", p.id, "seed", None, name, p.id, action="create")
        db.commit()


# ---------- create-admin ----------
def create_admin(username: str, password: str, full_name: str = "") -> str:
    if len(password) < 6:
        raise SystemExit("Şifre en az 6 karakter olmalı")
    _prepare_db()
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == username))
        if u is None:
            u = User(username=username, full_name=full_name or "Yönetici", role=ROLE_ADMIN,
                     password_hash=hash_password(password), active=True)
            db.add(u)
            db.flush()
            audit.record(db, None, "user", u.id, "username", None, username, action="create")
            msg = f"Yönetici '{username}' oluşturuldu"
        else:
            audit.record_changes(db, None, u, {"role": ROLE_ADMIN, "active": True}, "user", u.id)
            u.password_hash = hash_password(password)
            if full_name:
                u.full_name = full_name
            audit.record(db, None, "user", u.id, "password", None, "sıfırlandı")
            msg = f"'{username}' yönetici yapıldı ve şifresi sıfırlandı"
        db.commit()
    return msg


# ---------- backup ----------
def _record_backup(info: backup_svc.BackupInfo) -> None:
    try:
        with SessionLocal() as db:
            audit.record(db, None, "backup", info.name, "size", None, info.size, action="create")
            db.commit()
    except Exception as e:  # noqa: BLE001 - the backup itself succeeded
        log.warning("Backup audit entry failed: %s", e)


def backup_once() -> backup_svc.BackupInfo:
    info = backup_svc.create_backup()
    _record_backup(info)
    print(f"Yedek alındı: {info.path} ({info.size / 1_048_576:.1f} MB)")
    return info


def _next_run(at: str, now: datetime) -> datetime:
    hh, mm = (int(x) for x in at.split(":"))
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return nxt if nxt > now else nxt + timedelta(days=1)


def _saved_backup_time(at: str) -> str:
    """Time from Sistem Ayarları if one was saved, else `at`. Also refreshes the keep days of this process."""
    try:
        with SessionLocal() as db:
            system.apply_runtime(db)
            return (system.saved(db).get("files") or {}).get("backup_time") or at
    except Exception as e:  # noqa: BLE001
        print(f"Ayarlar okunamadı: {e}", file=sys.stderr, flush=True)
        return at


def daily_rates(last: date | None) -> date:
    """Try the Merkez Bankası rates once a day, best effort: most sites have no internet, and nothing here may
    disturb the server. Returns the day of the last try."""
    today = date.today()
    if last == today:
        return today
    try:
        with SessionLocal() as db:
            fx.fetch(db)
            db.commit()
    except fx.RateFetchError as e:
        print(f"Kurlar alınamadı: {e}", file=sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"Kur güncelleme hatası: {e}", file=sys.stderr, flush=True)
    return today


def backup_daemon(at: str) -> None:
    """Sleep until the backup time (local time, TZ env) every day and take a backup; never exits on errors.
    The same loop tries the daily exchange rate fetch."""
    start = at
    rates_day: date | None = None
    at = _saved_backup_time(start)
    print(f"Günlük yedekleme saati {at}, saklama {get_settings().backup_keep_days} gün", flush=True)
    while True:
        nxt = _next_run(at, datetime.now())
        print(f"Sonraki yedek: {nxt:%Y-%m-%d %H:%M}", flush=True)
        while (left := (nxt - datetime.now()).total_seconds()) > 0:
            rates_day = daily_rates(rates_day)
            time.sleep(min(left, 300))
            if (new := _saved_backup_time(start)) != at:
                at = new
                nxt = _next_run(at, datetime.now())
                print(f"Yedek saati değişti, sonraki yedek: {nxt:%Y-%m-%d %H:%M}", flush=True)
        _saved_backup_time(start)
        try:
            backup_once()
        except Exception as e:  # noqa: BLE001
            print(f"Yedekleme hatası: {e}", file=sys.stderr, flush=True)


# ---------- migrate / serve (Docker-free install) ----------
def migrate() -> None:
    """alembic upgrade head from any working directory. A SQLite database whose tables came from
    create_all (older dev setup) is stamped instead, since its schema already matches the models."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    # The desktop bundle ships the scripts as "migrations" so they cannot shadow the alembic package
    cfg.set_main_option("script_location", os.environ.get("ERP_MIGRATIONS_DIR") or str(BACKEND_DIR / "alembic"))
    insp = inspect(engine)
    if insp.has_table("users") and not insp.has_table("alembic_version"):
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


def serve(host: str, port: int, backup: bool) -> None:
    import uvicorn

    cfg = get_settings()
    for d in (cfg.data_dir, cfg.backup_dir):
        d.mkdir(parents=True, exist_ok=True)
    migrate()
    if cfg.spa_dir is None:
        print("Uyarı: frontend/dist bulunamadı, yalnızca API çalışacak (cd frontend && npm run build)",
              file=sys.stderr, flush=True)
    if backup:
        threading.Thread(target=backup_daemon, args=(cfg.backup_time,), name="backup", daemon=True).start()
    from .services import discovery

    discovery.start_responder(port, cfg.app_version)
    print(f"LAB ERP: http://{'localhost' if host in ('0.0.0.0', '::') else host}:{port}", flush=True)
    # Clients connect directly (no proxy in front), so only a local proxy may set X-Forwarded-For
    uvicorn.run("app.main:app", host=host, port=port, workers=1, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1", timeout_keep_alive=75, log_level="info")


def restore(path: Path, yes: bool) -> None:
    m = backup_svc.read_manifest(path)
    print(f"Yedek: {path.name}, tarih {m.get('created_at')}, sürüm {m.get('app_version')}, "
          f"veritabanı {m.get('db_kind')}, {m.get('data_files')} dosya")
    if not yes:
        ans = input("Mevcut veritabanı ve dosyaların ÜZERİNE yazılacak. Devam edilsin mi? (evet/hayır): ")
        if ans.strip().casefold() not in ("evet", "e", "yes", "y"):
            raise SystemExit("İptal edildi")
    backup_svc.restore_backup(path)
    print("Geri yükleme tamamlandı. Uygulamayı yeniden başlatın "
          "(Docker: docker compose restart backend, Docker'sız: ParcaTakipERP görevini yeniden başlatın)")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app.cli", description="LAB ERP komutları")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="Örnek verilerle demo veritabanı oluştur")
    s.add_argument("--data-dir", type=Path, default=Path(os.environ.get("ERP_SEED_DIR", DEFAULT_SEED_DIR)))
    s.add_argument("--force", action="store_true", help="Demo projelerini silip yeniden oluştur")
    b = sub.add_parser("backup", help="Yedek al")
    b.add_argument("--daemon", action="store_true", help="Her gün --at saatinde yedek al")
    b.add_argument("--at", default=get_settings().backup_time, help="HH:MM (varsayılan 02:00)")
    r = sub.add_parser("restore", help="Yedekten geri yükle")
    r.add_argument("file", type=Path)
    r.add_argument("--yes", action="store_true", help="Onay sormadan geri yükle")
    c = sub.add_parser("create-admin", help="Yönetici oluştur veya şifresini sıfırla")
    c.add_argument("--username", default=get_settings().admin_user)
    c.add_argument("--password", default=os.environ.get("ERP_NEW_ADMIN_PASSWORD"))
    c.add_argument("--full-name", default="")
    sub.add_parser("migrate", help="Veritabanı şemasını güncelle")
    v = sub.add_parser("serve", help="Docker'sız çalıştır: web sunucusu + günlük yedek")
    v.add_argument("--host", default=os.environ.get("ERP_HOST", "0.0.0.0"))
    v.add_argument("--port", type=int, default=int(os.environ.get("ERP_HTTP_PORT", "8000")))
    v.add_argument("--no-backup", action="store_true", help="Günlük yedeği çalıştırma")
    a = ap.parse_args(argv)

    if a.cmd == "seed":
        seed(a.data_dir, a.force)
    elif a.cmd == "backup":
        if a.daemon:
            backup_daemon(a.at)
        else:
            try:
                backup_once()
            except backup_svc.BackupError as e:
                print(f"Yedekleme hatası: {e}", file=sys.stderr)
                return 1
    elif a.cmd == "restore":
        path = a.file
        if not path.is_file():
            path = get_settings().backup_dir / a.file.name
        if not path.is_file():
            raise SystemExit(f"Yedek bulunamadı: {a.file}")
        restore(path, a.yes)
    elif a.cmd == "migrate":
        migrate()
    elif a.cmd == "serve":
        serve(a.host, a.port, not a.no_backup)
    elif a.cmd == "create-admin":
        pw = a.password
        if not pw:
            import getpass
            pw = getpass.getpass("Yeni şifre: ")
        print(create_admin(a.username, pw, a.full_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
