from __future__ import annotations

import io
import uuid
import zipfile

from sqlalchemy import select

from app.models import Part, Project
from app.services import bomimport

F_1102 = "BOM_T01_0000_0000_2026-11-02.csv"


def _project_1102(data_file, prefix: str) -> int:
    """Project with the 11-02 BOM approved directly through bomimport."""
    from app.db import SessionLocal
    with SessionLocal() as db:
        p = db.scalar(select(Part).where(Part.part_no == "TSDacikboy"))
        if p is None:
            db.add(Part(part_no="TSDacikboy", is_purchased_assembly=True))
        else:
            p.is_purchased_assembly = True
        db.flush()
        project = Project(name=f"{prefix} {uuid.uuid4().hex[:8]}")
        db.add(project)
        db.flush()
        v = bomimport.upload_bom(db, project, F_1102, data_file(F_1102).read_bytes(), None)
        bomimport.approve(db, v, None)
        db.commit()
        return project.id


def _pdf(width: int = 595, height: int = 842) -> bytes:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    doc.new_page(width, height)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _upload(client, h, pid, files: list[tuple[str, bytes]]) -> dict:
    r = client.post(f"/api/projects/{pid}/drawings", headers=h,
                    files=[("files", (n, b, "application/octet-stream")) for n, b in files])
    assert r.status_code == 201, r.text
    return r.json()


def test_drawing_upload_match_and_files(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_1102(data_file, "BE resim")
    stray = f"ZZ_{uuid.uuid4().hex[:8]}.pdf"
    pdf1 = _pdf()
    res = _upload(client, h, pid, [("T01_1100_0001 rev C.pdf", pdf1), ("T01_1100_0002 rev A.pdf", _pdf(600)),
                                   (stray, _pdf(610)), ("notlar.txt", b"x")])
    by = {r["filename"]: r for r in res["results"]}
    assert by["T01_1100_0001 rev C.pdf"]["part_no"] == "T01_1100_0001"
    assert not by["T01_1100_0001 rev C.pdf"]["rev_mismatch"]
    assert by["T01_1100_0002 rev A.pdf"]["rev_mismatch"]
    assert by[stray]["part_no"] is None and by["notlar.txt"]["status"] == "rejected"
    did = by["T01_1100_0001 rev C.pdf"]["drawing_id"]

    again = _upload(client, h, pid, [("T01_1100_0001 rev C.pdf", pdf1)])
    assert again["results"][0]["status"] == "unchanged"
    newv = _upload(client, h, pid, [("T01_1100_0001 rev C.pdf", _pdf(620))])["results"][0]
    assert newv["status"] == "new_version" and newv["version_no"] == 2

    listing = client.get(f"/api/projects/{pid}/drawings", headers=h).json()
    assert {"T01_1100_0001", "T01_1100_0002"} <= {i["part_no"] for i in listing["items"]}
    assert any(u["filename"] == stray for u in listing["unmatched"])
    assert "T01_1100_0001" not in listing["no_drawing"] and "T01_1100_0003" in listing["no_drawing"]
    parts = client.get(f"/api/projects/{pid}/parts", headers=h)
    if parts.status_code == 200:
        rows = {p["part_no"]: p for p in parts.json()["rows"]}
        assert rows["T01_1100_0001"]["has_drawing"] and rows["T01_1100_0002"]["drawing_rev_mismatch"]

    f = client.get(f"/api/drawings/{did}/file", headers=h)
    assert f.status_code == 200 and f.content.startswith(b"%PDF")
    assert f.headers["content-type"] == "application/pdf" and "inline" in f.headers["content-disposition"]
    token = h["Authorization"].split()[1]
    assert client.get(f"/api/drawings/{did}/file", params={"access_token": token}).status_code == 200
    assert client.get(f"/api/drawings/{did}/file").status_code == 401
    t = client.get(f"/api/drawings/{did}/thumb", headers=h)
    assert t.status_code == 200 and t.content.startswith(b"\x89PNG")

    z = client.post(f"/api/projects/{pid}/drawings/zip", json={"part_nos": ["T01_1100_0001"]}, headers=h)
    assert z.status_code == 200, z.text
    assert len(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == 1
    assert client.post(f"/api/projects/{pid}/drawings/zip", json={"mode": "x"}, headers=h).status_code == 400

    detail = client.get(f"/api/drawings/{did}", headers=h).json()
    assert sorted(v["version_no"] for v in detail["versions"]) == [1, 2]
    v2 = next(v for v in detail["versions"] if v["version_no"] == 2)
    r = client.delete(f"/api/drawings/versions/{v2['id']}", headers=h)
    assert r.status_code == 200 and r.json()["drawing"]["current_version"] == 1


def test_drawing_assign_zip_and_delete(client, admin_headers, data_file):
    h = admin_headers
    pid = _project_1102(data_file, "BE resim atama")
    stray = f"YY_{uuid.uuid4().hex[:8]}.pdf"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(stray, _pdf(630))
        zf.writestr("__MACOSX/._x.pdf", b"x")
        zf.writestr("oku.exe", b"x")
    res = _upload(client, h, pid, [("paket.zip", buf.getvalue())])
    by = {r["filename"]: r for r in res["results"]}
    assert by[stray]["status"] == "created" and by[stray]["zip"] == "paket.zip"
    assert by["oku.exe"]["status"] == "rejected"
    did = by[stray]["drawing_id"]
    assert any(d["id"] == did for d in client.get("/api/drawings/unmatched", headers=h).json())

    bad = client.post(f"/api/drawings/{did}/assign", json={"part_no": "YOK_9999"}, headers=h)
    assert bad.status_code == 400 and "bulunamadı" in bad.json()["detail"]
    r = client.post(f"/api/drawings/{did}/assign", json={"part_no": "T01_1100_0003"}, headers=h)
    assert r.status_code == 200 and r.json()["part_no"] == "T01_1100_0003" and r.json()["match_via"] == "manual"
    assert not any(d["id"] == did for d in client.get("/api/drawings/unmatched", headers=h).json())
    listing = client.get(f"/api/projects/{pid}/drawings", headers=h).json()
    assert any(i["id"] == did for i in listing["items"])

    r = client.post(f"/api/drawings/{did}/assign", json={"part_no": None}, headers=h)
    assert r.status_code == 200 and r.json()["part_no"] is None

    assert client.delete(f"/api/drawings/{did}", headers=h).status_code == 200
    assert client.get(f"/api/drawings/{did}", headers=h).status_code == 404


def test_drawing_upload_bad_zip_and_unknown_type(client, admin_headers, data_file):
    pid = _project_1102(data_file, "BE resim bozuk zip")
    res = _upload(client, admin_headers, pid, [("bozuk.zip", b"not a zip"), ("not.txt", b"x")])
    by = {r["filename"]: r for r in res["results"]}
    assert by["bozuk.zip"]["status"] == "rejected" and "okunamadı" in by["bozuk.zip"]["error"]
    assert by["not.txt"]["status"] == "rejected"
    assert res["counts"]["rejected"] == 2 and res["counts"]["stored"] == 0
