"""Montaj föyü: the T01 acceptance case from the spec, the seven checks, and the field round trip."""
from __future__ import annotations

import json
import uuid
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from app.core import assembly as core
from app.services import assembly_pdf

DATA = Path(__file__).parent / "data" / "assembly"
ORDER = {"T01_0010_0000": 2, "T01_0020_0000": 1, "T01_0030_0000": 2, "T01_0040_0000": 1, "T01_0050_0000": 2,
         "T01_0060_0000": 2, "T01_0070_0000": 1, "T01_0080_0000": 2, "T01_0600_0000": 2, "T01_0000_0009": 2}
HEADER = "Level;Dosya Adı;Reference Count;Malzeme;Ağırlık;Revizyon;TeminSekli;Kaplama Bilgisi"


def root_bom() -> bytes:
    """The ten sub-BOMs put under one synthetic root, each at the count the plan uses."""
    lines = [HEADER, "1;T01_0000_0000.SLDASM;1;;;A;Montaj;"]
    for i, (part, qty) in enumerate(ORDER.items(), 1):
        ext = "SLDPRT" if part.endswith("0009") else "SLDASM"
        text = (DATA / f"{part}.{ext}.1.BOM.csv").read_text(encoding="utf-8-sig")
        for j, row in enumerate(x for x in text.splitlines()[1:] if x.strip()):
            cells = row.split(";")
            cells[0] = f"1.{i}" + cells[0][1:]
            cells[1] = "  " + cells[1]
            if j == 0:
                cells[2] = str(qty)
            lines.append(";".join(cells))
    return ("\n".join(lines) + "\n").encode("utf-8-sig")


def make_project(client, headers) -> int:
    from app import models
    from app.db import SessionLocal
    from app.services import bomimport
    pid = client.post("/api/projects", json={"name": f"T01 {uuid.uuid4().hex[:8]}"}, headers=headers).json()["id"]
    with SessionLocal() as db:
        project = db.get(models.Project, pid)
        project.root_part_no = "T01_0000_0000"
        v = bomimport.upload_bom(db, project, "BOM_T01_0000_0000.csv", root_bom(), None)
        bomimport.approve(db, v, None)
        db.commit()
    return pid


def make_plan(client, headers, pid, items=None, publish=True, mode="none") -> int:
    items = items or [{"part_no": k, "qty": v} for k, v in ORDER.items()]
    r = client.post(f"/api/projects/{pid}/assembly/plans", headers=headers,
                    json={"plan_date": "2026-11-07", "responsible": "A", "drawing_mode": mode, "items": items})
    assert r.status_code == 200, r.text
    plan = r.json()["id"]
    if publish:
        assert client.post(f"/api/projects/{pid}/assembly/plans/{plan}/status", json={"status": "Yayınlandı"}, headers=headers).status_code == 200
    return plan


