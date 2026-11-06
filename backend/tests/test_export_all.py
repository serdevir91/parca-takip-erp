"""Excel files made of what is on screen, and the whole database in one file."""
from io import BytesIO

from openpyxl import load_workbook

from tests.test_api_photos_chat import _user


def _book(client, headers, fid: str):
    r = client.get(f"/api/export/grid/{fid}", params={"name": "x"}, headers=headers)
    assert r.status_code == 200, r.text
    return load_workbook(BytesIO(r.content))


def test_book_keeps_one_sheet_per_table_and_never_runs_cells(client, admin_headers):
    sheets = [
        {"name": "Liste", "columns": ["A", "B"], "rows": [["=1+1", 5], ["00123", None]]},
        {"name": "Liste", "columns": ["A"], "rows": [["x"]]},
        {"name": "a/b*c?", "columns": ["A"], "rows": [["=HYPERLINK(\"http://evil\",\"y\")"]]},
    ]
    r = client.post("/api/export/book", json={"sheets": sheets}, headers=admin_headers)
    assert r.status_code == 200, r.text
    wb = _book(client, admin_headers, r.json()["id"])
    assert len(wb.sheetnames) == 3 and len(set(wb.sheetnames)) == 3
    first = wb.worksheets[0]
    assert first["A2"].value == "=1+1" and first["A3"].value == "00123" and first["B2"].value == 5
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f"


def test_book_needs_a_session(client):
    assert client.post("/api/export/book", json={"sheets": []}).status_code == 401


def test_everything_is_admin_only_and_leaves_secrets_out(client, admin_headers):
    _, other = _user(client, admin_headers)
    assert client.post("/api/export/all", headers=other).status_code == 403
    client.post("/api/projects", json={"name": "=cmd()", "root_part_no": "R"}, headers=admin_headers)
    r = client.post("/api/export/all", headers=admin_headers)
    assert r.status_code == 200, r.text
    wb = _book(client, admin_headers, r.json()["id"])
    assert "Projeler" in wb.sheetnames
    assert not {n.lower() for n in wb.sheetnames} & {"kullanıcılar", "ayarlar", "sohbet", "users", "settings"}
    for ws in wb.worksheets:
        head = [str(c.value).lower() for c in next(ws.iter_rows(max_row=1))]
        assert not [h for h in head if "password" in h or "secret" in h or "token" in h], ws.title
    projects = wb["Projeler"]
    cells = [c for row in projects.iter_rows() for c in row]
    assert all(c.data_type != "f" for c in cells)
    assert any(c.value == "=cmd()" for c in cells)
