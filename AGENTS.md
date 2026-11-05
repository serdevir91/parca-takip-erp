# LAB ERP: agent notes

Offline LAN part-tracking ERP for a machine-building workshop. Product name **LAB ERP** since 1.4.1 (was "Parça Takip ERP"; repo, package ids, `ParcaTakipApp` bridge, UDP magic, `%APPDATA%\ParcaTakipERP` on old PCs and the Docker-free script paths keep the old name). Logo: `desktop/make_logo.py` writes `icon.ico`, `favicon.svg`, `logo-192.png` and the Android foreground; `components/BrandMark.tsx` and both `setup.html` files inline the same flask path. It tracks SolidWorks BOM versions, part status, fasteners, drawings and the T-35 control list. The full spec is `docs/SPEC.md` (Turkish), and the sample inputs are in `docs/reference/`.

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
  - Product tree (`bomtree`): validates a nested tree and writes it as the SolidWorks CSV, so `bomimport.upload_bom` handles it like any upload. No separate row model.
- `app/services/` holds the DB-backed logic:
  - `bomimport`: upload, approve and undo. These functions do not commit; the API layer commits.
  - `state.ProjectView`: the read model every screen uses.
  - `Tracking.hidden` and `FastenerSetting.hidden` only dim rows (Parça listesi, Bağlantı elemanları, İhtiyaç). They never change quantities, status or requirements.
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
  planning, purchasing, workorders, stock, hr, contacts, sales, finance, chat and admin. Role defaults plus per-user
  overrides in `users.permissions` (JSON); admin always has full access. Guard endpoints with
  `Depends(require("<module>", "edit"))`; `/api/admin/permissions` serves the catalog to the UI.
  Since 1.5.0 defaults follow the job: hr and finance are admin-only; designer/viewer have no contacts or sales.
  Changing `ROLE_DEFAULTS` changes existing users at once (only overrides are stored).
- `app/services/sync.py` + the `live_sync` middleware in `main.py`: every successful write bumps `sync_state.rev`
  (login, password, test and `*/preview` paths are skipped). `GET /api/sync` (no auth) returns the rev; clients poll it.
- `app/services/commerce.py`: sales orders (`SS-YYYY-####`), invoices (`FT-YYYY-####` for sales, the supplier's
  number for purchases), payments and firm balances/ledger. Total = sum(qty*price) - discount + KDV. Balance > 0
  means the firm owes us: + issued sales invoice, + payment out; - issued purchase invoice, - payment in.
  Routers: `api/sales.py`, `api/finance.py`, `api/hr.py` (employees, time entries; labour cost flows into
  `erp.project_costs` as source "İşçilik", one anonymous line without hr rights) and `api/overview.py` (home page
  KPIs, filtered by permission). `Employee.user_id` links a card to a login; `GET /hr/me` (any user, fallback
  match by e-mail) is the employee's own card, shown in `pages/MyCard.tsx` ("Personel kartım", nav item only
  for users without hr).
- Photos and chat:
  - `api/photos.py`: several photos per part number (entity "part", key = part_no, global like drawings) or stock
    item (entity "stock", key = item id). Permission follows the parts/stock module. Files go to `photo_dir`.
  - `api/chat.py` (prefix `/chat`): direct rooms (`dm_key` "low:high") and groups with admins, messages with one
    optional attachment each (`chat_dir/<room>`), read markers (`ChatMember.last_read_id`), soft delete.
    Module `chat` (every role defaults to edit). Chat writes are in `sync.SKIP_PATHS`; clients poll
    `GET /chat/state` instead, whose `key` changes on new messages, room edits/deletions and read markers.
  - `services/uploads.py`: `store()` (uuid name, size limit), `safe_name`, `is_image` (extension only, no SVG),
    `media_for(name)` -> (media type, inline ok). Only images and PDF are served inline; anything else is an attachment.
  - The server has no image library: the browser sends a JPEG `thumb` with each image upload
    (`src/api/images.ts` `makeThumb`); thumb endpoints fall back to the original. File endpoints take the Bearer header only (no `?access_token`).
- Security (v1.3.0):
  - `auth.py`: tokens carry `tv` = `User.token_version`; a password change, admin reset or deactivation bumps it and
    revokes every session. `POST /auth/password` returns a fresh `access_token`. `PUT /auth/me` edits own `full_name`.
    No forced password change. `MIN_PASSWORD` = 8 (`api/auth.check_password_rules`).
  - `services/loginguard.py`: in-memory login throttle (5 per user, 30 per IP, 15 min window; 429 + Retry-After).
  - `config.ensure_jwt_secret`: a weak or default `ERP_JWT_SECRET` is replaced by `data_dir/.jwt_secret`.
  - `main.py` `security_headers` middleware: nosniff, no-referrer, `X-Frame-Options: DENY`, sandbox CSP on `/api/*`,
    SPA CSP elsewhere (nginx mirrors it in `frontend/security_headers.conf`). `/api/docs` only with `ERP_API_DOCS`.
  - `services/xlsafe.neutralize(wb)` before every workbook save (formula injection); `core/xlsxguard.check_xlsx`
    and the `drawings.iter_zip` limits stop zip bombs.
