from datetime import date, datetime, timedelta

from app.core.attendance import default_break, is_forgotten, weekly_overtime, worked_hours
from test_api_commerce import _login


def _worker(client, admin_headers, name):
    h, uid = _login(client, admin_headers, "viewer")
    e = client.post("/api/employees", headers=admin_headers, json={"name": name, "user_id": uid}).json()
    return h, e["id"]


def _days_back(n):
    return (date.today() - timedelta(days=n)).isoformat()


def test_overtime_goes_to_the_shift_that_crossed_the_week_limit():
    mon = date(2026, 11, 2)
    shifts = [(i + 1, mon + timedelta(days=i), 10.0) for i in range(6)]
    got = weekly_overtime(shifts, 45)
    assert [got[i] for i in range(1, 7)] == [0, 0, 0, 0, 5, 10]
    assert weekly_overtime([(1, mon, 50.0), (2, mon + timedelta(days=7), 10.0)], 45) == {1: 5, 2: 0}


def test_shift_arithmetic():
    a = datetime(2026, 11, 2, 8, 0)
    assert worked_hours(a, a + timedelta(hours=9), 60) == 8
    assert worked_hours(a, None, 60) == 0
    assert default_break(a, a + timedelta(hours=9), 60) == 60
    assert default_break(a, a + timedelta(hours=3), 60) == 0
    assert is_forgotten(a, None, a + timedelta(hours=17))
    assert not is_forgotten(a, None, a + timedelta(hours=9))


def test_worker_stamps_and_sees_only_own_shifts(client, admin_headers):
    h1, e1 = _worker(client, admin_headers, "Ayşe Mesai")
    h2, e2 = _worker(client, admin_headers, "Veli Mesai")
    assert client.post("/api/attendance/clock-out", headers=h1, json={}).status_code == 409
    assert client.post("/api/attendance/clock-in", headers=h1, json={}).status_code == 201
    assert client.post("/api/attendance/clock-in", headers=h1, json={}).status_code == 409
    me = client.get("/api/attendance/me", headers=h1).json()
    assert me["open"] and {r["employee_id"] for r in me["rows"]} == {e1}
    assert client.get("/api/attendance/me", headers=h2).json()["rows"] == []
    assert client.post("/api/attendance/clock-out", headers=h1, json={}).status_code == 200
    assert client.get("/api/attendance/me", headers=h1).json()["open"] is None

    # A worker reaches nobody else's records, and cannot change even their own
    assert client.get("/api/attendance", headers=h1).status_code == 403
    assert client.get(f"/api/attendance?employee_id={e2}", headers=h1).status_code == 403
    sid = me["rows"][0]["id"]
    body = {"work_date": _days_back(0), "start": "08:00", "end": "09:00"}
    assert client.put(f"/api/attendance/{sid}", headers=h1, json=body).status_code == 403
    assert client.delete(f"/api/attendance/{sid}", headers=h1).status_code == 403
    assert client.post("/api/attendance", headers=h1, json={**body, "employee_id": e1}).status_code == 403


def test_no_card_cannot_stamp(client, admin_headers):
    h, _ = _login(client, admin_headers, "viewer")
    assert client.get("/api/attendance/me", headers=h).json()["employee"] is None
    assert client.post("/api/attendance/clock-in", headers=h, json={}).status_code == 400


def test_view_right_sees_everyone_but_cannot_correct(client, admin_headers):
    h, uid = _login(client, admin_headers, "viewer")
    r = client.put(f"/api/admin/users/{uid}", headers=admin_headers, json={"permissions": {"attendance": "view"}})
    assert r.status_code == 200, r.text
    assert client.get("/api/attendance", headers=h).status_code == 200
    assert client.get("/api/employees", headers=h).status_code == 403   # shifts do not open the wages
    assert client.delete("/api/attendance/999999", headers=h).status_code == 403


def test_manager_corrects_and_rules_hold(client, admin_headers):
    h = admin_headers
    e = client.post("/api/employees", headers=h, json={"name": "Düzeltme Mesai"}).json()["id"]
    base = {"employee_id": e, "work_date": _days_back(3), "start": "08:00", "end": "17:00"}
    r = client.post("/api/attendance", headers=h, json=base)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    q = f"/api/attendance?date_from={_days_back(3)}&date_to={_days_back(3)}&employee_id={e}"
    row = client.get(q, headers=h).json()["rows"][0]
    assert (row["break_minutes"], row["hours"], row["status"]) == (60, 8, "done")

    assert client.post("/api/attendance", headers=h, json={**base, "start": "16:00", "end": "18:00"}).status_code == 409
    assert client.post("/api/attendance", headers=h, json={**base, "start": "08:00", "end": "08:00"}).status_code == 400
    future = (date.today() + timedelta(days=1)).isoformat()
    assert client.post("/api/attendance", headers=h, json={**base, "work_date": future}).status_code == 400
    assert client.post("/api/attendance", headers=h, json={**base, "work_date": _days_back(5), "start": "08:00",
                                                           "end": "09:00", "break_minutes": 60}).status_code == 400

    night = {"work_date": _days_back(3), "start": "22:00", "end": "06:00", "break_minutes": 0}
    assert client.put(f"/api/attendance/{sid}", headers=h, json=night).status_code == 200
    row = client.get(q, headers=h).json()["rows"][0]
    assert (row["hours"], row["next_day"], row["corrected_by"]) == (8, True, "admin")

    assert client.delete(f"/api/employees/{e}", headers=h).status_code == 400
    assert client.delete(f"/api/attendance/{sid}", headers=h).status_code == 200
    assert client.get(q, headers=h).json()["rows"] == []