def get(client, headers, pid, plan):
    r = client.get(f"/api/projects/{pid}/assembly/plans/{plan}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def t01(client, admin_headers):
    pid = make_project(client, admin_headers)
    return pid, make_plan(client, admin_headers, pid)


def set_reference(client, headers, pid, plan):
    """The extras and ready quantities of the hand-made reference workbook."""
    for part in ("T01_0600_0002", "T01_0600_0003", "T01_0600_0004"):
        r = client.post(f"/api/projects/{pid}/assembly/plans/{plan}/extras", headers=headers,
                        json={"part_no": part, "qty": 2, "assembly_no": "T01_0600_0000"})
        assert r.status_code == 200, r.text
    ref = json.loads((DATA / "reference_pick.json").read_text())
    items = [{"part_no": k, "ready_qty": v[1]} for k, v in ref.items() if v[1]]
    r = client.post(f"/api/projects/{pid}/assembly/quantities", json={"items": items}, headers=headers)
    assert r.status_code == 200, r.text
    return ref


def pick(doc, part):
    return next(p for p in doc["picks"] if p["part_no"] == part)


def foy(doc, part):
    return next(f for f in doc["foys"] if f["part_no"] == part)


def test_acceptance_counts(client, admin_headers, t01):
    pid, plan = t01
    d = get(client, admin_headers, pid, plan)
    assert [f["part_no"] for f in d["foys"]] == list(ORDER)
    assert [f["qty"] for f in d["foys"]] == list(ORDER.values())
    assert d["plan_total"] == 163
    assert len(d["picks"]) == 47
    p = pick(d, "T01_0600_0001")
    assert p["need"] == 20
    assert p["uses"] == "T01_0070_0000 (4), T01_0080_0000 (4), T01_0600_0000 (4)"
    assert pick(d, "T01_0051_0002")["need"] == 8
    steps = foy(d, "T01_0050_0000")["steps"]
    assert [s["part_no"] for s in steps] == ["T01_0051_0011", "T01_0051_0000", "T01_0050_0000"]
    assert steps[0]["make"] == 4


def test_nested_parts_counted_once(client, admin_headers, t01):
    pid, plan = t01
    d = get(client, admin_headers, pid, plan)
    rows = [r for s in foy(d, "T01_0050_0000")["steps"] for r in s["rows"] if r["part_no"] in ("T01_0051_0012", "T01_0051_0013")]
    assert sum(r["need"] for r in rows) == pick(d, "T01_0051_0012")["need"] + pick(d, "T01_0051_0013")["need"]


def test_reference_status(client, admin_headers, t01):
    pid, plan = t01
    ref = set_reference(client, admin_headers, pid, plan)
    d = get(client, admin_headers, pid, plan)
    assert {p["part_no"]: [p["need"], p["ready"]] for p in d["picks"]} == ref
    assert (d["pick_total"], sum(p["ready"] for p in d["picks"])) == (169, 61)
    assert sum(p["need"] - p["ready"] for p in d["picks"]) == 108
    s = client.get(f"/api/projects/{pid}/assembly/summary", headers=admin_headers).json()
    assert sorted(x["part_no"] for x in s["ready"]) == ["T01_0070_0000", "T01_0600_0000"]


def test_extra_does_not_block_ready(client, admin_headers, t01):
    pid, plan = t01
    set_reference(client, admin_headers, pid, plan)
    d = get(client, admin_headers, pid, plan)
    assert pick(d, "T01_0600_0002")["need"] == 4
    assert foy(d, "T01_0600_0000")["ready"]
    assert "+2" in foy(d, "T01_0600_0000")["extra_note"]


def test_earlier_plan_reserves_first(client, admin_headers):
    pid = make_project(client, admin_headers)
    a = make_plan(client, admin_headers, pid, [{"part_no": "T01_0600_0000", "qty": 1}])
    b = make_plan(client, admin_headers, pid, [{"part_no": "T01_0600_0000", "qty": 1}])
    part = "T01_0600_0001"
    per_one = pick(get(client, admin_headers, pid, a), part)["need"]
    client.post(f"/api/projects/{pid}/assembly/quantities", json={"items": [{"part_no": part, "ready_qty": per_one}]}, headers=admin_headers)
    assert pick(get(client, admin_headers, pid, a), part)["ready"] == per_one
    assert pick(get(client, admin_headers, pid, b), part)["ready"] == 0


def excel(client, headers, pid, plan):
    r = client.get(f"/api/projects/{pid}/assembly/plans/{plan}/excel", headers=headers)
    assert r.status_code == 200, r.text
    return r.content


def preview(client, headers, pid, plan, data):
    r = client.post(f"/api/projects/{pid}/assembly/plans/{plan}/return/preview", headers=headers,
                    files={"file": ("foy.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    return r.json()


def codes(p):
    return {i["code"] for i in p["issues"]}


def test_excel_layout(client, admin_headers, t01):
    pid, plan = t01
    wb = load_workbook(BytesIO(excel(client, admin_headers, pid, plan)))
    assert len(wb.worksheets) == 3
    assert wb.worksheets[0]["A1"].value == "GÜNLÜK MONTAJ PLANI"
    fy = wb.worksheets[2]
    texts = [c.value for row in fy.iter_rows() for c in row if isinstance(c.value, str)]
    assert any(t.startswith("=") and "Yapılacak:" in t for t in texts)
    assert len(fy.row_breaks.brk) == 8


def test_clean_return_has_no_changes(client, admin_headers, t01):
    pid, plan = t01
    p = preview(client, admin_headers, pid, plan, excel(client, admin_headers, pid, plan))
    assert p["changes"] == []
    assert [i for i in p["issues"] if i["severity"] == core.ERROR] == []


def edit(data: bytes, fn) -> bytes:
    wb = load_workbook(BytesIO(data))
    fn(wb)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def row_of(ws, part, col):
    return next(r for r in range(1, ws.max_row + 1) if ws.cell(r, col).value == f"R|{part}")


def run(client, headers, pid, plan, fn):
    return preview(client, headers, pid, plan, edit(excel(client, headers, pid, plan), fn))


def set_pick(wb, part, need=None, ready=None, short=None, status=None, uses=None):
    ws = wb.worksheets[1]
    r = row_of(ws, part, 12)
    for col, v in ((7, need), (8, ready), (9, short), (11, status), (6, uses)):
        if v is not None:
            ws.cell(r, col).value = v


def set_box(wb, part, foy_part, col):
    ws = wb.worksheets[2]
    inside = False
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, 1).value == foy_part:
            inside = True
        elif inside and ws.cell(r, 14).value == f"R|{part}":
            for c in (8, 9, 10):
                ws.cell(r, c).value = "☐"
            ws.cell(r, col).value = "☒"
            return
    raise AssertionError(part)


def test_check_1_short_arithmetic(client, admin_headers, t01):
    p = run(client, admin_headers, *t01, lambda wb: set_pick(wb, "T01_0051_0002", 8, 3, 1))
    assert 1 in codes(p)


def test_check_2_places_disagree(client, admin_headers, t01):
    def fn(wb):
        set_pick(wb, "T01_0600_0001", 20, 4, 16)
        set_box(wb, "T01_0600_0001", "T01_0070_0000", 8)
        set_box(wb, "T01_0600_0001", "T01_0080_0000", 8)
    assert 2 in codes(run(client, admin_headers, *t01, fn))


def test_check_3_all_ready_but_missing_on_sheet(client, admin_headers, t01):
    p = run(client, admin_headers, *t01, lambda wb: set_pick(wb, "T01_0600_0001", 20, 20, 0))
    assert 3 in codes(p)


def test_check_4_extra_on_wrong_part(client, admin_headers):
    pid = make_project(client, admin_headers)
    plan = make_plan(client, admin_headers, pid, [{"part_no": "T01_0600_0000", "qty": 1}])
    url = f"/api/projects/{pid}/assembly/plans/{plan}/extras"
    e = client.post(url, json={"part_no": "T01_0020_0001", "qty": 2}, headers=admin_headers).json()["id"]
    assert any(i["code"] == 4 and i.get("extra_id") == e for i in get(client, admin_headers, pid, plan)["issues"])
    assert client.put(f"{url}/{e}", json={"part_no": "T01_0600_0001", "qty": 2}, headers=admin_headers).status_code == 200
    d = get(client, admin_headers, pid, plan)
    assert not any(i["code"] == 4 for i in d["issues"])
    assert pick(d, "T01_0600_0001")["extra"] == 2


def test_check_5_need_changed_by_hand_can_become_extra(client, admin_headers, t01):
    pid, plan = t01
    p = run(client, admin_headers, pid, plan, lambda wb: set_pick(wb, "T01_0051_0002", 10, 0, 10))
    issue = next(i for i in p["issues"] if i.get("action"))
    assert issue["code"] == 5 and issue["action"] == {"type": "extra", "part_no": "T01_0051_0002", "qty": 2}
    r = client.post(f"/api/projects/{pid}/assembly/plans/{plan}/return/apply", json={"changes": [issue["action"]]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert pick(get(client, admin_headers, pid, plan), "T01_0051_0002")["need"] == 10


def test_check_5_need_below_bom_is_an_error(client, admin_headers, t01):
    p = run(client, admin_headers, *t01, lambda wb: set_pick(wb, "T01_0051_0002", 4, 0, 4))
    assert any(i["code"] == 5 and i["severity"] == core.ERROR for i in p["issues"])


def test_check_6_status_text_and_boxes(client, admin_headers, t01):
    p = run(client, admin_headers, *t01, lambda wb: set_pick(wb, "T01_0051_0002", 8, 8, 0, "Sipariş Verilmedi"))
    assert 6 in codes(p)

    def fn(wb):
        ws = wb.worksheets[2]
        r = row_of(ws, "T01_0600_0001", 14)
        ws.cell(r, 8).value = ws.cell(r, 10).value = "☒"
    assert 6 in codes(run(client, admin_headers, *t01, fn))


def test_check_7_totals(client, admin_headers, t01):
    pid, plan = t01
    client.post(f"/api/projects/{pid}/assembly/plans/{plan}/extras", json={"part_no": "T01_0600_0002", "qty": 2}, headers=admin_headers)
    p = preview(client, admin_headers, pid, plan, excel(client, admin_headers, pid, plan))
    assert [i["severity"] for i in p["issues"] if i["code"] == 7] == [core.INFO]

    def fn(wb):
        ws = wb.worksheets[0]
        r = next(x for x in range(1, ws.max_row + 1) if str(ws.cell(x, 13).value).startswith("I|"))
        ws.cell(r, 6).value = 1
    p = run(client, admin_headers, pid, plan, fn)
    assert [i["severity"] for i in p["issues"] if i["code"] == 7] == [core.ERROR]


def test_wrong_plan_refused(client, admin_headers, t01):
    pid, plan = t01
    other = make_plan(client, admin_headers, pid, [{"part_no": "T01_0020_0000", "qty": 1}])
    r = client.post(f"/api/projects/{pid}/assembly/plans/{other}/return/preview", headers=admin_headers,
                    files={"file": ("foy.xlsx", excel(client, admin_headers, pid, plan))})
    assert r.status_code == 400


def test_return_apply_updates_status_and_audit(client, admin_headers, t01):
    pid, plan = t01

    def fn(wb):
        ws = wb.worksheets[2]
        r = row_of(ws, "T01_0600_0001", 14)
        ws.cell(r, 8).value, ws.cell(r, 10).value = "☒", "☐"
    p = preview(client, admin_headers, pid, plan, edit(excel(client, admin_headers, pid, plan), fn))
    assert p["changes"], p
    r = client.post(f"/api/projects/{pid}/assembly/plans/{plan}/return/apply", json={"changes": p["changes"]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    d = get(client, admin_headers, pid, plan)
    assert pick(d, "T01_0600_0001")["ready"] > 0
    h = client.get(f"/api/projects/{pid}/assembly/plans/{plan}/history", headers=admin_headers).json()["rows"]
    assert any("Excel" in (x["new"] or "") and f"plan {d['no']}" in x["new"] for x in h)


def test_field_box_and_tick(client, admin_headers, t01):
    pid, plan = t01
    d = get(client, admin_headers, pid, plan)
    step = foy(d, "T01_0020_0000")["steps"][0]
    ops = [{"item_id": foy(d, "T01_0020_0000")["item_id"], "path": step["path"], "part_no": r["part_no"], "state": "ready"} for r in step["rows"]]
    r = client.post(f"/api/projects/{pid}/assembly/plans/{plan}/field", json={"ops": ops}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert foy(get(client, admin_headers, pid, plan), "T01_0020_0000")["ready"]
    ops = [{**o, "state": None, "mounted": True} for o in ops]
    steps = [{"item_id": ops[0]["item_id"], "path": step["path"], "done": True}]
    r = client.post(f"/api/projects/{pid}/assembly/plans/{plan}/field", json={"ops": ops, "steps": steps}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert foy(get(client, admin_headers, pid, plan), "T01_0020_0000")["done"]


def test_pdf_black_and_white(client, admin_headers, t01):
    pid, plan = t01
    r = client.get(f"/api/projects/{pid}/assembly/plans/{plan}/pdf", headers=admin_headers)
    assert r.status_code == 200, r.text
    reader = PdfReader(BytesIO(r.content))
    pages = [p.extract_text() for p in reader.pages]
    assert sum("MONTAJ FÖYÜ" in t and "T01_" in t and "devam" not in t for t in pages) >= 9
    assert all(f"Sayfa {i} / {len(pages)}" in t for i, t in enumerate(pages, 1))
    assert all("T01 – Günlük Montaj" in t for t in pages)
    assert "☐" in "".join(pages)
    fonts = {str(f) for p in reader.pages for f in (p["/Resources"].get("/Font") or {}).values()}
    assert fonts
    doc = pdfium.PdfDocument(r.content)
    for i in range(len(doc)):
        img = doc[i].render(scale=1).to_pil().convert("HSV")
        assert sum(img.split()[1].histogram()[16:]) == 0


def test_single_foy_pdf(client, admin_headers, t01):
    pid, plan = t01
    r = client.get(f"/api/projects/{pid}/assembly/plans/{plan}/pdf", params={"foy": "T01_0050_0000"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    text = "".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
    assert "T01_0050_0000" in text and "T01_0060_0000" not in text


def test_permissions_and_draft_rules(client, admin_headers):
    from tests.test_api_photos_chat import _user
    pid = make_project(client, admin_headers)
    plan = make_plan(client, admin_headers, pid, [{"part_no": "T01_0020_0000", "qty": 1}], publish=False)
    r = client.post(f"/api/projects/{pid}/assembly/plans/{plan}/field", json={}, headers=admin_headers)
    assert r.status_code == 409
    _, viewer = _user(client, admin_headers, role="viewer")
    assert client.get(f"/api/projects/{pid}/assembly/plans", headers=viewer).status_code in (200, 403)
    assert client.delete(f"/api/projects/{pid}/assembly/plans/{plan}", headers=viewer).status_code == 403
    assert client.delete(f"/api/projects/{pid}/assembly/plans/{plan}", headers=admin_headers).status_code == 200


def test_ready_notification_names_part_and_assemblies(client, admin_headers, t01):
    pid, plan = t01
    d = get(client, admin_headers, pid, plan)
    parts = [r["part_no"] for s in foy(d, "T01_0020_0000")["steps"] for r in s["rows"]]
    need = {p: pick(d, p)["need"] for p in parts}
    items = [{"part_no": k, "ready_qty": v} for k, v in need.items()]
    assert client.post(f"/api/projects/{pid}/assembly/quantities", json={"items": items}, headers=admin_headers).status_code == 200
    rows = client.get("/api/notifications", headers=admin_headers).json()["items"]
    hit = [x for x in rows if x["key"].startswith(f"assembly:{pid}:")]
    assert hit and "T01_0020" in hit[0]["detail"] and "montaja hazır" in hit[0]["detail"]
    assert hit[0]["link"] == f"/p/{pid}/assembly/{plan}"


def test_drawing_pages_are_added_and_stamped(client, admin_headers, t01, tmp_path):
    from reportlab.lib.colors import red
    from reportlab.pdfgen.canvas import Canvas
    from app import models
    from app.db import SessionLocal
    pid, plan = t01
    part = "T01_0600_0002"
    f = tmp_path / "d.pdf"
    c = Canvas(str(f))
    c.setFillColor(red)
    c.rect(100, 100, 300, 300, fill=1)
    c.save()
    with SessionLocal() as db:
        d = models.Drawing(project_id=pid, part_no=part, filename="d.pdf", filename_key=f"d{pid}.pdf", base_name="d", ext="pdf", rev="A", current_version=1)
        d.versions.append(models.DrawingVersion(version_no=1, storage_path=str(f), size=f.stat().st_size, sha256="0" * 64))
        db.add(d)
        db.get(models.AssemblyPlan, plan).drawing_mode = "both"
        db.commit()
    r = client.get(f"/api/projects/{pid}/assembly/plans/{plan}/pdf", headers=admin_headers)
    assert r.status_code == 200, r.text
    doc = pdfium.PdfDocument(r.content)
    pages = [p.extract_text() for p in PdfReader(BytesIO(r.content)).pages]
    assert sum(f"· {part}" in t for t in pages) >= 1
    for i in range(len(doc)):
        assert sum(doc[i].render(scale=0.5).to_pil().convert("HSV").split()[1].histogram()[16:]) == 0


def drawing(client_pid, part, tmp_path):
    from reportlab.pdfgen.canvas import Canvas
    from app import models
    from app.db import SessionLocal
    f = tmp_path / f"{part}.pdf"
    c = Canvas(str(f))
    c.drawString(100, 100, "front")
    c.showPage()
    c.drawString(100, 100, "second")
    c.save()
    with SessionLocal() as db:
        d = models.Drawing(project_id=client_pid, part_no=part, filename=f"{part}.pdf", filename_key=f"{part}{client_pid}.pdf", base_name=part, ext="pdf", rev="A")
        d.versions.append(models.DrawingVersion(version_no=1, storage_path=str(f), size=f.stat().st_size, sha256="0" * 64))
        db.add(d)
        db.commit()


def mark(client, headers, code, apply=False):
    return client.post("/api/scan/mark" + ("/apply" if apply else ""), json={"payload": f"http://10.0.0.5:8000/q/{code}"}, headers=headers)


def set_plan_mode(plan, mode):
    from app import models
    from app.db import SessionLocal
    with SessionLocal() as db:
        db.get(models.AssemblyPlan, plan).drawing_mode = mode
        db.commit()


def test_qr_lands_on_the_back_of_every_drawing_page(client, admin_headers, t01, tmp_path):
    pid, plan = t01
    part = "T01_0600_0003"
    drawing(pid, part, tmp_path)
    set_plan_mode(plan, "pages")
    r = client.get(f"/api/projects/{pid}/assembly/plans/{plan}/pdf", headers=admin_headers)
    assert r.status_code == 200, r.text
    reader = PdfReader(BytesIO(r.content))
    pages = [p.extract_text() for p in reader.pages]
    assert len(pages) % 2 == 0
    fronts = [i for i, t in enumerate(pages) if f"· {part}" in t]
    assert len(fronts) == 2
    for i in fronts:
        assert i % 2 == 0 and "Bitince okutun: Üretildi" in pages[i + 1] and part in pages[i + 1]
    assert all(i % 2 == 0 for i, t in enumerate(pages) if t.startswith("MONTAJ FÖYÜ\n"))
    assert all(i % 2 == 1 for i, t in enumerate(pages) if "Okutunca" in t)
    assert reader.trailer["/Root"]["/ViewerPreferences"]["/Duplex"] == "/DuplexFlipLongEdge"


def test_part_qr_books_only_after_confirmation(client, admin_headers, t01):
    pid, plan = t01
    part = "T01_0600_0002"
    r = mark(client, admin_headers, f"A{plan}-{part}")
    assert r.status_code == 200, r.text
    m = r.json()
    assert (m["action"], m["done"], m["blocked"]) == ("Üretildi", False, "") and m["left"] > 0
    assert pick(get(client, admin_headers, pid, plan), part)["ready"] == 0
    assert mark(client, admin_headers, f"A{plan}-{part}", True).status_code == 200
    d = get(client, admin_headers, pid, plan)
    assert pick(d, part)["short"] == 0
    assert mark(client, admin_headers, f"A{plan}-{part}").json()["done"] is True
    before = pick(d, part)["ready"]
    assert mark(client, admin_headers, f"A{plan}-{part}", True).status_code == 200
    assert pick(get(client, admin_headers, pid, plan), part)["ready"] == before


def test_bought_part_qr_says_arrived(client, admin_headers, t01):
    pid, plan = t01
    bought = next(p for p in get(client, admin_headers, pid, plan)["picks"] if p["temin"] == "Hazır Alım")
    assert mark(client, admin_headers, f"A{plan}-{bought['part_no']}").json()["action"] == "Geldi"


def test_step_qr_marks_the_assembly_done(client, admin_headers, t01):
    pid, plan = t01
    f = foy(get(client, admin_headers, pid, plan), "T01_0600_0000")
    code = f"S{plan}-{f['item_id']}-1"
    m = mark(client, admin_headers, code).json()
    assert m["kind"] == "step" and m["action"] == "Montaj tamam" and m["rows"] and m["warnings"]
    assert mark(client, admin_headers, code, True).status_code == 200
    assert mark(client, admin_headers, code).json()["done"] is True


def test_qr_needs_rights_and_a_published_plan(client, admin_headers):
    pid = make_project(client, admin_headers)
    r = client.post(f"/api/projects/{pid}/assembly/plans", headers=admin_headers,
                    json={"plan_date": "2026-11-07", "items": [{"part_no": "T01_0600_0000", "qty": 2}]})
    assert r.status_code == 200, r.text
    plan = r.json()["id"]
    assert mark(client, admin_headers, f"A{plan}-T01_0600_0002").json()["blocked"]
    assert mark(client, admin_headers, f"A{plan}-T01_0600_0002", True).status_code == 409
    assert mark(client, admin_headers, f"A{plan}-NOPE").status_code == 404
    assert mark(client, {}, f"A{plan}-T01_0600_0002", True).status_code == 401


def test_project_drawing_print_has_qr_backs_and_part_code_books_bom_total(client, admin_headers, t01, tmp_path):
    pid, plan = t01
    part = "T01_0600_0004"
    drawing(pid, part, tmp_path)
    r = client.post(f"/api/projects/{pid}/drawings/print", json={"part_nos": [part]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    pages = [p.extract_text() for p in PdfReader(BytesIO(r.content)).pages]
    assert len(pages) == 4 and "front" in pages[0] and "Bitince okutun" in pages[1] and "second" in pages[2] and "Bitince okutun" in pages[3]
    m = mark(client, admin_headers, f"P{pid}-{part}").json()
    assert m["drawing"]["filename"] == f"{part}.pdf"
    assert mark(client, admin_headers, f"P{pid}-{part}", True).status_code == 200
    assert mark(client, admin_headers, f"P{pid}-{part}").json()["done"] is True
    r = client.post(f"/api/projects/{pid}/drawings/print", json={"part_nos": ["T01_0010_0001"]}, headers=admin_headers)
    assert r.status_code == 404


def test_second_read_adds_nothing_when_an_earlier_plan_took_the_parts(client, admin_headers):
    pid = make_project(client, admin_headers)
    items = [{"part_no": "T01_0600_0000", "qty": 2}]
    make_plan(client, admin_headers, pid, items)
    later = make_plan(client, admin_headers, pid, items)
    part = "T01_0600_0002"
    code = f"A{later}-{part}"
    left = mark(client, admin_headers, code).json()["left"]
    assert mark(client, admin_headers, code, True).status_code == 200
    assert mark(client, admin_headers, code).json()["done"] is True
    assert mark(client, admin_headers, code, True).status_code == 200
    rows = client.get(f"/api/projects/{pid}/assembly/quantities", headers=admin_headers).json()
    rows = rows["rows"] if isinstance(rows, dict) else rows
    assert next(r for r in rows if r["part_no"] == part)["ready"] == left


def test_single_sided_plan_has_no_qr_pages_and_leaves_duplex_off(client, admin_headers, t01, tmp_path):
    pid, plan = t01
    part = "T01_0600_0003"
    drawing(pid, part, tmp_path)
    set_plan_mode(plan, "pages")
    r = client.get(f"/api/projects/{pid}/assembly/plans/{plan}/pdf?qr=none", headers=admin_headers)
    assert r.status_code == 200, r.text
    reader = PdfReader(BytesIO(r.content))
    pages = [p.extract_text() for p in reader.pages]
    assert sum(f"· {part}" in t for t in pages) == 2
    assert not any("Okutunca" in t for t in pages) and all(t.strip() for t in pages)
    assert "/ViewerPreferences" not in reader.trailer["/Root"]


def test_plan_codes_come_as_labels_and_as_a_list(client, admin_headers, t01):
    pid, plan = t01
    base = f"/api/projects/{pid}/assembly/plans/{plan}/codes"
    labels = client.get(base, headers=admin_headers)
    assert labels.status_code == 200, labels.text
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(labels.content)).pages)
    assert "T01_0600_0002" in text and "Montaj tamam" in text and "ADIM" in text
    assert text.count("T01_0600_0002\n") == 1
    listed = client.get(f"{base}?layout=list", headers=admin_headers)
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(listed.content)).pages)
    assert "T01_0600_0002" in text and "Montaj tamam" in text
    assert client.get(f"{base}?foy=NOPE", headers=admin_headers).status_code == 404
    assert client.get(base).status_code == 401


def test_labels_fill_a_sheet_of_24_and_go_on_to_the_next(client, admin_headers, t01):
    pid, _ = t01
    code = assembly_pdf.Code("http://x/q/P1-A", "A", "name", "Üretildi", 2, "proj")
    assert len(PdfReader(BytesIO(assembly_pdf.labels("t", [code] * 24))).pages) == 1
    assert len(PdfReader(BytesIO(assembly_pdf.labels("t", [code] * 25))).pages) == 2
    long = assembly_pdf.Code("http://x/q/P1-A", "X" * 90, "n" * 200, "Montaj tamam", 2, "p" * 200)
    assert len(PdfReader(BytesIO(assembly_pdf.labels("t", [long]))).pages) == 1


def test_project_codes_cover_parts_without_a_pdf_drawing(client, admin_headers, t01):
    pid, _ = t01
    part = "T01_0010_0001"
    url = f"/api/projects/{pid}/drawings/codes"
    assert client.post(f"/api/projects/{pid}/drawings/print", json={"part_nos": [part]}, headers=admin_headers).status_code == 404
    for layout in ("labels", "list"):
        r = client.post(url, json={"part_nos": [part, "NOPE"], "layout": layout}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert part in PdfReader(BytesIO(r.content)).pages[0].extract_text()
    assert client.post(url, json={"part_nos": ["NOPE"]}, headers=admin_headers).status_code == 404
