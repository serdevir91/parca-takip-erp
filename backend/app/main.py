"""FastAPI application. Routers in app/api/*.py that expose `router` are mounted under /api."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import DataError, IntegrityError
from starlette.concurrency import run_in_threadpool

from . import api as api_pkg
from .bodylimit import BodyLimit
from .config import get_settings
from .db import SessionLocal, engine
from .services import mailer, maintenance, sync, tls
from .services.bootstrap import seed_defaults
from app.core.i18n import set_lang, tx

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
        mailer.seal_stored(db)
    yield


_docs = get_settings().api_docs
app = FastAPI(title="LAB ERP", version=get_settings().app_version, lifespan=lifespan,
              docs_url="/api/docs" if _docs else None, openapi_url="/api/openapi.json" if _docs else None,
              redoc_url=None)


@app.exception_handler(DataError)
async def value_does_not_fit(_: Request, e: DataError) -> JSONResponse:
    """PostgreSQL refuses what SQLite stores: a text longer than its column, a number beyond its type."""
    log.warning("value refused by the database: %s", e.orig)
    return JSONResponse({"detail": tx("Girilen değer çok uzun veya çok büyük")}, status_code=400)


@app.exception_handler(IntegrityError)
async def record_in_conflict(_: Request, e: IntegrityError) -> JSONResponse:
    log.warning("integrity error: %s", e.orig)
    return JSONResponse({"detail": tx("Bu kayıt zaten var veya başka kayıtlarla bağlantılı")}, status_code=409)

# The SPA: own scripts only (pdf.js needs wasm), inline styles (charts), blob: for previews and the
# pdf.js worker; connect-src adds only the configured update feed. API responses (JSON and stored files)
# never need to run anything, so they get a sandboxed, empty policy: an uploaded HTML or SVG file opened
# directly cannot run script on the app origin.
_feed = urlsplit(get_settings().update_feed_url)
_FEED_ORIGIN = f" {_feed.scheme}://{_feed.netloc}" if _feed.scheme in ("http", "https") and _feed.netloc else ""
SPA_CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
           f"img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'{_FEED_ORIGIN}; "
           "worker-src 'self' blob:; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; "
           "form-action 'self'; frame-ancestors 'none'")
API_CSP = "default-src 'none'; img-src 'self'; sandbox; frame-ancestors 'none'"
_DOCS_PATHS = ("/api/docs", "/api/openapi.json")


# Added first, so it sits inside the two below: their task groups would turn its refusal into a plain 400
app.add_middleware(BodyLimit)


@app.middleware("http")
async def restore_gate(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in ("/api/health", "/api/version"):
        return await call_next(request)
    if not maintenance.enter():
        return JSONResponse({"detail": tx("Sistem yedekten geri yükleniyor, biraz sonra tekrar deneyin")}, 503,
                            headers={"Retry-After": "30"})
    try:
        return await call_next(request)
    finally:
        maintenance.leave()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("X-Frame-Options", "DENY")
    path = request.url.path
    if path.startswith("/api/") and path not in _DOCS_PATHS:
        h.setdefault("Content-Security-Policy", API_CSP)
    elif not path.startswith("/api/"):
        h.setdefault("Content-Security-Policy", SPA_CSP)
    return response


@app.middleware("http")
async def live_sync(request: Request, call_next):
    response = await call_next(request)
    if sync.counts(request.method, request.url.path, response.status_code):
        await run_in_threadpool(sync.bump, engine)
    return response


@app.middleware("http")
async def request_language(request: Request, call_next):
    """Added last, so it runs first: every message below it uses the caller's language."""
    set_lang(request.headers.get("x-lang") or request.cookies.get("erp_lang"))
    return await call_next(request)


@app.get("/api/sync", tags=["system"])
def sync_rev() -> dict:
    """Write counter for live refresh on other computers (no login needed: it is just a number)."""
    return {"rev": sync.current(engine)}


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/tls/cert", tags=["system"])
def tls_cert() -> Response:
    """The server's own certificate, for adding it to a browser or phone. Public by nature."""
    cert = tls.files()[0]
    if not cert.is_file():
        raise HTTPException(404, tx("HTTPS açık değil"))
    return Response(cert.read_bytes(), media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="lab-erp.crt"'})


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
            raise HTTPException(404, tx("Not Found"))
        f = (_spa_root / path).resolve()
        if path and f.is_file() and _spa_root in f.parents:
            return FileResponse(f)
        return FileResponse(_spa_root / "index.html", headers={"Cache-Control": "no-cache"})
