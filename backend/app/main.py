"""FastAPI application. Routers in app/api/*.py that expose `router` are mounted under /api."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from . import api as api_pkg
from .config import get_settings
from .db import SessionLocal, engine
from .services import sync
from .services.bootstrap import seed_defaults

log = logging.getLogger("erp")


def _ensure_dirs() -> None:
    cfg = get_settings()
    for d in (cfg.bom_dir, cfg.drawing_dir, cfg.thumb_dir, cfg.photo_dir, cfg.chat_dir):
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


@app.middleware("http")
async def live_sync(request: Request, call_next):
    response = await call_next(request)
    if sync.counts(request.method, request.url.path, response.status_code):
        await run_in_threadpool(sync.bump, engine)
    return response


@app.get("/api/sync", tags=["system"])
def sync_rev() -> dict:
    """Write counter for live refresh on other computers (no login needed: it is just a number)."""
    return {"rev": sync.current(engine)}


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


# ---------- SPA (Docker-free install only; in Docker nginx serves the frontend) ----------
_spa = get_settings().spa_dir
if _spa is not None:
    import mimetypes

    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # The Windows registry can map .js to text/plain, which browsers refuse for ES modules
    for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"),
                        (".svg", "image/svg+xml"), (".wasm", "application/wasm"), (".json", "application/json")):
        mimetypes.add_type(_type, _ext)

    app.mount("/assets", StaticFiles(directory=_spa / "assets", check_dir=False), name="assets")
    _spa_root = _spa.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "Not Found")
        f = (_spa_root / path).resolve()
        if path and f.is_file() and _spa_root in f.parents:
            return FileResponse(f)
        return FileResponse(_spa_root / "index.html", headers={"Cache-Control": "no-cache"})
