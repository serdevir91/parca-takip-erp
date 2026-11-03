"""Backups: one tar file per run with the database dump and the data directory.

Layout of `erp_YYYYMMDD_HHMMSS.tar`:
  manifest.json      -> {created_at, app_version, db_kind, db_file, data_files}
  db.dump            -> PostgreSQL custom-format dump (pg_restore), or
  db.sqlite3         -> consistent SQLite copy (dev/test)
  data/...           -> uploaded BOM files, drawings and thumbnails

Files are written as `.partial` first and renamed when complete, so a crashed run
never shows up as a valid backup. Backups older than `backup_keep_days` are pruned,
but the newest backup is always kept.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from ..config import get_settings

NAME_RE = re.compile(r"^erp_(\d{8}_\d{6})\.tar$")
_lock = threading.Lock()


class BackupError(RuntimeError):
    pass


class BackupBusy(BackupError):
    """Another backup is running or one was just taken; retry later."""


@dataclass
class BackupInfo:
    name: str
    path: Path
    size: int
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.size, "created_at": self.created_at.isoformat()}


def _stamp_of(path: Path) -> datetime:
    m = NAME_RE.match(path.name)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def list_backups(backup_dir: Path | None = None) -> list[BackupInfo]:
    """Completed backups, newest first."""
    d = Path(backup_dir or get_settings().backup_dir)
    if not d.is_dir():
        return []
    out = [BackupInfo(p.name, p, p.stat().st_size, _stamp_of(p))
           for p in d.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    return sorted(out, key=lambda b: b.created_at, reverse=True)


def backup_path(name: str, backup_dir: Path | None = None) -> Path:
    """Resolve a backup by name; only plain `erp_*.tar` names are accepted (no paths)."""
    if not NAME_RE.match(name):
        raise BackupError("Geçersiz yedek adı")
    p = Path(backup_dir or get_settings().backup_dir) / name
    if not p.is_file():
        raise BackupError("Yedek bulunamadı")
    return p


def prune(keep_days: int, backup_dir: Path | None = None, now: datetime | None = None) -> list[str]:
    """Delete backups older than keep_days; the newest one always stays. Returns deleted names."""
    items = list_backups(backup_dir)
    if not items or keep_days <= 0:
        return []
    limit = (now or datetime.now(timezone.utc)) - timedelta(days=keep_days)
    deleted = []
    for b in items[1:]:
        if b.created_at < limit:
            b.path.unlink(missing_ok=True)
            deleted.append(b.name)
    d = Path(backup_dir or get_settings().backup_dir)
    for p in d.glob("erp_*.tar.partial"):  # leftovers of crashed runs
        if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) < limit:
            p.unlink(missing_ok=True)
    return deleted


def _pg_env(url) -> dict[str, str]:
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    return env


def _pg_args(url) -> list[str]:
    args = []
    if url.host:
        args += ["-h", url.host]
    if url.port:
        args += ["-p", str(url.port)]
    if url.username:
        args += ["-U", url.username]
    return args


def _dump_db(database_url: str, workdir: Path) -> tuple[str, Path]:
    url = make_url(database_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        src = url.database
        if not src or src == ":memory:":
            raise BackupError("Bellek içi SQLite veritabanı yedeklenemez")
        dst = workdir / "db.sqlite3"
        with sqlite3.connect(src) as s, sqlite3.connect(dst) as t:
            s.backup(t)
        return "sqlite", dst
    if backend == "postgresql":
        dst = workdir / "db.dump"
        cmd = ["pg_dump", *_pg_args(url), "-Fc", "--no-owner", "-f", str(dst), url.database or ""]
        try:
            r = subprocess.run(cmd, env=_pg_env(url), capture_output=True, text=True, timeout=3600)
        except FileNotFoundError as e:
            raise BackupError("pg_dump bulunamadı (postgresql-client kurulu değil)") from e
        if r.returncode != 0:
            raise BackupError(f"Veritabanı dökümü alınamadı: {r.stderr.strip()[-500:]}")
        return "postgresql", dst
    raise BackupError(f"Desteklenmeyen veritabanı: {backend}")


def create_backup(database_url: str | None = None, data_dir: Path | None = None,
                  backup_dir: Path | None = None, keep_days: int | None = None,
                  now: datetime | None = None) -> BackupInfo:
    """Dump the database and archive the data directory, then prune old backups."""
    cfg = get_settings()
    database_url = database_url or cfg.database_url
    data_dir = Path(data_dir or cfg.data_dir)
    backup_dir = Path(backup_dir or cfg.backup_dir)
    keep_days = cfg.backup_keep_days if keep_days is None else keep_days
    if not _lock.acquire(blocking=False):
        raise BackupBusy("Yedekleme zaten çalışıyor")
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = now or datetime.now(timezone.utc)
        name = f"erp_{ts.strftime('%Y%m%d_%H%M%S')}.tar"
        final = backup_dir / name
        if final.exists():
            raise BackupBusy("Aynı saniyede başka bir yedek alındı, tekrar deneyin")
        partial = backup_dir / (name + ".partial")
        with tempfile.TemporaryDirectory(prefix="erp_bk_", dir=backup_dir) as tmp:
            kind, dump = _dump_db(database_url, Path(tmp))
            n_files = sum(1 for p in data_dir.rglob("*") if p.is_file()) if data_dir.is_dir() else 0
            manifest = {"created_at": ts.isoformat(), "app_version": cfg.app_version, "db_kind": kind,
                        "db_file": dump.name, "data_files": n_files}
            mpath = Path(tmp) / "manifest.json"
            mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                with tarfile.open(partial, "w") as tar:
                    tar.add(mpath, arcname="manifest.json")
                    tar.add(dump, arcname=dump.name)
                    if data_dir.is_dir():
                        tar.add(data_dir, arcname="data")
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
        partial.rename(final)
        prune(keep_days, backup_dir, now=ts)
        return BackupInfo(name, final, final.stat().st_size, _stamp_of(final))
    finally:
        _lock.release()


def read_manifest(path: Path) -> dict[str, Any]:
    with tarfile.open(path, "r") as tar:
        f = tar.extractfile("manifest.json")
        if f is None:
            raise BackupError("Yedekte manifest.json yok")
        return json.loads(f.read().decode("utf-8"))


def restore_backup(path: Path, database_url: str | None = None, data_dir: Path | None = None) -> dict[str, Any]:
    """Restore database and data directory from a backup tar. Overwrites current data.

    Run it with the backend stopped (or no users active); see README "Geri yükleme"."""
    cfg = get_settings()
    database_url = database_url or cfg.database_url
    data_dir = Path(data_dir or cfg.data_dir)
    manifest = read_manifest(path)
    url = make_url(database_url)
    with tempfile.TemporaryDirectory(prefix="erp_rs_") as tmp:
        t = Path(tmp)
        with tarfile.open(path, "r") as tar:
            tar.extractall(t, filter="data")
        dump = (t / str(manifest["db_file"])).resolve()
        if Path(t).resolve() not in dump.parents:
            raise ValueError("Yedek dosyası bozuk: veritabanı dosyası yolu geçersiz")
        if manifest["db_kind"] == "sqlite":
            if url.get_backend_name() != "sqlite":
                raise BackupError("SQLite yedeği PostgreSQL'e geri yüklenemez")
            with sqlite3.connect(dump) as s, sqlite3.connect(url.database) as d:
                s.backup(d)
        else:
            if url.get_backend_name() != "postgresql":
                raise BackupError("PostgreSQL yedeği bu veritabanına geri yüklenemez")
            cmd = ["pg_restore", *_pg_args(url), "--clean", "--if-exists", "--no-owner",
                   "-d", url.database or "", str(dump)]
            r = subprocess.run(cmd, env=_pg_env(url), capture_output=True, text=True, timeout=3600)
            if r.returncode != 0:
                raise BackupError(f"Veritabanı geri yüklenemedi: {r.stderr.strip()[-500:]}")
        src = t / "data"
        if src.is_dir():
            data_dir.mkdir(parents=True, exist_ok=True)
            for child in data_dir.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
            for child in src.iterdir():
                shutil.move(str(child), str(data_dir / child.name))
    return manifest


def status(backup_dir: Path | None = None) -> dict[str, Any]:
    """Summary for the admin screen."""
    cfg = get_settings()
    d = Path(backup_dir or cfg.backup_dir)
    items = list_backups(d)
    free = None
    try:
        free = shutil.disk_usage(d if d.exists() else d.parent).free
    except OSError:
        pass
    return {"backup_dir": str(d), "keep_days": cfg.backup_keep_days, "count": len(items),
            "total_size": sum(b.size for b in items), "free_bytes": free,
            "last": items[0].to_dict() if items else None, "running": _lock.locked(),
            "items": [b.to_dict() for b in items]}
