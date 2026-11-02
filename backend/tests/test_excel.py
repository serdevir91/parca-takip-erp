"""Excel export / re-import (SPEC §9)."""
from __future__ import annotations

import io
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.formula import Tokenizer
from sqlalchemy import select

from app.core.status import PROG_DONE, PROG_RUN
from app.models import AuditLog, MissingRow, Part, Project, Tracking
from app.services import bomimport
from app.services import excel_export as ex
from app.services import excel_import as im
from app.services.state import ProjectView

BOM = "BOM_T01_0000_0000_2026-11-02.csv"
# Functions the exports may use (all exist in Excel 2010+ and LibreOffice)
ALLOWED_FUNCS = {"IF", "OR", "AND", "SUBTOTAL", "SUMIF", "COUNTIF", "COUNTIFS", "SUMPRODUCT", "ISNUMBER", "FIND",
                 "ROUNDUP", "SUM", "SUMIFS", "IFERROR", "COUNTA", "ROUND", "MAX", "MIN", "NOT", "LEN", "ISBLANK"}


def _db():
    from app.db import SessionLocal
    return SessionLocal()


def _project(client, tag: str) -> int:
    """Project with the 11-02 BOM approved and one missing row; returns its id."""
    db = _db()
    try:
        p = db.scalar(select(Part).where(Part.part_no == "TSDacikboy"))
        if p is None:
            db.add(Part(part_no="TSDacikboy", is_purchased_assembly=True))
        else:
            p.is_purchased_assembly = True
        db.flush()
        project = Project(name=f"Excel {tag} {uuid.uuid4().hex[:8]}")
        db.add(project)
        db.flush()
        data = (Path(__file__).parent / "data" / BOM).read_bytes()
        v = bomimport.upload_bom(db, project, BOM, data, None)
        bomimport.approve(db, v, None)
        view = ProjectView.load(db, project)
        part = next(x for x in view.parts(include_in_purchased=False)
                    if not x["is_assembly"] and x["procurement"] == "İmalat")
        db.add(MissingRow(project_id=project.id, part_no=part["part_no"], qty=2, reason="Hurda"))
        db.commit()
        return project.id
    finally:
        db.close()


def _build(pid: int, kind: str):
    db = _db()
    try:
        view = ProjectView.load(db, db.get(Project, pid))
        if kind == "takip":
            return ex.build_takip_listesi(db, view)
        if kind == "order":
            return ex.build_fastener_order(db, view)
        return ex.build_parca_takip(db, view)
    finally:
        db.close()


def _roundtrip(wb):
    return load_workbook(io.BytesIO(ex.to_bytes(wb)))


def _headers(ws, row: int = ex.HR) -> list[str]:
    return [c.value for c in ws[row] if c.value is not None]


def _formulas(wb):
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    yield ws, c


@pytest.fixture(scope="module")
def pid(client):
    return _project(client, "export")


def test_parca_takip_structure(pid):
    wb = _roundtrip(_build(pid, "parca"))
    assert wb.sheetnames == [ex.SHEET_SUMMARY, ex.SHEET_PARTS, ex.SHEET_LISTS]
    assert wb[ex.SHEET_LISTS].sheet_state == "hidden"
    ws = wb[ex.SHEET_PARTS]
    assert _headers(ws) == [h for h, _ in ex.PART_COLS]
    assert ws.freeze_panes == "C6"
    assert ws.auto_filter.ref and ws.auto_filter.ref.startswith("A5:")
    assert ws.column_dimensions[ex.PL_[ex.H_KEY]].hidden
    # dropdowns point at the hidden list sheet
    dvs = ws.data_validations.dataValidation
    assert len(dvs) >= 3 and all(d.type == "list" and "Listeler" in d.formula1 for d in dvs)
    prog_col = ex.PL_[ex.H_PROG]
    assert any(prog_col in str(d.sqref) for d in dvs)
    assert any(ex.PL_[ex.H_MANUF] in str(d.sqref) for d in dvs)
    # status formulas + conditional colors
    first = ws.cell(ex.HR + 1, ex.PC[ex.H_STATUS]).value
    assert isinstance(first, str) and first.startswith("=IF(")
    assert len(ws.conditional_formatting) >= 2
    assert str(ws["C3"].value).startswith("=SUBTOTAL(103")
    # one line per part, no assembly except purchased
    types = {ws.cell(r, ex.PC[ex.H_TYPE]).value for r in range(ex.HR + 1, ws.max_row + 1)}
    assert ex.TYPE_ASM not in types and ex.TYPE_PART in types and ex.TYPE_MISSING in types
    keys = [ws.cell(r, ex.PC[ex.H_KEY]).value for r in range(ex.HR + 1, ws.max_row + 1)]
    pkeys = [k for k in keys if k and k.startswith(ex.KEY_PART)]
    assert len(pkeys) == len(set(pkeys))
    assert sum(len(w._charts) for w in wb.worksheets) >= 3


