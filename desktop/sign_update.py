"""Signs a released installer, so the desktop app accepts it as an update. Run after CI has built the .exe:

    python desktop/sign_update.py LabERP-Setup-x.y.z.exe      -> writes LabERP-Setup-x.y.z.exe.sig

The private key stays on the release machine, never in the repository or in CI. The matching public key is
UPDATE_PUBLIC_KEY in parca_takip_desktop.py; losing the private key means shipping a new public key by hand."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization

KEY = Path.home() / ".config" / "lab-erp" / "update_signing_ed25519.pem"


def main() -> None:
    target = Path(sys.argv[1])
    key = serialization.load_pem_private_key(KEY.read_bytes(), None)
    digest = hashlib.sha256(target.read_bytes()).digest()
    sig = target.with_name(target.name + ".sig")
    sig.write_bytes(key.sign(digest))
    print(sig)


if __name__ == "__main__":
    main()
