"""Parça Takip ERP desktop app: the web UI in a native window (pywebview; Edge WebView2 on Windows).

Two modes, chosen on the first start and changeable from the "Uygulama" menu:
- server ("Bu bilgisayar sunucu"): SQLite database on this PC; the API and the UI run inside this
  process on 0.0.0.0:<port>, so other PCs can connect with a browser or with this app in client mode.
- client ("Ağdaki sunucuya bağlan"): connects to a running server (Docker, Docker-free or another
  desktop app in server mode).

Settings live in desktop.json under %APPDATA%\\ParcaTakipERP. Updates come from the GitHub releases of
the project (silent check at startup and "Güncellemeleri denetle" in the menu).

Dev run on macOS/Linux/Windows:  python desktop/parca_takip_desktop.py   (needs frontend/dist)
Bundle smoke test (CI):           ParcaTakipERP.exe --smoke <empty folder>
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
    ASSETS = BUNDLE
else:
    BACKEND_DIR = BUNDLE.parent / "backend"
    MIGRATIONS = BACKEND_DIR / "alembic"
    SPA_DIR = BUNDLE.parent / "frontend" / "dist"
    ASSETS = BUNDLE
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402  (no settings are read at import time)

APP_NAME = "Parça Takip ERP"
VERSION = Settings.model_fields["app_version"].default
REPO = "serdevir91/parca-takip-erp"
DEFAULT_PORT = 8000
IS_WIN = sys.platform == "win32"


def config_dir() -> Path:
    if IS_WIN:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    d = base / "ParcaTakipERP"
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
    return str(Path.home() / "Documents" / "ParcaTakipERP")


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
        self._base = ""          # URL the window shows: the server root
        self._setup_html = (ASSETS / "setup.html").read_text(encoding="utf-8")

    # --- state for setup.html ---
    def get_state(self) -> dict:
        c = self._cfg
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
            "ok": False, "error": f"{u} adresinde Parça Takip ERP sunucusu bulunamadı"}

    def discover(self) -> list[dict]:
        from app.services.discovery import discover

        own = {f"http://{ip}:{self._server.port}" for ip in lan_addresses()} if self._server else set()
        return [s for s in discover() if s["url"] not in own]

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
        self._window.load_html(self._setup_html)

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
    def _on_start(self) -> None:
        if self._cfg.get("mode") in ("server", "client"):
            self._connect(None)
        else:
            self._window.load_html(self._setup_html)
        threading.Thread(target=self._check_update, args=(True,), daemon=True).start()

    def _fail(self, msg: str) -> None:
        log.error("%s", msg)
        self._cfg["_error"] = msg
        self._window.load_html(self._setup_html)

    def _connect(self, admin_password: str | None) -> None:
        c = self._cfg
        self._window.load_html(self._setup_html.replace("<body>", '<body class="loading">', 1))
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
        self._cfg.pop("_error", None)
        self._window.load_url(self._base + "/")
        return None

    def _restart(self) -> None:
        args = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
        subprocess.Popen(args, close_fds=True)
        if self._server:
            self._server.stop()
        self._window.destroy()

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
        target = Path(tempfile.gettempdir()) / safe_name(url.rsplit("/", 1)[-1], "ParcaTakipERP-Setup.exe")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"ParcaTakipERP/{VERSION}"})
            with urllib.request.urlopen(req, timeout=600) as r, open(target, "wb") as f:
                shutil.copyfileobj(r, f, 1024 * 1024)
        except OSError as e:
            self._alert(f"Güncelleme indirilemedi.\n{e}")
            return
        # The installer closes this app, updates it and starts it again (postinstall entry in installer.iss)
        subprocess.Popen([str(target), "/SILENT", "/NORESTART"], close_fds=True)
        if self._server:
            self._server.stop()
        self._window.destroy()

    def _menu(self) -> list:
        from webview.menu import Menu, MenuAction, MenuSeparator

        def reload() -> None:
            if self._base:
                self._window.load_url(self._base + "/")

        def addresses() -> None:
            if self._server is None:
                self._alert(f"Bağlı sunucu: {self._base or '-'}")
                return
            urls = [f"http://{ip}:{self._server.port}" for ip in lan_addresses()]
            self._alert("Diğer bilgisayarlar tarayıcıdan veya bu uygulamanın \"Ağdaki sunucuya bağlan\" "
                        "seçeneğiyle şu adreslerden bağlanır:\n\n" + ("\n".join(urls) or "(ağ bağlantısı yok)") +
                        "\n\nBağlanamıyorlarsa Windows Güvenlik Duvarı'nda bu uygulamaya izin verin.")

        def open_data() -> None:
            if self._server is not None:
                open_folder(self._server.data_dir)
            else:
                self._alert("Veri klasörü yalnızca sunucu modunda bu bilgisayardadır.")

        def about() -> None:
            mode = "Sunucu (veriler bu bilgisayarda)" if self._server else f"İstemci ({self._base or '-'})"
            self._alert(f"{APP_NAME} masaüstü\nSürüm {VERSION}\nÇalışma şekli: {mode}\nAyarlar: {CONFIG_FILE}")

        return [Menu("Uygulama", [
            MenuAction("Yeniden yükle", reload),
            MenuAction("Bağlantı ayarları…", self.show_settings),
            MenuSeparator(),
            MenuAction("Ağ adresleri", addresses),
            MenuAction("Veri klasörünü aç", open_data),
            MenuSeparator(),
            MenuAction("Güncellemeleri denetle", lambda: threading.Thread(
                target=self._check_update, args=(False,), daemon=True).start()),
            MenuAction("Hakkında", about),
            MenuSeparator(),
            MenuAction("Çıkış", lambda: self._window.destroy()),
        ])]

    def run(self) -> None:
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        server_mode = self._cfg.get("mode") == "server"
        self._window = webview.create_window(
            APP_NAME, html=self._setup_html.replace("<body>", '<body class="loading">', 1), js_api=self,
            width=1440, height=900, min_size=(960, 600), maximized=True, text_select=True,
            confirm_close=server_mode, background_color="#0f172a",
            localization={"global.quitConfirmation":
                          "Uygulama kapanınca sunucu da durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. "
                          "Kapatılsın mı?"} if server_mode else None)
        self._window.events.closed += lambda: self._server and self._server.stop()
        icon = ASSETS / "icon.ico"
        webview.start(self._on_start, private_mode=False, storage_path=str(config_dir() / "webview"),
                      menu=self._menu(), icon=str(icon) if icon.is_file() else None)


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
    setup_logging()
    log.info("start %s frozen=%s", VERSION, FROZEN)
    if len(sys.argv) >= 3 and sys.argv[1] == "--smoke":
        code = smoke(Path(sys.argv[2]))
        logging.shutdown()
        os._exit(code)  # uvicorn and the backup thread are daemons; skip their shutdown
    DesktopApp().run()
    os._exit(0)


if __name__ == "__main__":
    main()
