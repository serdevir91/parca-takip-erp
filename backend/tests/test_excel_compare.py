"""Comparing any spreadsheet with the project's parts (SPEC §9.1)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.core.status import DEFAULT_TEMIN_TYPES, PROG_DONE, PROG_RUN, PROG_WAIT
from app.models import Project, Setting
from app.services import excel_compare as cp
from app.services.state import ProjectView

from test_excel import _db, _project

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _parts(pid: int) -> list[dict]:
    db = _db()
    try:
        view = ProjectView.load(db, db.get(Project, pid))
        return [p for p in view.parts(include_in_purchased=False)
                if not p["is_assembly"] and p["procurement"] == "İmalat"]
    finally:
        db.close()


def _book(rows: list[list], title: str = "Liste") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _compare(client, headers, pid, data: bytes, name="liste.xlsx", config=None):
    r = client.post(f"/api/excel/{pid}/compare", headers=headers, files={"file": (name, data, XLSX)},
                    data={"config": json.dumps(config)} if config else {})
    assert r.status_code == 200, r.text
    return r.json()


def _apply(client, headers, pid, res, new_temins=()):
    body = {"changes": [{k: c[k] for k in ("kind", "key", "field", "new", "old")} for c in res["changes"]],
            "new_temins": list(new_temins)}
    return client.post(f"/api/excel/{pid}/import/apply", headers=headers, json=body)


@pytest.fixture(scope="module")
def pid(client):
    return _project(client, "compare")


def test_words_mean_progress():
    for word, want in (("Üretildi", PROG_DONE), ("BİTTİ", PROG_DONE), ("Sipariş Teslim Edildi", PROG_DONE), ("✓", PROG_DONE),
                       ("100%", PROG_DONE), ("Sipariş verildi", PROG_RUN), ("Üretimde", PROG_RUN), ("%40", PROG_RUN),
                       ("Sipariş verilmedi", PROG_WAIT), ("Sipariş verilecek", PROG_WAIT), ("Üretilmedi", PROG_WAIT),
                       ("0%", PROG_WAIT), ("Teslim edilmedi", PROG_WAIT)):
        assert cp.read_progress(word) == want, word
    assert cp.read_progress("Mavi kutuda") is None


def test_words_mean_temin():
    choices = [t["name"] for t in DEFAULT_TEMIN_TYPES]
    for word, want in (("lazer", "Lazer Kesim"), ("LAZER KESİM", "Lazer Kesim"), ("abkant", "Büküm"), ("CNC", "Talaşlı İmalat"),
                       ("satın alma", "Hazır Alım"), ("kaynak", "Kaynak"), ("Su Jeti", "Su Jeti")):
        assert cp.read_temin(word, choices) == want, word


def test_defaults_have_the_production_steps():
    names = {t["name"]: t for t in DEFAULT_TEMIN_TYPES}
    for n in ("Lazer Kesim", "Büküm", "Kaynak", "Talaşlı İmalat", "Montaj"):
        assert names[n]["kind"] == "İmalat" and names[n]["drawing"]


def test_any_workbook_is_compared_and_applied(client, admin_headers, pid):
    a, b, c, d = (p["part_no"] for p in _parts(pid)[:4])
    data = _book([["Haftalık üretim raporu"], [],
                  ["Sıra", "Kod", "Üretim Durumu", "Sipariş Durumu", "Temin Şekli", "Açıklama"],
                  [1, a, "Üretildi", None, "Lazer", "Excel notu"],
                  [2, f" {b.lower()}.SLDPRT ", "Mavi kutuda", None, "Su Jeti", None],
                  [3, c, None, "Sipariş verildi", "Hazır Alım", None],
                  [4, "YOK-999", "Bitti", None, None, None]])
    res = _compare(client, admin_headers, pid, data)
    assert res["mode"] == "any" and res["matched"] == 3
    lay = res["layouts"][0]
    assert lay["header"] == 3 and lay["cols"] == {"part_no": 2, "status": 3, "order": 4, "temin": 5, "note": 6}
    assert [u["part_no"] for u in res["unknown"]] == ["YOK-999"]
    assert res["unresolved"] == [{"value": "Mavi kutuda", "count": 1}]
    assert [t["name"] for t in res["new_temins"]] == ["Su Jeti"]
    assert any(p["part_no"] == d for p in res["not_in_file"])
    got = {(x["key"], x["field"]): x["new"] for x in res["changes"]}
    assert got[(a, "progress")] == PROG_DONE and got[(a, "procurement_override")] == "Lazer Kesim"
    assert got[(a, "note")] == "Excel notu"
    assert got[(b, "procurement_override")] == "Su Jeti"
    assert got[(c, "procurement_override")] == "Hazır Alım" and got[(c, "progress")] == PROG_RUN

    # the user tells what the unknown word means and leaves nothing out
    res = _compare(client, admin_headers, pid, data, config={"values": {"progress": {"Mavi kutuda": PROG_RUN}}})
    assert res["unresolved"] == []
    assert any(x["key"] == b and x["field"] == "progress" and x["new"] == PROG_RUN for x in res["changes"])

    r = _apply(client, admin_headers, pid, res, [{"name": "Su Jeti", "kind": "İmalat"}])
    assert r.status_code == 200 and not r.json()["skipped"], r.text
    db = _db()
    try:
        saved = db.scalar(select(Setting).where(Setting.key == "temin_types")).value
        assert any(t["name"] == "Su Jeti" and t["drawing"] for t in saved)
        view = ProjectView.load(db, db.get(Project, pid))
        rows = {p["part_no"]: p for p in view.parts(include_in_purchased=False)}
        assert rows[a]["procurement"] == "Lazer Kesim" and rows[a]["status"] == "Üretildi"
        assert rows[b]["procurement"] == "Su Jeti"
        assert rows[c]["status"] == "Sipariş Verildi"
    finally:
        db.close()
    assert _compare(client, admin_headers, pid, data, config={"values": {"progress": {"Mavi kutuda": PROG_RUN}}})["changes"] == []


def test_columns_are_found_by_their_values(client, admin_headers):
    pid = _project(client, "values")
    parts = [p["part_no"] for p in _parts(pid)[:4]]
    data = _book([["A", "B", "C"], *[[1, p, "Lazer Kesim"] for p in parts]], "Sayfa")
    res = _compare(client, admin_headers, pid, data)
    assert res["layouts"][0]["cols"] == {"part_no": 2, "temin": 3}
    assert len(res["changes"]) == 4


def test_only_real_columns_are_offered(tmp_path):
    path = tmp_path / "liste.xlsx"
    path.write_bytes(_book([["Kod", "Durum"], ["A", "bitti"]]))
    assert [len(row) for row in cp.read_tables(path)[0].rows] == [2, 2]


def test_user_corrects_the_columns(client, admin_headers, pid):
    part = _parts(pid)[-1]["part_no"]
    data = _book([["Parça No", "Durum", "Renk"], [part, "Tamamlandı", "Bekliyor"]])
    res = _compare(client, admin_headers, pid, data)
    assert any(x["field"] == "progress" and x["new"] == PROG_DONE for x in res["changes"])
    res = _compare(client, admin_headers, pid, data, config={"sheets": {"Liste": {"cols": {"part_no": 1, "status": 3}}}})
    assert not any(x["key"] == part for x in res["changes"])


def test_a_sheet_can_be_left_out(client, admin_headers, pid):
    part = _parts(pid)[-2]["part_no"]
    data = _book([["Parça No", "Durum"], [part, "Tamamlandı"]])
    res = _compare(client, admin_headers, pid, data, config={"sheets": {"Liste": {"use": False}}})
    assert res["changes"] == [] and res["rows"] == 0


def test_csv_and_blank_cells_keep_the_db_value(client, admin_headers, pid):
    part = _parts(pid)[-3]["part_no"]
    data = f"Parça No;Durum;Not\n{part};Tamamlandı;\n".encode("cp1254")
    res = _compare(client, admin_headers, pid, data, name="liste.csv")
    assert [x["field"] for x in res["changes"] if x["key"] == part] == ["progress"]


def test_old_xls_format():
    table = cp.read_tables(Path(__file__).parent / "data" / "old_format.xls")[0]
    assert table.name == "Eski" and table.at(2, 1) == "T01_1100_0001" and table.at(2, 2) == "Bitti"


def test_bad_files(client, admin_headers, pid):
    r = client.post(f"/api/excel/{pid}/compare", headers=admin_headers, files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 400
    r = client.post(f"/api/excel/{pid}/compare", headers=admin_headers, files={"file": ("a.xlsx", b"not a zip", XLSX)})
    assert r.status_code == 400
    r = client.post(f"/api/excel/{pid}/compare", headers=admin_headers, files={"file": ("a.xlsx", _book([["x"]]), XLSX)},
                    data={"config": "{broken"})
    assert r.status_code == 400


def test_own_export_keeps_the_exact_path(client, admin_headers, pid):
    r = client.get(f"/api/excel/{pid}/parca-takip", headers=admin_headers)
    res = _compare(client, admin_headers, pid, r.content)
    assert res["mode"] == "export" and res["changes"] == []


def test_connection_needs_login_and_lists_the_server(client, admin_headers):
    assert client.get("/api/connection").status_code == 401
    body = client.get("/api/connection", headers=admin_headers).json()
    assert set(body) == {"ips", "hostname"}