- Sign-up and mail (v1.4.0):
  - `POST /auth/register` creates a viewer with `active=False, pending=True` (setting `signup.enabled`, 5 per IP/hour).
    Login with the right password on a pending/inactive user returns 403 with a Turkish reason; wrong password stays 401.
    Admin: `GET /admin/signups/count`, `POST /admin/users/{id}/approve` (role + permissions), `DELETE /admin/users/{id}/signup`.
  - `User.email` (migration 0006). `services/mailer.py`: SMTP settings key `smtp` (password never returned),
    `send()` raises `RuntimeError` with Turkish text. `api/mail.py`: `/mail/status`, `/mail/recipients`,
    `/mail/send` (multipart, 20 recipients, 20 MB, 60/hour/user, Reply-To = sender), admin `/mail/settings` + `/mail/test`.
- Temin types (v1.5.7): setting `temin_types`, a list of `{name, kind, drawing, order}`; defaults in
  `core/status.py`. Rows keep the type's name in `procurement`; status logic goes through `state.base_kind` and
  `needs_drawing`, never a comparison with a literal name. `FIXED_TEMINS` cannot be removed.
- Numbers (v1.5.10): `core/numbers.py` and `frontend/src/api/num.ts` are the one rounding rule (money and hours 2, quantity 3, percent 1, half up on the decimal value); `tests/test_numbers.py` pins both. `num.ceil_units` for whole units, `num.text` for numbers inside messages (never `:g`, it prints 1.23457e+06).
- Sessions (v1.5.10): httpOnly cookies `erp_session` (HTTP) and `erp_session_s` (Secure), path `/api`, SameSite strict. Native shells cannot reach the cookie for file work, so they ask `POST /auth/file-ticket` for a short ticket.
- Edit forms (v1.5.10): `services/conflict.py`, columns `edit_rev`, `edit_by` (migration 0011). A form sends `rev`; a stale one gets 409 and `api/conflict.tsx` asks. No `rev` means overwrite on purpose (bulk edits). Not covered: fastener settings and rules, T35 config, users, system settings, self-service time, chat, photos; employee and firm active toggles send no `rev`.
- Holidays (v1.5.10): `services/holidays.py`, `api/holidays.py`, `pages/admin/Holidays.tsx`. Fixed national days are one click; religious holidays move each year, so the admin enters them. Weekly overtime is unchanged.
- Sales credits (v1.5.10): `Invoice.kind` is String(16) because `sales_credit` does not fit 10 (SQLite never complained, PostgreSQL did). A credit note is checked against its source invoice (`_check_credit_room`), not the order billing cap. `invoice_status` locks the order first, or two concurrent issues both pass.
- Balance basis (v1.5.10): `commerce.balance_basis` "today" or document date, per request `?basis=`; the difference is shown as Kur farkı.
- Transport (v1.5.10): cleartext stays permitted in `network_security_config.xml` because a LAN address is only known at run time; `MainActivity.downgrade` refuses http to a server pinned on https. The desktop pin is `guard_certificates` (WebView2 certificate event); a certificate signed by a public authority raises no event, so the pin cannot stop that case.
- Print CSS sets `color-scheme: light`: a dark scheme paints the page margins black in the PDF even with a white body.
- Workspace features (v1.5.9): `api/notifications.py` computes each user's list from permissions and stores only dismissals; keys carry state (`low:{id}:{qty}`), so a changed fact comes back. `api/prefs.py` + `frontend/src/api/prefs.ts` mirror `dg.*`, `parts.*`, `erp_theme` to the server; the server wins on load, so a key written straight to localStorage without `savePref` is removed. `api/templates.py` makes projects from templates.
- Edit conflicts (v1.5.9): `/parts` returns `rev` (max AuditLog.id, read before the rows); PATCH and `/parts/cells` take it, `tracking.recent_edits` + `conflict_of` report other users' changes; PATCH answers 409, cells saves the rest and returns `conflicts`. UI: `components/EditConflicts.tsx`. Bulk edit overwrites on purpose. Only the parts grid is covered.
- Money totals (v1.5.9): `fx.Book(db)` converts with stored rates; `po_out`, `so_out` give `base_total` (None without a rate), `commerce.balances` gives `base_*`. Never add document currencies 1:1. `commerce.SO_SHIPPING` is confirmed + partial.
- Stock returns: one kind, `issue_return`, in `ISSUE_KINDS`; `project_costs` nets it off.
- Attendance (v1.5.8): table `attendance` (migration 0009), `core/attendance.py` (arithmetic), `api/attendance.py`. `/attendance/me`, `clock-in`, `clock-out` are any_user on the card linked to the login; the list and edits need module `attendance`. Datetimes are naive server wall clock; `work_date` is the day the shift began; overtime is weekly over `production.week_hours`.
- Part names (v1.5.7): global `part_names` table (migration 0008), row field `part_name`, `tracking.set_names`.
  `POST /projects/{id}/parts/cells` saves many cells at once and reports bad ones per cell; `/parts/names` takes a
  pasted list. `POST /export/grid` writes the visible rows to `data_dir/exports`, the GET by id downloads it, because
  the desktop and mobile shells save only from a GET.
