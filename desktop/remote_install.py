"""'Sunucuma kur': install or update the LAB ERP server on a Linux machine over SSH.

The desktop app packs the backend source and the built frontend (same version as the app), uploads them with
server_install.sh over SFTP and runs the script as root (sudo with the same password when the user is not
root). The script sets up a venv, a systemd service (laberp) and /var/lib/laberp; see server_install.sh.
"""
from __future__ import annotations

import io
import logging
import posixpath
import shlex
import tarfile
import threading
import time
from pathlib import Path

log = logging.getLogger("laberp.remote")

SKIP = {"__pycache__", ".pytest_cache", ".DS_Store"}


def build_package(backend: Path, spa: Path) -> bytes:
    """tar.gz with backend/{app,alembic,alembic.ini,requirements.txt} and frontend/dist, the repo layout the
    backend expects (app/config.py finds ../frontend/dist next to the backend folder)."""
    buf = io.BytesIO()

    def keep(t: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if any(part in SKIP for part in Path(t.name).parts) or t.name.endswith((".pyc", ".pyo")):
            return None
        t.uid = t.gid = 0
        t.uname = t.gname = "root"
        t.mode = 0o755 if t.isdir() else 0o644
        return t

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("app", "alembic", "alembic.ini", "requirements.txt"):
            src = backend / name
            if not src.exists():
                raise FileNotFoundError(f"Sunucu paketi eksik: {src}")
            tar.add(str(src), arcname=f"backend/{name}", filter=keep)
        if not (spa / "index.html").is_file():
            raise FileNotFoundError(f"Arayüz dosyaları eksik: {spa}")
        tar.add(str(spa), arcname="frontend/dist", filter=keep)
    return buf.getvalue()


class RemoteInstall:
    """One install run in a background thread; the setup page polls status()."""

    def __init__(self, form: dict, script: Path, known_hosts: Path) -> None:
        self.host = str(form.get("host") or "").strip()
        self.ssh_port = int(form.get("ssh_port") or 22)
        self.user = str(form.get("user") or "").strip() or "root"
        self.password = str(form.get("password") or "")
        self.key_file = str(form.get("key_file") or "").strip()
        self.port = int(form.get("port") or 8000)
        self.admin_password = str(form.get("admin_password") or "")
        self.firewall = bool(form.get("firewall", True))
        self.package = b""   # build_package() output, set by the caller after validate()
        self._script = script
        self._known_hosts = known_hosts
        self.lines: list[str] = []
        self.step = "Bağlanılıyor"
        self.done = False
        self.ok = False
        self.error = ""
        self._lock = threading.Lock()

    def validate(self) -> str:
        if not self.host or any(c in self.host for c in " /\\@"):
            return "Sunucu adresini yazın (örnek 192.168.1.50 veya erp.firma.com)"
        if not 1 <= self.ssh_port <= 65535 or not 1 <= self.port <= 65535:
            return "Port 1-65535 arasında olmalı"
        if not self.password and not self.key_file:
            return "SSH şifresini yazın veya bir SSH anahtar dosyası seçin"
        if self.admin_password and len(self.admin_password) < 8:
            return "Yönetici şifresi en az 8 karakter olmalı"
        return ""

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    def start(self) -> None:
        threading.Thread(target=self._run, name="remote-install", daemon=True).start()

    def status(self) -> dict:
        with self._lock:
            return {"step": self.step, "lines": self.lines[-200:], "done": self.done, "ok": self.ok,
                    "error": self.error, "url": self.url}

    def _add(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        if self.password and self.password in line:
            line = line.replace(self.password, "***")
        with self._lock:
            if line.startswith("## "):
                self.step = line[3:]
            self.lines.append(line)
        log.info("remote: %s", line)

    def _finish(self, ok: bool, error: str = "") -> None:
        with self._lock:
            self.done, self.ok, self.error = True, ok, error

    def _run(self) -> None:
        try:
            self._install()
        except Exception as e:  # noqa: BLE001  (every failure ends up on the setup page)
            log.exception("remote install failed")
            self._finish(False, _explain(e))

    def _install(self) -> None:
        import paramiko

        client = paramiko.SSHClient()
        # Trust on first use; a changed host key afterwards is refused (BadHostKeyException)
        if self._known_hosts.is_file():
            client.load_host_keys(str(self._known_hosts))
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._add(f"## {self.user}@{self.host}:{self.ssh_port} adresine bağlanılıyor")
        client.connect(self.host, port=self.ssh_port, username=self.user, password=self.password or None,
                       key_filename=self.key_file or None, passphrase=self.password or None,
                       timeout=15, banner_timeout=30, auth_timeout=30, look_for_keys=not self.password,
                       allow_agent=False)
        try:
            self._known_hosts.parent.mkdir(parents=True, exist_ok=True)
            client.save_host_keys(str(self._known_hosts))
        except OSError:
            log.warning("could not save known hosts")
        key = client.get_transport().get_remote_server_key()
        self._add(f"Bağlandı. Sunucu anahtarı {key.get_name()} {key.fingerprint}")
        try:
            self._upload_and_run(client)
        finally:
            client.close()

    def _upload_and_run(self, client) -> None:
        work = f"/tmp/laberp-install-{int(time.time())}"
        self._add("## Dosyalar sunucuya gönderiliyor")
        sftp = client.open_sftp()
        try:
            sftp.mkdir(work, 0o700)
            with sftp.open(posixpath.join(work, "laberp-server.tgz"), "wb") as f:
                f.set_pipelined(True)
                f.write(self.package)
            # LF only: a Windows checkout may have turned the script into CRLF, which bash rejects
            with sftp.open(posixpath.join(work, "server_install.sh"), "wb") as f:
                f.write(self._script.read_bytes().replace(b"\r\n", b"\n"))
            if self.admin_password:
                with sftp.open(posixpath.join(work, "admin_password"), "w") as f:
                    f.chmod(0o600)
                    f.write(self.admin_password)
        finally:
            sftp.close()
        self._add(f"{len(self.package) // 1024} KB gönderildi")
        cmd = "bash " + " ".join(shlex.quote(a) for a in (
            f"{work}/server_install.sh", work, str(self.port), "1" if self.firewall else "0"))
        root = self.user == "root"
        if not root:
            # The password goes through stdin, never the command line; -k so sudo always reads it
            cmd = f"sudo -S -k -p '' {cmd}"
        chan = client.get_transport().open_session()
        chan.set_combine_stderr(True)
        chan.exec_command(cmd)
        if not root:
            chan.sendall((self.password + "\n").encode())
        chan.shutdown_write()
        buf = b""
        while True:
            if chan.recv_ready():
                buf += chan.recv(65536)
                *full, buf = buf.split(b"\n")
                for raw in full:
                    self._add(raw.decode("utf-8", "replace"))
            elif chan.exit_status_ready():
                break
            else:
                time.sleep(0.1)
        while chan.recv_ready():
            buf += chan.recv(65536)
        for raw in buf.split(b"\n"):
            self._add(raw.decode("utf-8", "replace"))
        code = chan.recv_exit_status()
        if code == 0:
            self._add("## Kurulum tamamlandı")
            self._finish(True)
            return
        last = next((ln[3:] for ln in reversed(self.lines) if ln.startswith("!! ")), "")
        if not last and not root and any("incorrect password" in ln or "sudo:" in ln for ln in self.lines[-5:]):
            last = f"sudo şifresi kabul edilmedi veya {self.user} kullanıcısının sudo yetkisi yok"
        self._finish(False, last or f"Kurulum betiği hata verdi (çıkış kodu {code}); ayrıntılar yukarıda")


def _explain(e: Exception) -> str:
    import socket

    import paramiko

    if isinstance(e, paramiko.AuthenticationException):
        return "SSH kullanıcı adı veya şifresi kabul edilmedi"
    if isinstance(e, paramiko.BadHostKeyException):
        return ("Sunucunun SSH anahtarı daha önce bağlanılandan farklı. Sunucu yeniden kurulduysa "
                "bilinen anahtarı silin (ayarlar klasöründeki known_hosts dosyası); kurulmadıysa bağlanmayın.")
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "Sunucuya ulaşılamadı (zaman aşımı). Adresi, SSH portunu ve ağ bağlantısını kontrol edin."
    if isinstance(e, (ConnectionRefusedError, paramiko.ssh_exception.NoValidConnectionsError)):
        return "SSH bağlantısı reddedildi. Sunucuda SSH (port 22) açık mı?"
    if isinstance(e, socket.gaierror):
        return "Sunucu adı çözülemedi. Adresi kontrol edin."
    if isinstance(e, FileNotFoundError):
        return str(e)
    return f"{type(e).__name__}: {e}"
