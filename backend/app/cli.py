"""Command line tools: python -m app.cli <command>

  seed          demo database from the sample files (T-35 main assembly + T01_0004 sub-assembly)
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
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from .auth import hash_password
from .config import get_settings
from .db import SessionLocal, engine
from .models import ROLE_ADMIN, Part, Project, Tracking, User
from .services import audit, backup as backup_svc
from .services.bootstrap import seed_defaults

log = logging.getLogger("erp.cli")

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SEED_DIR = BACKEND_DIR / "tests" / "data"
MAIN_PROJECT = "T-35 (Demo)"
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
                print(f"'{name}' oluşturuldu: 3 BOM sürümü")
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


def backup_daemon(at: str) -> None:
    """Sleep until `at` (local time, TZ env) every day and take a backup; never exits on errors."""
    print(f"Günlük yedekleme saati {at}, saklama {get_settings().backup_keep_days} gün", flush=True)
    while True:
        nxt = _next_run(at, datetime.now())
        print(f"Sonraki yedek: {nxt:%Y-%m-%d %H:%M}", flush=True)
        while (left := (nxt - datetime.now()).total_seconds()) > 0:
            time.sleep(min(left, 300))
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
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
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
    print(f"Parça Takip ERP: http://{'localhost' if host in ('0.0.0.0', '::') else host}:{port}", flush=True)
    uvicorn.run("app.main:app", host=host, port=port, workers=1, proxy_headers=True,
                forwarded_allow_ips="*", timeout_keep_alive=75, log_level="info")


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
    ap = argparse.ArgumentParser(prog="python -m app.cli", description="Parça Takip ERP komutları")
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