- System settings (v1.5.5): `services/system.py`, setting key `system`, stored as differences from defaults only
  (`clean`). `apply_runtime(db)` copies session, upload, backup, password, login and module values onto `get_settings()`
  on every authenticated request, so code without a DB session and several workers stay in step. `for_user`/`for_login`
  go to the UI (`src/api/system.ts`, `sys`, `curSign`, `useBrand`). `permissions.effective` masks `disabled_modules` for
  everyone, admin included; `admin` cannot be turned off. `next_no(db, model)` takes document prefixes from settings.
- The `t35` code names (`t35_note`, `/t35`, setting key `t35`) stay for compatibility; the UI calls them "Durum listesi".
  `DEFAULT_MANUFACTURERS` is empty, and `excel_import` still accepts the old "T-35 Notu" header.
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
  - `DataGrid`: virtualized, with Excel-like column filters, inline edit and selection. Split into `dgTypes.ts`
    (`GridColumn`, `GridProps`), `dgFilter.tsx` (column filter with `conds`, `AdvancedFilter`, `ADV` hidden column)
    and `dgSheet.tsx` (`TableView`: range selection, clipboard, fill, undo, find, context menu). `onEditMany` takes
    multi-cell writes in one call, `selectionActions` fills the selection bar, `stateKey` names the saved
    `dg.layout.<key>` and `dg.views.<key>` entries. `openOnClick` keeps single-click open in table mode; otherwise a
    click selects the cell and a double click on a read-only cell calls `onRowClick`.
    The clipboard uses DOM copy/cut/paste events because `navigator.clipboard` does not exist on plain http.
  - `Layout`: `Page`, `useProject`.
  - `Toast`, `PdfViewer`, the import modals and `UpdateCheck`.
  - `viewer/`: `Viewer` (gallery of `ViewItem`s, picks `PdfViewer` or `ImageLightbox`, thumbnail strip, ← →),
    `ImageLightbox` (transform-based wheel/pinch zoom, pan, rotate), `gestures.ts` (`useGestures`) and `Thumb`
    (cached, lazy object-URL thumbnails of protected API files; `forgetThumb` after delete).
  - `Photos`: photo grid + multi upload for one part number or stock item.
- `DataGrid` has two views (`useGridView`, localStorage `dg.view`, default "cards"): `CardView` (virtualized cards,
  columns mapped by `GridColumn.card` = title/sub/badge/field/actions/hide, `cardLead`, `cardColor`) and `TableView`.
  The bar has search, Filtre sheet, sort, "Paylaş ▾" (CSV with `;` + BOM, or e-mail via `MailDialog`; `exportName`,
  `false` hides it). `components/MailDialog.tsx`: `MailFile` (`path` from the API or `blob`), `shareFiles()` uses the
  Android `share`/`shareData` bridge or Web Share.
- `__APP_VERSION__` (vite.config.ts) is read from `backend/app/config.py`, so the update banner compares one source.
- `Layout` also has the grouped, collapsible sidebar, `PageHeader` and `useLiveSync()` (polls `/api/sync` every
  4 s and invalidates all queries when the rev changes).
- Routes: `/` is `Home` (dashboard), `/projects` the project list, `/p/:pid/*` the project screens, then
  `/purchasing`, `/work-orders`, `/stock`, `/hr`, `/contacts`, `/sales`, `/finance`, `/chat` (`?r=<room>`) and `/admin`.
- `Layout` also runs `useChatPoll` (`/chat/state` every 4 s): unread badge, "(n)" tab title, new-message toast,
  and it invalidates `["chat", …]` queries when the key changes.
- `src/pages/`: one file per spec §8 screen. The ERP screens are `Planning`, `Purchasing`, `WorkOrders` and `Stock`;
  their shared types, formatters and pickers are in `pages/erp/common.tsx`. The commerce screens `Sales`, `Finance`,
  `Hr` and `Contacts` share types and widgets (`LinesEditor`, `LedgerModal`, `Stat`) in `pages/erp/commerce.tsx`.
