# Parça Takip ERP: agent notes

Offline LAN part-tracking ERP for a machine-building workshop. It tracks SolidWorks BOM versions, part status, fasteners, drawings and the T-35 control list. The full spec is `docs/SPEC.md` (Turkish), and the sample inputs are in `docs/reference/`.

Read this file first. Do not re-scan the whole project.

## Stack
- **Backend** (`backend/`): FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 in production and SQLite in tests, and openpyxl.
- **Frontend** (`frontend/`): React 18, TypeScript and Vite, with:
  - TanStack Query, Table and Virtual.
  - Recharts.
  - pdfjs-dist, bundled locally.
- **Serving**: nginx in the frontend image serves the SPA and proxies `/api`. Uploads are limited to 2 GB.
- **Runtime**: `docker-compose.yml` runs `db`, `backend`, `backup` and `frontend`. Nothing is loaded from a CDN at runtime.

## Backend layout
- `app/main.py` includes every router in `app/api/*.py` under `/api`, so a new file there is picked up automatically.
- `app/api/deps.py` has the guards:
  - Role guards: `any_user`, `editor` (admin, designer or planner), `designer` and `admin`.
  - `project_or_404`.
- Roles are `admin`, `designer`, `planner` and `viewer`. In the UI they appear as Admin, Tasarımcı, Planlama/Satın alma and İzleyici.
- `app/core/` holds pure logic with no DB access:
  - BOM parse (`bomparse`), compare (`compare`) and status rules (`status`, spec §5).
  - Fastener matcher (`fastener`), T-35 import (`t35`), drawing match (`drawmatch`) and control list (`control`).
- `app/services/` holds the DB-backed logic:
  - `bomimport`: upload, approve and undo. These functions do not commit; the API layer commits.
  - `state.ProjectView`: the read model every screen uses.
  - `settings`: admin-editable JSON settings.
  - `excel_export` / `excel_import`, `drawings` / `thumbs`, `backup` and `audit`.
  - `erp`: purchasing, stock, work orders, requirements (MRP) and project costs. Its API routers are
    `api/purchasing.py`, `api/stock.py` and `api/workorders.py`.
    - Stock is one global pool. Goods bought or made for a project get a receipt or production move plus an
      issue move to that project, so free stock nets to 0. Stock-to-project issues use `ref="STOK"`.
    - Shortage = required - issued - on order (open PO lines) - in production (open WOs) - free stock.
    - Hooks: a sent PO or started WO sets tracking to "Devam ediyor" and fasteners to "Sipariş Verildi";
      when issued >= required, parts become "Tamamlandı" and fasteners "Teslim Edildi".
- `app/permissions.py`: per-module levels `none`/`view`/`edit` for projects, parts, fasteners, drawings, control,
  planning, purchasing, workorders, stock, hr, contacts, sales, finance and admin. Role defaults plus per-user
  overrides in `users.permissions` (JSON); admin always has full access. Guard endpoints with
  `Depends(require("<module>", "edit"))`; `/api/admin/permissions` serves the catalog to the UI.
- `app/services/sync.py` + the `live_sync` middleware in `main.py`: every successful write bumps `sync_state.rev`
  (login, password, test and `*/preview` paths are skipped). `GET /api/sync` (no auth) returns the rev; clients poll it.
- `app/services/commerce.py`: sales orders (`SS-YYYY-####`), invoices (`FT-YYYY-####` for sales, the supplier's
  number for purchases), payments and firm balances/ledger. Total = sum(qty*price) - discount + KDV. Balance > 0
  means the firm owes us: + issued sales invoice, + payment out; - issued purchase invoice, - payment in.
  Routers: `api/sales.py`, `api/finance.py`, `api/hr.py` (employees, time entries; labour cost flows into
  `erp.project_costs` as source "İşçilik") and `api/overview.py` (home page KPIs, filtered by permission).
- `app/cli.py` provides:
  - `seed`: demo data.
  - `backup`: one run, or `--daemon` for the daily run with retention of `ERP_BACKUP_KEEP_DAYS`.
  - `restore`.
  - `migrate` (alembic upgrade head from any cwd; stamps old create_all SQLite DBs) and `serve` (Docker-free: migrate + uvicorn + backup thread).
