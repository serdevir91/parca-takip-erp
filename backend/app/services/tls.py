"""HTTPS with a certificate made on this server, for LANs that have no domain name or public certificate.

The files live in data_dir/tls and their presence is what turns HTTPS on: `serve` and the desktop app use them at
the next start. They never go into a backup. Browsers warn about a certificate like this one, so the apps do not
rely on a certificate authority: they remember the fingerprint on first contact and refuse a different one."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ..config import get_settings
from . import discovery

FOLDER = "tls"
VALID_DAYS = 3650


def folder(data_dir: Path | None = None) -> Path:
    return Path(data_dir or get_settings().data_dir) / FOLDER


def files(data_dir: Path | None = None) -> tuple[Path, Path]:
    d = folder(data_dir)
    return d / "cert.pem", d / "key.pem"


def enabled(data_dir: Path | None = None) -> bool:
    return all(p.is_file() for p in files(data_dir))


def _names() -> tuple[list[str], list[str]]:
    hosts = list(dict.fromkeys(["localhost", socket.gethostname()]))
    return hosts, list(dict.fromkeys(["127.0.0.1", *discovery._local_ipv4()]))


def enable(data_dir: Path | None = None) -> None:
    """Make the certificate when there is none yet. Idempotent: a new one would break every client's pin."""
    cert_file, key_file = files(data_dir)
    if enabled(data_dir):
        return
    cert_file.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    hosts, ips = _names()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[-1][:64] or "LAB ERP"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LAB ERP")])
    now = datetime.now(timezone.utc)
    san = [x509.DNSName(h) for h in hosts] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def disable(data_dir: Path | None = None) -> None:
    for p in files(data_dir):
        p.unlink(missing_ok=True)


def fingerprint(data_dir: Path | None = None) -> str:
    """SHA-256 of the certificate as lowercase hex, "" without HTTPS."""
    if not enabled(data_dir):
        return ""
    der = ssl.PEM_cert_to_DER_cert(files(data_dir)[0].read_text())
    return hashlib.sha256(der).hexdigest()


def uvicorn_args(data_dir: Path | None = None) -> dict[str, str]:
    if not enabled(data_dir):
        return {}
    cert_file, key_file = files(data_dir)
    return {"ssl_certfile": str(cert_file), "ssl_keyfile": str(key_file)}
