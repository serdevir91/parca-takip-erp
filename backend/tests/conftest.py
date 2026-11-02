import os
import tempfile
from pathlib import Path

# API tests run against a throwaway SQLite file; must be set before app.db is imported
_TMP = Path(tempfile.mkdtemp(prefix="erp_test_"))
os.environ.setdefault("ERP_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("ERP_DATA_DIR", str(_TMP / "data"))
os.environ.setdefault("ERP_BACKUP_DIR", str(_TMP / "backups"))
os.environ.setdefault("ERP_JWT_SECRET", "test-secret")

import pytest  # noqa: E402

from app.core.bomparse import parse_bom  # noqa: E402

DATA = Path(__file__).parent / "data"


def load(name: str, **kw):
    return parse_bom((DATA / name).read_bytes(), **kw)


@pytest.fixture(scope="session")
def bom_1102():
    return load("BOM_T01_0000_0000_2026-11-02.csv", purchased_assemblies=["TSDacikboy"])


@pytest.fixture(scope="session")
def bom_1031():
    return load("BOM_T01_0000_0000_2026-10-31.csv")


@pytest.fixture(scope="session")
def boms_v():
    return [load(f"BOM_T01_0004_0000_v{i}.csv") for i in (1, 2, 3)]


@pytest.fixture(scope="session")
def client():
    """TestClient with the app started (tables created, defaults seeded)."""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def data_file():
    """Path to a file in tests/data."""
    return lambda name: DATA / name
