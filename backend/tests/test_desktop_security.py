"""The desktop shell: signed updates, the pinned certificate, what its JS API allows on which page."""
import base64
import importlib.util
import socket
import ssl
import sys
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services import tls

SHELL = Path(__file__).resolve().parents[2] / "desktop" / "parca_takip_desktop.py"


@pytest.fixture(scope="module")
def desk():
    spec = importlib.util.spec_from_file_location("parca_takip_desktop", SHELL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _key(desk, monkeypatch):
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setattr(desk, "UPDATE_PUBLIC_KEY", base64.b64encode(raw).decode())
    return key


def test_update_needs_the_release_signature(desk, monkeypatch, tmp_path):
    import hashlib
    key = _key(desk, monkeypatch)
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"installer")
    good = key.sign(hashlib.sha256(b"installer").digest())
    assert desk.verify_update(exe, good)
    exe.write_bytes(b"installer + virus")
    assert not desk.verify_update(exe, good)
    assert not desk.verify_update(exe, b"\0" * 64)


def _serve_tls(data_dir):
    tls.enable(data_dir)
    cert, key = tls.files(data_dir)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = socket.create_server(("127.0.0.1", 0))

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            try:
                with ctx.wrap_socket(c, server_side=True) as s:
                    s.recv(100)
            except (OSError, ssl.SSLError):
                pass

    threading.Thread(target=loop, daemon=True).start()
    return srv, f"https://127.0.0.1:{srv.getsockname()[1]}"


def test_only_the_pinned_certificate_is_accepted(desk, tmp_path):
    srv, url = _serve_tls(tmp_path / "a")
    try:
        der = desk.peer_certificate(url)
        port = srv.getsockname()[1]
        import hashlib
        assert hashlib.sha256(der).hexdigest() == tls.fingerprint(tmp_path / "a")

        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with desk.pinned_context(der).wrap_socket(raw, server_hostname="127.0.0.1"):
                pass

        tls.enable(tmp_path / "b")
        other = ssl.PEM_cert_to_DER_cert(tls.files(tmp_path / "b")[0].read_text())
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with pytest.raises(ssl.SSLCertVerificationError):
                desk.pinned_context(other).wrap_socket(raw, server_hostname="127.0.0.1")
    finally:
        srv.close()


class _Window:
    url = None

    def get_current_url(self):
        return self.url


def _shell(desk, base, url):
    a = object.__new__(desk.DesktopApp)
    a._window, a._base, a._on_setup = _Window(), base, False
    a._window.url = url
    return a


def test_server_pages_cannot_reach_setup_actions(desk):
    a = _shell(desk, "http://10.0.0.5:8000", "http://10.0.0.5:8000/p/1")
    a._cfg = {}
    for call in (lambda: a.get_state(), lambda: a.discover(), lambda: a.remote_status(), lambda: a.pick_key_file(),
                 lambda: a.apply_settings({"mode": "client", "server_url": "http://evil"}),
                 lambda: a.remote_install({})):
        with pytest.raises(PermissionError):
            call()


def test_foreign_page_cannot_use_app_actions(desk):
    a = _shell(desk, "http://10.0.0.5:8000", "http://evil.example/")
    with pytest.raises(PermissionError):
        a.app_action("quit")
    with pytest.raises(PermissionError):
        a.file_request({"path": "/x"})
    a._window.url = "http://10.0.0.5:8000.evil.example/"
    with pytest.raises(PermissionError):
        a.app_action("quit")
    a._window.url = "http://10.0.0.5:8000/parts"
    assert a._app_only() is None