- `src/api/mobile.ts`: `mobileApp()` returns the Android bridge (`window.ParcaTakipApp`) or null; `onBack(handler)`
  registers back-button handlers (`window.__erpBack`, open dialogs get Escape). `download()` goes through the bridge
  inside the app. `components/Profile.tsx`: own name + password ("Profilim", opened from the user chip).
- Mobile UI: `styles.css` `/* === Mobil (telefon) === */` block. At <=800px the sidebar is an off-canvas drawer
  (`.nav-open`), modals are bottom sheets, tables scroll; `.mobile-only` / `.desk-only` helpers.
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
Windows desktop app: `desktop/parca_takip_desktop.py` (pywebview window; server mode runs the backend in-process on SQLite, client mode opens a LAN server, UDP discovery), `setup.html` first-run screen, PyInstaller `parca_takip.spec`, Inno `installer.iss` (exe `LabERP.exe`, assets `LabERP-Setup-<v>.exe`; it deletes the old `ParcaTakipERP.exe` and shortcuts). Use `_show_html()`, never `window.load_html` directly: before WebView2 is ready pywebview drops `load_html` and shows `window.html` (the 1.4.0 stuck "açılıyor" bug). CI runs `LabERP.exe --ui-test <json>` on a fresh profile (`ERP_DESKTOP_CONFIG_DIR`). No native menu since 1.5.0: `components/DesktopMenu.tsx` ("Uygulama", also on the login page) calls the js_api `app_info`/`app_action`/`set_theme`; `set_theme` paints the Windows title bar with DWM attributes 20/19/34/35/36 and is remembered in the config. "Sunucuma kur" (`remote_install.py` + `server_install.sh`, paramiko): packs `server_src` (backend source, bundled by the spec) + `frontend_dist`, uploads over SFTP, runs the script as root (sudo -S via stdin), which sets up `/opt/laberp` venv, `/var/lib/laberp`, `/etc/laberp.env` and systemd `laberp`; host keys TOFU in `config_dir()/known_hosts`. Test it against a systemd Ubuntu container with sshd (colima; arm64 needs a self-built image). CI (`.github/workflows`) builds it on windows-latest; pushing tag `vX.Y.Z` (must equal `app_version` in `backend/app/config.py`) publishes the installer to GitHub Releases with `desktop/RELEASE_NOTES.md`.
Server mode closes to the tray (`pystray`, since 1.5.5): `_on_form_closing` cancels `UserClosing` and hides the window, `_tray_quit` is the only real exit, and a second launch wakes the first through `INSTANCE_PORT` 47812. CI checks it with `LabERP.exe --tray-test`. `remote_install.check()` is the "Bağlantıyı dene" probe.
Store page: `README.md` head uses `docs/screenshots/*.png`, captured from a seeded demo at 1440x900 (phones 390x844).
Android app: `mobile/android` (plain Java, no AndroidX UI, Gradle 9.1 + AGP). `MainActivity` is a WebView over the
saved server with the `ParcaTakipApp` JS bridge (gated to `setup.html` and the saved server origin), file chooser +
camera via FileProvider, downloads to `Downloads/LAB ERP`, back key -> `__erpBack`, GitHub releases update check.
`Discovery` finds servers (UDP 47811, then a /24 probe on 8000/80/8080). `assets/setup.html` is the first-run screen.
Version comes from `config.py`. Release signing: gitignored `keystore.properties` + `release.jks`, or `ERP_KEYSTORE_*`
env (CI secrets; the job skips the APK when they are missing). `splits.abi` builds arm64-v8a, armeabi-v7a, x86_64, x86 and
universal; release assets are `LabERP-<v>-<abi>.apk` + `LabERP-<v>.apk` (upload the universal one last:
1.3.0 clients take the last `.apk` asset). `MainActivity.pickApk` picks the split for `Build.SUPPORTED_ABIS`. Build: `JAVA_HOME=<jdk17> ./gradlew assembleRelease`.
Desktop updates are signed: the shell refuses a download without a valid `<exe>.sig`. After CI publishes a release, download the exe, run `backend/.venv/bin/python desktop/sign_update.py <exe>` and `gh release upload v<x> <exe>.sig --clobber`. The Ed25519 private key is `~/.config/lab-erp/update_signing_ed25519.pem`, on the Mac mini only; losing it means shipping a new public key by hand to every desktop install.
HTTPS pinning: Android `Pin.java` keeps the first certificate per server (TOFU), `onReceivedSslError` and `saveFile`/`shareFile` check it, forgetting the server clears it. The desktop shell checks its pin when it connects, not on each request.
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
