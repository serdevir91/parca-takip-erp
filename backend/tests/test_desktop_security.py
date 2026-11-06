"""The desktop shell: signed updates, the pinned certificate, what its JS API allows on which page."""
import base64
import importlib.util
import socket
import ssl
import sys
import threading
import urllib.error
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


def test_an_address_without_a_port_tries_the_server_port(desk):
    assert desk.server_candidates("192.168.1.5") == [
        "http://192.168.1.5:8000", "http://192.168.1.5", "https://192.168.1.5:8000", "https://192.168.1.5"]
    assert desk.server_candidates("http://192.168.1.5/") == ["http://192.168.1.5:8000", "http://192.168.1.5"]
    assert desk.server_candidates("192.168.1.5:9000") == ["http://192.168.1.5:9000"]
    assert desk.server_candidates("https://erp.example.com/lab") == ["https://erp.example.com/lab"]
    assert desk.server_candidates("  ") == []


def test_local_addresses_skip_the_proxy(desk):
    for url in ("http://192.168.1.5:8000", "http://10.0.0.2", "http://[fd00::1]:8000", "http://server",
                "http://server.local:8000", "http://127.0.0.1:8000"):
        assert desk.is_direct(url), url
    for url in ("https://github.com/x", "http://8.8.8.8"):
        assert not desk.is_direct(url), url


def test_probe_tells_why_a_server_cannot_be_reached(desk, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    assert desk.probe(f"http://127.0.0.1:{closed}", 5) == "refused"   # Windows retries for about 2 seconds first

    answers = {"http://a": {"status": "ok"}, "http://b": {"hello": "world"}}
    monkeypatch.setattr(desk, "http_json", lambda url, *a, **k: answers[url.removesuffix("/api/health")])
    assert desk.probe("http://a") == "ok" and desk.is_erp("http://a")
    assert desk.probe("http://b") == "other" and not desk.is_erp("http://b")

    def fails(error):
        def call(*_a, **_k):
            raise error
        monkeypatch.setattr(desk, "http_json", call)
        return desk.probe("http://a")

    assert fails(urllib.error.URLError(socket.gaierror(8, "no name"))) == "name"
    assert fails(urllib.error.URLError(TimeoutError())) == "timeout"
    assert fails(TimeoutError()) == "timeout"
    assert fails(urllib.error.HTTPError("u", 404, "no", None, None)) == "other"


def test_another_network_is_named_only_when_no_address_shares_it(desk):
    assert desk.other_network("http://192.168.1.5:8000", ["10.20.30.40"])
    assert not desk.other_network("http://192.168.1.5:8000", ["192.168.1.77"])
    assert not desk.other_network("https://erp.example.com", ["10.20.30.40"])
    message = desk.why_unreachable("http://192.168.1.5", "timeout", ["10.20.30.40"])
    assert "192.168.1.5" in message and ("ağda" in message or "network" in message or "red" in message or "Netzwerk" in message)