- Migrations live in `alembic/`. The backend runs `alembic upgrade head` on startup. Migration 0001 runs `create_all` from the
  current models, so later migrations must be idempotent: check the inspector before adding a column or table
  (see `0002_erp_modules.py`).

## Frontend layout
- `src/api/`:
  - The client: `api.get/post/put/patch/del`, `upload`, `download` and `blobUrl`.
  - The auth hook `useAuth`, which gives `can(module, level = "view")`, `isAdmin` and `reloadUser()`.
    Pages gate edit buttons with `useAuth().can("<module>", "edit")`; `App.tsx` wraps routes in `RequireAuth({module})`.
- `src/components/`:
  - `DataGrid`: virtualized, with Excel-like column filters, inline edit and selection.
  - `Layout`: `Page`, `useProject`.
  - `Toast`, `PdfViewer`, the import modals and `UpdateCheck`.
- `Layout` also has the grouped, collapsible sidebar, `PageHeader` and `useLiveSync()` (polls `/api/sync` every
  4 s and invalidates all queries when the rev changes).
- Routes: `/` is `Home` (dashboard), `/projects` the project list, `/p/:pid/*` the project screens, then
  `/purchasing`, `/work-orders`, `/stock`, `/hr`, `/contacts`, `/sales`, `/finance` and `/admin`.
- `src/pages/`: one file per spec §8 screen. The ERP screens are `Planning`, `Purchasing`, `WorkOrders` and `Stock`;
  their shared types, formatters and pickers are in `pages/erp/common.tsx`. The commerce screens `Sales`, `Finance`,
  `Hr` and `Contacts` share types and widgets (`LinesEditor`, `LedgerModal`, `Stat`) in `pages/erp/commerce.tsx`.
- `src/theme/`: light, dark and AMOLED themes. The theme is set with the `data-theme` attribute and saved in localStorage under `erp_theme`.
- `src/styles.css`: one block per screen, marked with `/* === Screen === */` comments.

## Commands
```bash
# backend tests (SQLite)
cd backend && .venv/bin/python -m pytest -q 2>&1 | grep -iE "error|fail|passed"
# frontend type check + build
cd frontend && npx tsc -b && npm run build
# full stack
docker compose up -d --build
```
Windows install/update: `KURULUM.bat` runs `deploy/windows_install.ps1` (Docker check, random `.env` secrets, free-port pick, firewall rule). `.gitattributes` keeps LF everywhere except `*.ps1`/`*.bat`; `.ps1` files need a UTF-8 BOM for Windows PowerShell 5.1.
Windows desktop app: `desktop/parca_takip_desktop.py` (pywebview window; server mode runs the backend in-process on SQLite, client mode opens a LAN server, UDP discovery), `setup.html` first-run screen, PyInstaller `parca_takip.spec`, Inno `installer.iss`. CI (`.github/workflows`) builds it on windows-latest; pushing tag `vX.Y.Z` (must equal `app_version` in `backend/app/config.py`) publishes the installer to GitHub Releases with `desktop/RELEASE_NOTES.md`.
Docker-free mode: `python -m app.cli serve` on SQLite (WAL); the backend serves `frontend/dist` itself when `ERP_STATIC_DIR` is unset and `../frontend/dist` exists (never inside the image). Windows: `KURULUM_DOCKERSIZ.bat` -> `deploy/windows_native_install.ps1` (winget Python 3.12 + Node, data in `C:\ParcaTakipVeri`, Task Scheduler task `ParcaTakipERP` as SYSTEM). Codespaces demo: `.devcontainer/` (setup.sh builds + seeds, start.sh serves port 8000, admin/admin).

## Rules
- The UI text is Turkish, with correct characters (ç, ğ, ı, İ, ö, ş, ü). This app is an explicit exception to the workspace's English-default rule.
- Store status colors as hex without `#`. `statusStyle(hex)` in the frontend renders them.
- Acceptance numbers for spec §10 are covered by `tests/test_bomimport.py`. For the 11-02 BOM they are:
  - 450 rows and 62 fastener rows.
  - 43 unique fasteners, total 1006.
  - 60 rows inside purchased assemblies.
- Workspace baseline:
  - Themes are implemented.
  - The update check runs silently at startup and from the menu, using `ERP_UPDATE_FEED_URL`.
  - In-app purchase and in-app review do **not apply**: this is an internal LAN tool, not a store app.