def test_takip_listesi_structure(pid):
    wb = _roundtrip(_build(pid, "takip"))
    assert wb.sheetnames == [ex.SHEET_SUMMARY, ex.SHEET_PARTS, ex.SHEET_FX, ex.SHEET_FX_SUM, ex.SHEET_LISTS]
    assert sum(len(w._charts) for w in wb.worksheets) >= 5
    fs = wb[ex.SHEET_FX_SUM]
    assert _headers(fs) == [h for h, _ in ex.FX_SUM_COLS]
    assert any("SUMIF(" in str(fs.cell(ex.HR + 1, c).value) for c in range(1, fs.max_column + 1))
    assert fs.data_validations.dataValidation
    fx_rows = fs.max_row - ex.HR
    assert fx_rows == 43
    fd = wb[ex.SHEET_FX]
    assert str(fd.cell(ex.HR + 1, 10).value).startswith("=")
    parts = wb[ex.SHEET_PARTS]
    types = {parts.cell(r, ex.PC[ex.H_TYPE]).value for r in range(ex.HR + 1, parts.max_row + 1)}
    assert ex.TYPE_ASM in types
    temin = {parts.cell(r, ex.PC[ex.H_TEMIN]).value for r in range(ex.HR + 1, parts.max_row + 1)}
    assert ex.IN_PURCHASED_TEMIN in temin


def test_order_form(pid):
    wb = _roundtrip(_build(pid, "order"))
    assert ex.SHEET_ORDER in wb.sheetnames


def test_formulas_static(pid):
    """Every formula only references existing sheets and known functions (no #REF!/#NAME? risk)."""
    for kind in ("parca", "takip", "order"):
        wb = _roundtrip(_build(pid, kind))
        names = set(wb.sheetnames)
        n = 0
        for ws, c in _formulas(wb):
            n += 1
            assert "#REF" not in c.value, (ws.title, c.coordinate)
            for t in Tokenizer(c.value).items:
                if t.type == "FUNC" and t.subtype == "OPEN":
                    assert t.value[:-1].upper() in ALLOWED_FUNCS, (ws.title, c.coordinate, t.value)
                if t.type == "OPERAND" and t.subtype == "RANGE" and "!" in t.value:
                    sheet = t.value.rsplit("!", 1)[0].strip("'").replace("''", "'")
                    assert sheet in names, (ws.title, c.coordinate, t.value)
        assert n > 0


def test_endpoints(client, admin_headers, pid):
    for kind in ("takip-listesi", "parca-takip", "baglanti-siparis"):
        r = client.get(f"/api/excel/{pid}/{kind}", headers=admin_headers)
        assert r.status_code == 200, r.text
        cd = r.headers["content-disposition"]
        assert cd.startswith("attachment;") and "filename*=UTF-8''" in cd and 'filename="' in cd
        load_workbook(io.BytesIO(r.content))
    r = client.post(f"/api/excel/{pid}/gorunen", headers=admin_headers, json={"part_nos": []})
    assert r.status_code == 400
    assert client.get(f"/api/excel/{pid}/parca-takip").status_code == 401
    assert client.get("/api/excel/999999/parca-takip", headers=admin_headers).status_code == 404


