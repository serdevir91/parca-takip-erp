"""LAB ERP desktop app (formerly Parça Takip ERP): the web UI in a native window (pywebview; Edge WebView2 on Windows).

Two modes, chosen on the first start and changeable from the "Uygulama" menu:
- server ("Bu bilgisayar sunucu"): SQLite database on this PC; the API and the UI run inside this
  process on 0.0.0.0:<port>, so other PCs can connect with a browser or with this app in client mode.
- client ("Ağdaki sunucuya bağlan"): connects to a running server (Docker, Docker-free or another
  desktop app in server mode).

In server mode on Windows the close button only hides the window: the server keeps running and a tray icon
(hidden icons, next to the clock) reopens the window or really quits. A second start shows the running window.

Settings live in desktop.json under %APPDATA%\\LabERP (%APPDATA%\\ParcaTakipERP on PCs set up before 1.4.1). Updates come from the GitHub releases of
the project (silent check at startup and "Güncellemeleri denetle" in the menu).

Dev run on macOS/Linux/Windows:  python desktop/parca_takip_desktop.py   (needs frontend/dist)
Bundle smoke test (CI):           LabERP.exe --smoke <empty folder>
Window self-test (CI):            LabERP.exe --ui-test <result.json>   (fresh profile: setup page + JS bridge)
Background self-test (CI):        LabERP.exe --tray-test <result.json>  (server profile: close hides, reopen, quit)
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if FROZEN:
    BACKEND_DIR = BUNDLE                      # app package in the archive, alembic.ini + migrations/ next to it
    MIGRATIONS = BUNDLE / "migrations"
    SPA_DIR = BUNDLE / "frontend_dist"
    SERVER_SRC = BUNDLE / "server_src"       # backend source for "Sunucuma kur"
    ASSETS = BUNDLE
else:
    BACKEND_DIR = BUNDLE.parent / "backend"
    MIGRATIONS = BACKEND_DIR / "alembic"
    SPA_DIR = BUNDLE.parent / "frontend" / "dist"
    SERVER_SRC = BACKEND_DIR
    ASSETS = BUNDLE
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402  (no settings are read at import time)

APP_NAME = "LAB ERP"
VERSION = Settings.model_fields["app_version"].default
REPO = "serdevir91/parca-takip-erp"
DEFAULT_PORT = 8000
IS_WIN = sys.platform == "win32"
INSTANCE_PORT = 47812         # loopback only: a second start asks the running app to show its window
INSTANCE_HELLO = b"LABERP-SHOW\n"
UI_TEST: Path | None = None   # --ui-test <result.json>: exit once the setup page talks to Python
TRAY_TEST: Path | None = None  # --tray-test <result.json>: exercise the background mode, then quit


def config_dir() -> Path:
    if IS_WIN:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    # Before 1.4.1 the app was "Parça Takip ERP"; keep using its folder where it exists
    d = base / "ParcaTakipERP"
    if os.environ.get("ERP_DESKTOP_CONFIG_DIR"):
        d = Path(os.environ["ERP_DESKTOP_CONFIG_DIR"])
    elif not d.is_dir():
        d = base / "LabERP"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_FILE = config_dir() / "desktop.json"
LOG_FILE = config_dir() / "desktop.log"
log = logging.getLogger("desktop")


def setup_logging() -> None:
    # A windowed exe has no console: sys.stdout/stderr are None, and uvicorn/alembic write to them
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5_000_000:
        LOG_FILE.replace(LOG_FILE.with_suffix(".log.1"))
    f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(f)])


# ---------- settings ----------
def default_data_dir() -> str:
    old = Path.home() / "Documents" / "ParcaTakipERP"
    return str(old if (old / "erp.db").is_file() else Path.home() / "Documents" / "LabERP")


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def normalize_url(u: str) -> str:
    u = u.strip().rstrip("/")
    if u and not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    return u


def http_json(url: str, timeout: float = 5, **kw) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": f"ParcaTakipERP/{VERSION}",
                                               **kw.pop("headers", {})}, **kw)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def is_erp(base: str, timeout: float = 3) -> bool:
    try:
        return http_json(f"{base}/api/health", timeout).get("status") == "ok"
    except (OSError, ValueError):
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def lan_addresses() -> list[str]:
    from app.services.discovery import _local_ipv4

    return _local_ipv4()


# ---------- embedded server ----------
def wake_running_app() -> bool:
    """True when an app is already running here; it brings its window to the front."""
    if IS_WIN:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_ulong(0xFFFFFFFF))  # ASFW_ANY
    try:
        with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=1) as s:
            s.settimeout(3)
            s.sendall(INSTANCE_HELLO)
            return s.recv(2) == b"OK"
    except OSError:
        return False


class EmbeddedServer:
    """Runs migrate + uvicorn + the daily backup thread in this process (like `app.cli serve`)."""

    def __init__(self, data_dir: Path, port: int, jwt_secret: str, admin_password: str | None):
        self.data_dir, self.port = data_dir, port
        self.server = None
        self.error: str | None = None
        d = data_dir.as_posix()
        os.environ.update({
            "ERP_DATABASE_URL": f"sqlite:///{d}/erp.db",
            "ERP_DATA_DIR": f"{d}/data",
            "ERP_BACKUP_DIR": f"{d}/yedek",
            "ERP_JWT_SECRET": jwt_secret,
            # Only used when the database has no users yet (first start)
            "ERP_ADMIN_PASSWORD": admin_password or secrets.token_urlsafe(16),
            "ERP_STATIC_DIR": str(SPA_DIR),
            "ERP_MIGRATIONS_DIR": str(MIGRATIONS),
        })

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout: float = 90) -> None:
        for sub in ("data", "yedek"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        import uvicorn

        from app import cli
        from app.config import get_settings

        from app.services import discovery

        cli.migrate()
        threading.Thread(target=cli.backup_daemon, args=(get_settings().backup_time,), name="backup",
                         daemon=True).start()
        discovery.start_responder(self.port, VERSION)
        from app.main import app  # imported here (not by name) so the bundler sees it

        config = uvicorn.Config(app, host="0.0.0.0", port=self.port, workers=1, log_config=None,
                                timeout_keep_alive=75, proxy_headers=True, forwarded_allow_ips="*")
        self.server = uvicorn.Server(config)
        t = threading.Thread(target=self._run, name="uvicorn", daemon=True)
        t.start()
        end = time.monotonic() + timeout
        while not self.server.started:
            if not t.is_alive() or time.monotonic() > end:
                raise RuntimeError(self.error or f"Sunucu {self.port} portunda başlatılamadı")
            time.sleep(0.1)

    def _run(self) -> None:
        try:
            self.server.run()
        except BaseException as e:  # noqa: BLE001 - reported to the UI
            log.exception("uvicorn stopped")
            self.error = str(e)

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True


# ---------- updates (GitHub releases) ----------
def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def latest_release() -> dict | None:
    """{"version", "url" (release page), "asset" (installer URL or None), "notes"} or None if not newer."""
    data = http_json(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=8,
                     headers={"Accept": "application/vnd.github+json"})
    ver = str(data.get("tag_name", "")).lstrip("vV")
    if not ver or version_tuple(ver) <= version_tuple(VERSION):
        return None
    asset = next((a["browser_download_url"] for a in data.get("assets", [])
                  if a.get("name", "").lower().endswith(".exe")), None)
    return {"version": ver, "url": data.get("html_url"), "asset": asset, "notes": data.get("body") or ""}


# ---------- files from the API (downloads, opening drawings) ----------
# Extensions opened with the default program; anything else is offered as "save" instead
OPEN_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg", ".dxf", ".dwg",
             ".step", ".stp", ".igs", ".iges", ".sldprt", ".sldasm", ".slddrw", ".edrw", ".eprt", ".easm",
             ".xlsx", ".xls", ".csv", ".txt"}


def safe_name(name: str, fallback: str = "dosya") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(name.replace("\\", "/")).name).strip(" .")
    return name or fallback


def disposition_name(cd: str) -> str | None:
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    return urllib.parse.unquote(m.group(1)) if m else None


def open_with_default(path: Path) -> None:
    if IS_WIN:
        os.startfile(str(path))  # noqa: S606 - file type checked against OPEN_EXTS
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ---------- the app ----------
class DesktopApp:
    """Owns the window and the mode. Public methods are the JavaScript API (window.pywebview.api)."""

    def __init__(self) -> None:
        self._cfg = load_config()
        self._window = None
        self._server: EmbeddedServer | None = None
        self._remote = None      # RemoteInstall of "Sunucuma kur"
        self._base = ""          # URL the window shows: the server root
        self._tray = None        # pystray icon: set while the server runs in the background (Windows)
        self._listener: socket.socket | None = None   # wake_running_app() connects here
        self._quitting = False   # False: the close button only hides the window while the tray is up
        self._hint_shown = False
        self._setup_html = (ASSETS / "setup.html").read_text(encoding="utf-8")

    # --- state for setup.html ---
    def get_state(self) -> dict:
        c = self._cfg
        if UI_TEST is not None:
            title_bar = self._paint_title_bar({"dark": True, "caption": "#0f172a", "text": "#e6e9ee"})
            UI_TEST.write_text(json.dumps({"ok": True, "version": VERSION, "mode": c.get("mode"),
                                           "title_bar": title_bar}), encoding="utf-8")
            threading.Timer(1.0, self._window.destroy).start()
        data_dir = c.get("data_dir") or default_data_dir()
        return {
            "version": VERSION, "mode": c.get("mode", "server"), "data_dir": data_dir,
            "port": c.get("port", DEFAULT_PORT), "server_url": c.get("server_url", ""),
            "running": self._server is not None, "has_db": (Path(data_dir) / "erp.db").is_file(),
            "error": c.get("_error", ""),
        }

    def pick_folder(self, current: str = "") -> str | None:
        import webview

        r = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=current or str(Path.home()))
        return r[0] if r else None

    def data_dir_has_db(self, folder: str) -> bool:
        return bool(folder) and (Path(folder) / "erp.db").is_file()

    def test_server(self, url: str) -> dict:
        u = normalize_url(url)
        if not u:
            return {"ok": False, "error": "Sunucu adresini yazın"}
        return {"ok": True, "url": u} if is_erp(u, 5) else {
            "ok": False, "error": f"{u} adresinde LAB ERP sunucusu bulunamadı"}

    def discover(self) -> list[dict]:
        from app.services.discovery import discover

        own = {f"http://{ip}:{self._server.port}" for ip in lan_addresses()} if self._server else set()
        return [s for s in discover() if s["url"] not in own]

    # ---- "Sunucuma kur": install the server on a Linux machine over SSH (remote_install.py) ----

    def pick_key_file(self) -> str | None:
        import webview

        r = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=str(Path.home() / ".ssh"))
        return r[0] if r else None

    def remote_install(self, form: dict) -> dict:
        from remote_install import RemoteInstall, build_package

        if self._remote is not None and not self._remote.done:
            return {"ok": False, "error": "Kurulum sürüyor"}
        try:
            job = RemoteInstall(form, ASSETS / "server_install.sh", config_dir() / "known_hosts")
        except ValueError:
            return {"ok": False, "error": "Port bir sayı olmalı"}
        err = job.validate()
        if err:
            return {"ok": False, "error": err}
        try:
            job.package = build_package(SERVER_SRC, SPA_DIR)
        except FileNotFoundError as e:
            return {"ok": False, "error": str(e)}
        self._remote = job
        job.start()
        return {"ok": True}

    def remote_check(self, form: dict) -> dict:
        """Read-only look at the server before installing; the guide on the setup page shows the answers."""
        from remote_install import RemoteInstall

        try:
            job = RemoteInstall(form, ASSETS / "server_install.sh", config_dir() / "known_hosts")
        except ValueError:
            return {"ok": False, "error": "Port bir sayı olmalı", "problem": "form"}
        return job.check()

    def remote_status(self) -> dict:
        return self._remote.status() if self._remote else {"done": True, "ok": False, "lines": [], "error": ""}

    def apply_settings(self, form: dict) -> dict:
        """Save the setup form and connect. A running embedded server cannot switch settings in-process,
        so in that case the app restarts itself."""
        mode = form.get("mode")
        cfg = dict(self._cfg)
        cfg.pop("_error", None)
        admin_password = None
        if mode == "server":
            data_dir = str(form.get("data_dir") or "").strip()
            try:
                port = int(form.get("port") or DEFAULT_PORT)
            except ValueError:
                return {"ok": False, "error": "Port bir sayı olmalı"}
            if not data_dir:
                return {"ok": False, "error": "Veri klasörünü seçin"}
            if not 1 <= port <= 65535:
                return {"ok": False, "error": "Port 1-65535 arasında olmalı"}
            if not self.data_dir_has_db(data_dir):
                admin_password = str(form.get("admin_password") or "")
                if len(admin_password) < 8:
                    return {"ok": False, "error": "Yönetici şifresi en az 8 karakter olmalı"}
            cfg.update(mode="server", data_dir=data_dir, port=port)
            cfg.setdefault("jwt_secret", secrets.token_urlsafe(48))
        elif mode == "client":
            t = self.test_server(str(form.get("server_url") or ""))
            if not t["ok"]:
                return t
            cfg.update(mode="client", server_url=t["url"])
        else:
            return {"ok": False, "error": "Çalışma şeklini seçin"}
        self._cfg = cfg
        save_config(cfg)
        if self._server is not None:
            self._restart()
            return {"ok": True}
        threading.Thread(target=self._connect, args=(admin_password,), daemon=True).start()
        return {"ok": True}

    def show_settings(self) -> None:
        self._show_html(self._setup_html)

    def file_request(self, req: dict) -> dict:
        """Fetch /api<path> with the user's token, then save it (dialog) or open it with the default program."""
        import webview

        path = str(req.get("path") or "")
        if not path.startswith("/") or not self._base:
            return {"ok": False, "error": "Geçersiz istek"}
        headers = {"User-Agent": f"ParcaTakipERP/{VERSION}"}
        if req.get("token"):
            headers["Authorization"] = f"Bearer {req['token']}"
        data = None
        if req.get("body") is not None:
            data = json.dumps(req["body"]).encode("utf-8")
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(f"{self._base}/api{path}", data=data, headers=headers,
                                   method=str(req.get("method") or ("POST" if data else "GET")))
        try:
            resp = urllib.request.urlopen(r, timeout=600)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail") or ""
            except (ValueError, AttributeError):
                pass
            return {"ok": False, "status": e.code,
                    "error": detail if isinstance(detail, str) and detail else f"İndirme başarısız ({e.code})"}
        except OSError as e:
            return {"ok": False, "error": f"Sunucuya ulaşılamadı: {e}"}
        with resp:
            name = safe_name(disposition_name(resp.headers.get("Content-Disposition", "")) or
                             str(req.get("filename") or ""))
            action = req.get("action")
            if action == "open" and Path(name).suffix.lower() in OPEN_EXTS:
                folder = Path(tempfile.gettempdir()) / "ParcaTakipERP"
                folder.mkdir(exist_ok=True)
                target = folder / name
            else:
                downloads = Path.home() / "Downloads"
                picked = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name,
                                                         directory=str(downloads if downloads.is_dir() else Path.home()))
                if not picked:
                    return {"ok": False, "cancelled": True}
                target = Path(picked if isinstance(picked, str) else picked[0])
                action = "save"
            try:
                with open(target, "wb") as f:
                    shutil.copyfileobj(resp, f, 1024 * 1024)
            except OSError as e:
                return {"ok": False, "error": f"Dosya yazılamadı: {e}"}
        if action == "open":
            open_with_default(target)
        return {"ok": True, "path": str(target)}

    # --- internals (not exposed: leading underscore) ---
    def _loading_html(self) -> str:
        return self._setup_html.replace("<body>", '<body class="loading">', 1)

    def _show_html(self, html: str) -> None:
        # While WebView2 is still starting (first run on a new PC takes seconds), pywebview drops
        # load_html and later shows window.html, the page the window was created with. Keep that in step,
        # or the window stays on the "açılıyor" screen for good.
        self._window.html = html
        self._window.real_url = None
        self._window.load_html(html)

    def _on_start(self) -> None:
        # Wait for the first page (WebView2 ready) before switching pages; carry on if it never comes
        if not self._window.events.loaded.wait(60):
            log.warning("webview did not report loaded within 60 s")
        log.info("webview ready, mode=%s", self._cfg.get("mode"))
        self._paint_title_bar(self._cfg.get("theme") or {"dark": True, "caption": "#0f172a", "text": "#e6e9ee"})
        if self._cfg.get("mode") in ("server", "client"):
            self._connect(None)
        elif '<body class="loading">' in (self._window.html or ""):
            self._show_html(self._setup_html)
        threading.Thread(target=self._check_update, args=(True,), daemon=True).start()

    def _fail(self, msg: str) -> None:
        log.error("%s", msg)
        self._cfg["_error"] = msg
        self._show_html(self._setup_html)

    def _connect(self, admin_password: str | None) -> None:
        c = self._cfg
        self._show_html(self._loading_html())
        if c.get("mode") == "client":
            url = c.get("server_url", "")
            if not is_erp(url, 6):
                # The server may have got a new IP from the router: if exactly one server answers on the
                # LAN, switch to it and remember the new address
                try:
                    found = self.discover()
                except Exception:  # noqa: BLE001 - discovery is best effort
                    log.exception("discovery failed")
                    found = []
                if len(found) != 1:
                    return self._fail(f"{url} adresindeki sunucuya bağlanılamadı. Sunucu bilgisayarın açık, "
                                      "uygulamanın çalışır ve iki cihazın aynı ağda olduğunu kontrol edin."
                                      + (" Ağda birden fazla sunucu var, birini seçin." if found else ""))
                log.info("server moved: %s -> %s", url, found[0]["url"])
                url = c["server_url"] = found[0]["url"]
                save_config({k: v for k, v in c.items() if not k.startswith("_")})
            self._base = url
        else:
            port = int(c.get("port", DEFAULT_PORT))
            local = f"http://127.0.0.1:{port}"
            # After a restart the old process may still hold the port for a moment
            for _ in range(50):
                if port_free(port):
                    break
                time.sleep(0.2)
            if not port_free(port):
                if is_erp(local):
                    log.info("port %s already serves an ERP; connecting to it", port)
                    self._base = local
                    self._window.load_url(local + "/")
                    return None
                return self._fail(f"{port} numaralı port başka bir program tarafından kullanılıyor. "
                                  "Ayarlardan başka bir port seçin.")
            try:
                srv = EmbeddedServer(Path(c["data_dir"]), port, c["jwt_secret"], admin_password)
                srv.start()
            except Exception as e:  # noqa: BLE001 - shown on the setup page
                log.exception("server start failed")
                return self._fail(f"Sunucu başlatılamadı: {e}")
            self._server = srv
            self._base = srv.local_url
            self._start_background()
        self._cfg.pop("_error", None)
        log.info("opening %s", self._base)
        self._window.load_url(self._base + "/")
        return None

    # --- background mode: the server outlives the window until "Sunucuyu durdur ve çık" in the tray ---
    def _start_background(self) -> None:
        if not IS_WIN or self._tray is not None:
            return
        try:
            import pystray
            from PIL import Image

            addresses = ", ".join(f"{ip}:{self._server.port}" for ip in lan_addresses()) or "ağ bağlantısı yok"
            self._tray = pystray.Icon("LabERP", Image.open(ASSETS / "icon.ico"), f"{APP_NAME} sunucusu çalışıyor",
                                      pystray.Menu(
                pystray.MenuItem(f"{APP_NAME} penceresini aç", lambda icon, item: self._show_window(), default=True),
                pystray.MenuItem(f"Adres: {addresses}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sunucuyu durdur ve çık", lambda icon, item: self._tray_quit())))
            self._tray.run_detached()
            self._window.native.FormClosing += self._on_form_closing
        except Exception:  # noqa: BLE001 - the app still works, only without the background mode
            log.exception("tray start failed")
            self._tray = None
            return
        self._listen_for_wake()

    def _on_form_closing(self, _sender, args) -> None:
        """Runs on the UI thread. Only the user's close is turned into hide: Windows shutdown, log off and
        Task Manager must go through, or the hidden window would block them."""
        try:
            from System.Windows.Forms import CloseReason

            if self._quitting or self._tray is None or args.CloseReason != CloseReason.UserClosing:
                return
            args.Cancel = True
            self._hide_window()
        except Exception:  # noqa: BLE001 - an exception must not cross into .NET
            log.exception("close to tray failed")

    def _hide_window(self) -> None:
        self._window.hide()
        if not self._hint_shown:
            self._hint_shown = True
            self._tray.notify("Sunucu arka planda çalışmaya devam ediyor. Kapatmak için saatin yanındaki gizli "
                              f"simgelerden {APP_NAME} simgesine sağ tıklayın.", APP_NAME)

    def _show_window(self) -> None:
        self._window.show()
        if str(self._window.native.WindowState) == "Minimized":
            self._window.restore()

    def _tray_quit(self) -> None:
        import ctypes

        text = "Sunucu durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. Kapatılsın mı?"
        # OK/Cancel, warning icon, always on top: the window may be hidden, so it cannot own this dialog
        if ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x1 | 0x30 | 0x40000 | 0x10000) == 1:
            self._leave()

    def _listen_for_wake(self) -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", INSTANCE_PORT))
            srv.listen(4)
        except OSError:
            log.exception("instance port busy")
            return
        self._listener = srv

        def serve() -> None:
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                try:
                    with conn:
                        conn.settimeout(2)
                        if conn.recv(32) == INSTANCE_HELLO:
                            conn.sendall(b"OK")
                            self._show_window()
                except Exception:  # noqa: BLE001 - keep listening
                    log.exception("wake failed")

        threading.Thread(target=serve, name="instance", daemon=True).start()

    def _stop_listener(self) -> None:
        if self._listener is not None:
            self._listener.close()
            self._listener = None

    def _leave(self) -> None:
        """Really end the app."""
        self._quitting = True
        self._stop_listener()
        if self._tray is not None:
            self._tray.stop()
        if self._server:
            self._server.stop()
        self._window.destroy()

    def _tray_self_test(self) -> None:
        import ctypes

        def until(cond, timeout: float = 20) -> bool:
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if cond():
                    return True
                time.sleep(0.2)
            return False

        result: dict = {"version": VERSION}
        try:
            result["tray"] = until(lambda: self._tray is not None and self._tray.visible, 90)
            hwnd = ctypes.c_void_p(int(self._window.native.Handle.ToInt64()))
            user32 = ctypes.windll.user32
            user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
            visible = lambda: bool(user32.IsWindowVisible(hwnd))  # noqa: E731
            result["shown"] = until(visible)
            # WM_SYSCOMMAND + SC_CLOSE is what the title bar X sends; a bare WM_CLOSE reads as TaskManagerClosing
            user32.PostMessageW(hwnd, 0x0112, 0xF060, None)
            result["hidden"] = until(lambda: not visible())
            result["server_alive"] = is_erp(self._server.local_url)
            second = subprocess.run([sys.executable], timeout=60, check=False)
            result["second_start_exit"] = second.returncode
            result["reopened"] = until(visible)
            result["ok"] = all(result[k] for k in ("tray", "shown", "hidden", "server_alive", "reopened")) \
                and second.returncode == 0
        except Exception as e:  # noqa: BLE001
            log.exception("tray test failed")
            result["error"] = repr(e)
        TRAY_TEST.write_text(json.dumps(result), encoding="utf-8")
        self._leave()

    def _restart(self) -> None:
        self._stop_listener()   # or the new process would only wake this one and exit
        args = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
        subprocess.Popen(args, close_fds=True)
        self._leave()

    def _alert(self, text: str) -> None:
        self._window.evaluate_js(f"alert({json.dumps(text)})")

    def _check_update(self, silent: bool) -> None:
        if silent:
            time.sleep(5)
        try:
            rel = latest_release()
        except (OSError, ValueError, KeyError) as e:
            log.info("update check failed: %s", e)
            if not silent:
                self._alert(f"Güncelleme sunucusuna ulaşılamadı.\n{e}")
            return
        if rel is None:
            if not silent:
                self._alert(f"{APP_NAME} güncel (sürüm {VERSION}).")
            return
        msg = f"Yeni sürüm {rel['version']} hazır (kullandığınız sürüm {VERSION})."
        if IS_WIN and rel["asset"]:
            if self._window.create_confirmation_dialog("Güncelleme", msg + "\n\nŞimdi indirip kurulsun mu?"):
                self._install_update(rel["asset"])
        elif self._window.create_confirmation_dialog("Güncelleme", msg + "\n\nİndirme sayfası açılsın mı?"):
            webbrowser.open(rel["url"])

    def _install_update(self, url: str) -> None:
        target = Path(tempfile.gettempdir()) / safe_name(url.rsplit("/", 1)[-1], "LabERP-Setup.exe")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"ParcaTakipERP/{VERSION}"})
            with urllib.request.urlopen(req, timeout=600) as r, open(target, "wb") as f:
                shutil.copyfileobj(r, f, 1024 * 1024)
        except OSError as e:
            self._alert(f"Güncelleme indirilemedi.\n{e}")
            return
        # The installer closes this app, updates it and starts it again (postinstall entry in installer.iss)
        subprocess.Popen([str(target), "/SILENT", "/NORESTART"], close_fds=True)
        self._leave()

    # ---- in-app "Uygulama" menu (frontend/src/components/DesktopMenu.tsx) ----
    # The native WinForms menu bar was white in every theme, so its actions now live in the themed web UI.

    def app_info(self) -> dict:
        urls = [f"http://{ip}:{self._server.port}" for ip in lan_addresses()] if self._server else []
        return {"version": VERSION, "mode": "server" if self._server else "client", "base": self._base or "",
                "addresses": urls, "data_dir": str(self._server.data_dir) if self._server else "",
                "background": self._tray is not None,
                "config": str(CONFIG_FILE)}

    def app_action(self, name: str) -> dict:
        if name == "reload":
            if self._base:
                self._window.load_url(self._base + "/")
        elif name == "settings":
            self.show_settings()
        elif name == "open_data":
            if self._server is None:
                return {"ok": False, "error": "Veri klasörü yalnızca sunucu modunda bu bilgisayardadır."}
            open_folder(self._server.data_dir)
        elif name == "update":
            threading.Thread(target=self._check_update, args=(False,), daemon=True).start()
        elif name == "quit":
            if self._tray is not None:
                self._hide_window()
            else:
                threading.Timer(0.1, self._window.destroy).start()
        else:
            return {"ok": False, "error": f"Bilinmeyen işlem: {name}"}
        return {"ok": True}

    def set_theme(self, theme: dict) -> dict:
        """Paint the Windows title bar like the app theme; remembered for the next start."""
        def color(v: object, default: str) -> str:
            v = str(v or "").strip()
            return v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default
        t = {"dark": bool(theme.get("dark")), "caption": color(theme.get("caption"), "#0f172a"),
             "text": color(theme.get("text"), "#e6e9ee")}
        if self._cfg.get("theme") != t:
            self._cfg["theme"] = t
            if self._cfg.get("mode"):
                save_config({k: v for k, v in self._cfg.items() if not k.startswith("_")})
        return {"ok": self._paint_title_bar(t)}

    def _paint_title_bar(self, t: dict) -> bool:
        if not IS_WIN or self._window is None or self._window.native is None:
            return False
        try:
            import ctypes

            hwnd = ctypes.c_void_p(int(self._window.native.Handle.ToInt64()))
            dwm = ctypes.windll.dwmapi

            def put(attr: int, value: int) -> bool:
                v = ctypes.c_int(value)
                return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0

            def colorref(h: str) -> int:  # #RRGGBB -> 0x00BBGGRR
                return int(h[5:7], 16) << 16 | int(h[3:5], 16) << 8 | int(h[1:3], 16)

            # Dark caption: attribute 20 (Windows 10 20H1+ and 11), 19 on older Windows 10 builds
            ok = put(20, int(t["dark"])) or put(19, int(t["dark"]))
            # Windows 11: exact caption, text and border colours (ignored by Windows 10)
            put(35, colorref(t["caption"]))
            put(36, colorref(t["text"]))
            put(34, colorref(t["caption"]))
            # Repaint the frame now instead of on the next focus change
            ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
            return ok
        except Exception:  # noqa: BLE001  (cosmetic; never break the app over it)
            log.exception("title bar theme failed")
            return False

    def run(self) -> None:
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        server_mode = self._cfg.get("mode") == "server"
        first = self._setup_html if self._cfg.get("mode") not in ("server", "client") else self._loading_html()
        self._window = webview.create_window(
            APP_NAME, html=first, js_api=self,
            width=1440, height=900, min_size=(960, 600), maximized=True, text_select=True,
            confirm_close=server_mode and not IS_WIN, background_color="#0f172a",
            localization={"global.quitConfirmation":
                          "Uygulama kapanınca sunucu da durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. "
                          "Kapatılsın mı?"} if server_mode and not IS_WIN else None)
        self._window.events.closed += lambda: self._server and self._server.stop()
        icon = ASSETS / "icon.ico"
        if TRAY_TEST is not None:
            threading.Thread(target=self._tray_self_test, name="tray-test", daemon=True).start()
        webview.start(self._on_start, private_mode=False, storage_path=str(config_dir() / "webview"),
                      icon=str(icon) if icon.is_file() else None)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        os.startfile(str(path))  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def smoke(folder: Path) -> int:
    """CI check of the frozen bundle without a window: server start, SPA, login, a read, pdfium import."""
    result: dict = {"version": VERSION}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        port = next(p for p in range(18000, 18100) if port_free(p))
        srv = EmbeddedServer(folder, port, secrets.token_urlsafe(32), "smoke-test")
        srv.start()
        base = srv.local_url
        result["health"] = is_erp(base)
        with urllib.request.urlopen(base + "/", timeout=10) as r:
            result["spa"] = b'id="root"' in r.read()
        body = urllib.parse.urlencode({"username": "admin", "password": "smoke-test"}).encode()
        token = http_json(base + "/api/auth/login", 10, data=body)["access_token"]
        projects = http_json(base + "/api/projects", 10, headers={"Authorization": f"Bearer {token}"})
        result["login"] = isinstance(projects, list)
        import pypdfium2
        import webview  # noqa: F401 - the GUI layer must be in the bundle too

        result["pdfium"] = pypdfium2.PdfDocument.new() is not None
        ok = all(result.get(k) for k in ("health", "spa", "login", "pdfium"))
    except Exception as e:  # noqa: BLE001
        log.exception("smoke failed")
        result["error"] = repr(e)
        ok = False
    result["ok"] = ok
    (folder / "smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if ok else 1


def main() -> None:
    global UI_TEST, TRAY_TEST
    setup_logging()
    log.info("start %s frozen=%s", VERSION, FROZEN)
    if len(sys.argv) >= 3 and sys.argv[1] == "--smoke":
        code = smoke(Path(sys.argv[2]))
        logging.shutdown()
        os._exit(code)  # uvicorn and the backup thread are daemons; skip their shutdown
    if len(sys.argv) >= 3 and sys.argv[1] == "--ui-test":
        UI_TEST = Path(sys.argv[2])
        UI_TEST.unlink(missing_ok=True)
        # The setup page must call get_state within 120 s, or the window is stuck
        threading.Timer(120, lambda: (log.error("ui-test: no setup page"), os._exit(1))).start()
    if len(sys.argv) >= 3 and sys.argv[1] == "--tray-test":
        TRAY_TEST = Path(sys.argv[2])
        TRAY_TEST.unlink(missing_ok=True)
        threading.Timer(240, lambda: (log.error("tray-test: timed out"), os._exit(1))).start()
    if IS_WIN and UI_TEST is None and TRAY_TEST is None and load_config().get("mode") == "server" and wake_running_app():
        log.info("already running; its window was brought to the front")
        logging.shutdown()
        os._exit(0)
    DesktopApp().run()
    result = UI_TEST or TRAY_TEST
    if result is not None:
        ok = result.is_file() and json.loads(result.read_text(encoding="utf-8")).get("ok")
        logging.shutdown()
        os._exit(0 if ok else 1)
    os._exit(0)


if __name__ == "__main__":
    main()
