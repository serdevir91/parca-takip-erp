"""FastAPI application. Routers in app/api/*.py that expose `router` are mounted under /api."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import api as api_pkg
from .config import get_settings
from .db import SessionLocal, engine
from .services.bootstrap import seed_defaults

log = logging.getLogger("erp")


def _ensure_dirs() -> None:
    cfg = get_settings()
    for d in (cfg.bom_dir, cfg.drawing_dir, cfg.thumb_dir):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:  # pragma: no cover - read-only dev machines
            log.warning("Cannot create %s: %s", d, e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _ensure_dirs()
    if get_settings().database_url.startswith("sqlite"):
        # Dev/test convenience; PostgreSQL schema comes from Alembic (alembic upgrade head)
        from .db import Base
        from . import models  # noqa: F401
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_defaults(db)
    yield


app = FastAPI(title="Parça Takip ERP", version=get_settings().app_version, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/version", tags=["system"])
def version() -> dict:
    cfg = get_settings()
    return {"version": cfg.app_version, "update_feed_url": cfg.update_feed_url}


for _m in sorted(pkgutil.iter_modules(api_pkg.__path__), key=lambda m: m.name):
    _mod = importlib.import_module(f"{api_pkg.__name__}.{_m.name}")
    _router = getattr(_mod, "router", None)
    if _router is not None:
        app.include_router(_router, prefix="/api")