def test_gorunen_subset(client, admin_headers, pid):
    db = _db()
    try:
        view = ProjectView.load(db, db.get(Project, pid))
        pick = [p["part_no"] for p in view.parts(include_in_purchased=False) if not p["is_assembly"]][:3]
    finally:
        db.close()
    r = client.post(f"/api/excel/{pid}/gorunen", headers=admin_headers, json={"part_nos": pick})
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content))[ex.SHEET_PARTS]
    got = {ws.cell(r_, ex.PC[ex.H_KEY]).value for r_ in range(ex.HR + 1, ws.max_row + 1)}
    assert {ex.KEY_PART + p for p in pick} <= got
    assert len([k for k in got if k and k.startswith(ex.KEY_PART)]) == 3


def _find_row(ws, key: str) -> int:
    for r in range(ex.HR + 1, ws.max_row + 1):
        if ws.cell(r, ex.PC[ex.H_KEY]).value == key:
            return r
    raise AssertionError(key)


def test_reimport_diff_and_apply(client, admin_headers):
    pid = _project(client, "reimport")
    db = _db()
    try:
        view = ProjectView.load(db, db.get(Project, pid))
        imalat = [p for p in view.parts(include_in_purchased=False)
                  if not p["is_assembly"] and p["procurement"] == "İmalat"]
        a, b = imalat[0]["part_no"], imalat[1]["part_no"]
        missing_id = view.missing[0].id
    finally:
        db.close()

    wb = _roundtrip(_build(pid, "takip"))
    ws = wb[ex.SHEET_PARTS]
    ra, rb = _find_row(ws, ex.KEY_PART + a), _find_row(ws, ex.KEY_PART + b)
    ws.cell(ra, ex.PC[ex.H_PROG]).value = PROG_DONE
    ws.cell(ra, ex.PC[ex.H_NOTE]).value = "Excel notu ç"
    ws.cell(rb, ex.PC[ex.H_TEMIN]).value = "Hazır Alım"
    ws.cell(rb, ex.PC[ex.H_PROG]).value = "Bitti"                         # invalid
    ws.cell(rb, ex.PC[ex.H_MANUF]).value = "Olmayan Firma XYZ"            # invalid (not in list)
    rm = _find_row(ws, ex.KEY_MISSING + str(missing_id))
    ws.cell(rm, ex.PC[ex.H_PROG]).value = PROG_RUN
    unk = ws.max_row + 1
    ws.cell(unk, ex.PC[ex.H_PNO]).value = "T99_9999_9999"
    ws.cell(unk, ex.PC[ex.H_KEY]).value = ex.KEY_PART + "T99_9999_9999"
    ws.cell(unk, ex.PC[ex.H_PROG]).value = PROG_DONE
    fs = wb[ex.SHEET_FX_SUM]
    fkey = fs.cell(ex.HR + 1, ex.FC[ex.H_KEY]).value
    fs.cell(ex.HR + 1, ex.FC[ex.H_FX_STATUS]).value = "Sipariş Verildi"
    fs.cell(ex.HR + 1, ex.FC[ex.H_SPARE]).value = 25
    buf = io.BytesIO()
    wb.save(buf)

    files = {"file": ("Takip_Listesi.xlsx", buf.getvalue(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = client.post(f"/api/excel/{pid}/import", headers=admin_headers, files=files)
    assert r.status_code == 200, r.text
    d = r.json()
    ch = {(c["kind"], c["key"], c["field"]): c for c in d["changes"]}
    assert ch[("tracking", a, "progress")]["old"] == "Bekliyor"
    assert ch[("tracking", a, "progress")]["new"] == PROG_DONE
    assert ch[("tracking", a, "note")]["new"] == "Excel notu ç"
    assert ch[("tracking", b, "procurement_override")]["new"] == "Hazır Alım"
    assert ("tracking", b, "progress") not in ch
    assert ch[("missing", str(missing_id), "progress")]["new"] == PROG_RUN
    assert ch[("fastener", fkey[len(ex.KEY_FASTENER):], "order_status")]["new"] == "Sipariş Verildi"
    assert ch[("fastener", fkey[len(ex.KEY_FASTENER):], "spare_pct")]["new"] == 25
    assert len(d["changes"]) == 6, [(c["kind"], c["key"], c["field"]) for c in d["changes"]]
    assert [u["part_no"] for u in d["unknown"]] == ["T99_9999_9999"]
    bad = {(i["key"], i["field"]) for i in d["invalid"]}
    assert (b, "İlerleme") in bad and (b, "Üretici") in bad

    # unchanged export -> empty diff
    clean = io.BytesIO(ex.to_bytes(_build(pid, "takip")))
    r0 = client.post(f"/api/excel/{pid}/import", headers=admin_headers,
                     files={"file": ("x.xlsx", clean.getvalue(), "application/octet-stream")})
    assert r0.status_code == 200 and r0.json()["changes"] == [] and r0.json()["invalid"] == []

    # apply all but the note; one stale change is skipped
    sel = [{k: c[k] for k in ("kind", "key", "field", "new", "old")} for c in d["changes"] if c["field"] != "note"]
    sel.append({"kind": "tracking", "key": b, "field": "progress", "new": PROG_DONE, "old": PROG_RUN})
    r = client.post(f"/api/excel/{pid}/import/apply", headers=admin_headers, json={"changes": sel})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["applied"] == 5 and len(res["skipped"]) == 1

    db = _db()
    try:
        ta = db.scalar(select(Tracking).where(Tracking.project_id == pid, Tracking.part_no == a))
        tb = db.scalar(select(Tracking).where(Tracking.project_id == pid, Tracking.part_no == b))
        assert ta.progress == PROG_DONE and ta.note == "" and ta.updated_by == "admin"
        assert tb.procurement_override == "Hazır Alım" and tb.progress == "Bekliyor"
        assert db.get(MissingRow, missing_id).progress == PROG_RUN
        view = ProjectView.load(db, db.get(Project, pid))
        f = next(x for x in view.fasteners() if x["key"] == fkey[len(ex.KEY_FASTENER):])
        assert f["order_status"] == "Sipariş Verildi" and f["spare_pct"] == 25
        logs = list(db.scalars(select(AuditLog).where(AuditLog.project_id == pid)))
        assert any(x.entity == "tracking" and x.entity_id == a and x.field == "progress" for x in logs)
        assert any(x.action == "excel_import" for x in logs)
    finally:
        db.close()

    # re-applying the same diff is now stale (old no longer matches)
    r = client.post(f"/api/excel/{pid}/import/apply", headers=admin_headers, json={"changes": sel[:1]})
    assert r.json()["applied"] == 0 and len(r.json()["skipped"]) == 1


def test_reimport_bad_files(client, admin_headers, pid):
    r = client.post(f"/api/excel/{pid}/import", headers=admin_headers,
                    files={"file": ("a.csv", b"x;y", "text/csv")})
    assert r.status_code == 400
    r = client.post(f"/api/excel/{pid}/import", headers=admin_headers,
                    files={"file": ("a.xlsx", b"not a zip", "application/octet-stream")})
    assert r.status_code == 400 and "okunamadı" in r.json()["detail"]
    from openpyxl import Workbook
    wb = Workbook()
    wb.active["A1"] = "foo"
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/excel/{pid}/import", headers=admin_headers,
                    files={"file": ("a.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 400
    r = client.post(f"/api/excel/{pid}/import/apply", headers=admin_headers, json={"changes": []})
    assert r.status_code == 400


def test_parse_key():
    assert im._parse_key("P:T01_1", "") == ("tracking", "T01_1")
    assert im._parse_key("", "T01_2") == ("tracking", "T01_2")
    assert im._parse_key("", "T01_2" + ex.MISSING_SUFFIX) is None
    assert im._parse_key("F:Cıvata|ISO|M8", "") == ("fastener", "Cıvata|ISO|M8")


def test_content_disposition():
    cd = ex.content_disposition("Takip_Listesi_T01_ç.xlsx")
    assert 'filename="Takip_Listesi_T01_c.xlsx"' in cd or 'filename="Takip_Listesi_T01__.xlsx"' in cd
    assert "filename*=UTF-8''Takip_Listesi_T01_%C3%A7.xlsx" in cd


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice (soffice) yok")
def test_libreoffice_recalc(pid, tmp_path):
    """Recalculate in LibreOffice: no cell may evaluate to an error (#REF!, #NAME?, #VALUE!, ...)."""
    for kind in ("parca", "takip", "order"):
        src = tmp_path / f"{kind}.xlsx"
        src.write_bytes(ex.to_bytes(_build(pid, kind)))
        out = tmp_path / "out"
        subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(out), str(src)],
                       check=True, capture_output=True, timeout=180)
        wb = load_workbook(out / src.name, data_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    assert not (isinstance(c.value, str) and c.value.startswith("#")), (kind, ws.title, c.coordinate,
                                                                                       c.value)


def test_reimport_part_on_several_rows(client, admin_headers):
    """A part used under several assemblies is listed on several rows of Takip Listesi.
    Editing only one of them is a change, not a conflict; two different edits are a conflict."""
    pid = _project(client, "multirow")
    wb = _roundtrip(_build(pid, "takip"))
    ws = wb[ex.SHEET_PARTS]
    rows: dict[str, list[int]] = {}
    for r in range(ex.HR + 1, ws.max_row + 1):
        k = ws.cell(r, ex.PC[ex.H_KEY]).value
        if k and k.startswith(ex.KEY_PART) and ws.cell(r, ex.PC[ex.H_TYPE]).value == ex.TYPE_PART:
            rows.setdefault(k, []).append(r)
    multi = [(k, rs) for k, rs in rows.items() if len(rs) > 1]
    assert len(multi) >= 2, "BOM has no part on several rows"
    (k1, r1), (k2, r2) = multi[0], multi[1]
    ws.cell(r1[-1], ex.PC[ex.H_PROG]).value = PROG_DONE          # only one row edited
    ws.cell(r2[0], ex.PC[ex.H_PROG]).value = PROG_DONE           # two rows, two different values
    ws.cell(r2[1], ex.PC[ex.H_PROG]).value = PROG_RUN
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/excel/{pid}/import", headers=admin_headers,
                    files={"file": ("t.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    d = r.json()
    ch = {(c["key"], c["field"]): c for c in d["changes"]}
    p1, p2 = k1[len(ex.KEY_PART):], k2[len(ex.KEY_PART):]
    assert ch[(p1, "progress")]["new"] == PROG_DONE
    assert (p2, "progress") not in ch
    assert any(i["key"] == p2 and i["field"] == "İlerleme" for i in d["invalid"])
    assert not any(i["key"] == p1 for i in d["invalid"])


def test_import_requires_editor(client, pid):
    from app.auth import create_token, hash_password  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415
    db = _db()
    try:
        u = User(username=f"xlview_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), role="viewer")
        db.add(u)
        db.commit()
        h = {"Authorization": f"Bearer {create_token(u)}"}
    finally:
        db.close()
    buf = io.BytesIO(ex.to_bytes(_build(pid, "parca")))
    r = client.post(f"/api/excel/{pid}/import", headers=h,
                    files={"file": ("t.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 403
    r = client.post(f"/api/excel/{pid}/import/apply", headers=h, json={"changes": []})
    assert r.status_code == 403
    assert client.get(f"/api/excel/{pid}/parca-takip", headers=h).status_code == 200
