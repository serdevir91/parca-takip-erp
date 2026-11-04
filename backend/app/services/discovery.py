"""LAN discovery: a server answers a UDP broadcast so desktop clients find it without typing an address.

Started by `app.cli serve` and by the desktop app in server mode. Docker servers sit behind NAT and do not
receive broadcasts; for them the desktop client falls back to probing /api/health on the local subnet.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

PORT = 47811
MAGIC = b"PARCA_TAKIP_ERP_DISCOVER"
log = logging.getLogger("erp.discovery")


def start_responder(http_port: int, version: str, scheme: str = "http", fingerprint: str = "") -> bool:
    """Answer discovery broadcasts in a daemon thread. False if the UDP port is taken (another server)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", PORT))
    except OSError as e:
        log.warning("discovery responder not started: %s", e)
        sock.close()
        return False
    reply = json.dumps({"name": socket.gethostname(), "port": http_port, "version": version, "scheme": scheme,
                        "fingerprint": fingerprint}).encode()

    def loop() -> None:
        while True:
            try:
                data, addr = sock.recvfrom(512)
                if data.strip() == MAGIC:
                    sock.sendto(reply, addr)
            except OSError:
                time.sleep(1)

    threading.Thread(target=loop, name="discovery", daemon=True).start()
    return True


def _local_ipv4() -> list[str]:
    ips: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outgoing interface
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def _broadcast(timeout: float) -> dict[str, dict]:
    found: dict[str, dict] = {}
    targets = {"255.255.255.255"}
    for ip in _local_ipv4():
        targets.add(str(ipaddress.ip_network(f"{ip}/24", strict=False).broadcast_address))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.2)
        for t in targets:
            try:
                s.sendto(MAGIC, (t, PORT))
            except OSError:
                pass
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, (host, _) = s.recvfrom(512)
                info = json.loads(data.decode())
                scheme = "https" if info.get("scheme") == "https" else "http"
                url = f"{scheme}://{host}:{int(info['port'])}"
                found[url] = {"url": url, "name": str(info.get("name") or host), "version": info.get("version"),
                              "fingerprint": str(info.get("fingerprint") or "")}
            except (OSError, ValueError, KeyError):
                continue
    return found


def _probe(url: str) -> bool:
    try:
        with urlopen(f"{url}/api/health", timeout=0.6) as r:
            return json.loads(r.read().decode()).get("status") == "ok"
    except (OSError, ValueError):
        return False


def discover(timeout: float = 1.5, ports: tuple[int, ...] = (8000, 80, 8080)) -> list[dict]:
    """Servers on the LAN: UDP answers first, then a /24 health probe on the usual ports (Docker servers)."""
    found = _broadcast(timeout)
    if not found:
        urls = [f"http://{h}" + ("" if p == 80 else f":{p}")
                for ip in _local_ipv4()
                for h in map(str, ipaddress.ip_network(f"{ip}/24", strict=False).hosts())
                for p in ports]
        with ThreadPoolExecutor(max_workers=128) as ex:
            for url, ok in zip(urls, ex.map(_probe, urls)):
                if ok:
                    found[url] = {"url": url, "name": url.split("//", 1)[1].split(":")[0], "version": None}
    return sorted(found.values(), key=lambda s: s["url"])
