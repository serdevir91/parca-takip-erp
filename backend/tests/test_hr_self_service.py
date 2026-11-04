"""Leave, shift correction requests and hours to jobs: the worker's own side and the manager's side."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.api import attendance as attendance_api
from app.api import leave as leave_api
from app.core.attendance import day_balance, working_days
from app.db import SessionLocal
from app.models import Attendance, AttendanceRequest, AuditLog, LeaveRequest, TimeEntry
from test_api_commerce import _login, _u

MON = date(2027, 3, 1)       # a Monday in a year of its own, so the balance tests need no clock


def _worker(client, admin_headers, **card):
    h, uid = _login(client, admin_headers, "viewer")
    e = client.post("/api/employees", headers=admin_headers, json={"name": _u("Personel"), "user_id": uid, **card}).json()
    return h, e["id"]


def _viewer_manager(client, admin_headers):
    return _login(client, admin_headers, "viewer", permissions={"attendance": "view"})[0]


def _ask(client, h, start, end, kind="annual"):
    return client.post("/api/leave/me", headers=h, json={"kind": kind, "start_date": str(start), "end_date": str(end)})


def _decide(client, admin_headers, rid, approve=True, note=""):
    return client.post(f"/api/leave/{rid}/decide", headers=admin_headers, json={"approve": approve, "note": note})


def _balance(client, h, year=MON.year):
    return client.get("/api/leave/me", headers=h, params={"year": year}).json()["balance"]


def _last_week_monday():
    today = date.today()
    return today - timedelta(days=today.weekday() + 7)


def _shift(client, admin_headers, emp, day, start="08:00", end="17:00", **extra):
    r = client.post("/api/attendance", headers=admin_headers,
                    json={"employee_id": emp, "work_date": str(day), "start": start, "end": end, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _report(client, admin_headers, emp, first, last):
    r = client.get("/api/attendance", headers=admin_headers,
                   params={"date_from": str(first), "date_to": str(last), "employee_id": emp})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- pure arithmetic ----------
def test_working_days_skip_weekends():
    assert working_days(MON, MON + timedelta(days=4)) == 5
    assert working_days(MON, MON + timedelta(days=6)) == 5
    assert working_days(MON + timedelta(days=5), MON + timedelta(days=6)) == 0
    assert working_days(MON + timedelta(days=4), MON + timedelta(days=7)) == 2
    assert working_days(MON + timedelta(days=1), MON) == 0
    assert working_days(date(1, 1, 1), date(9999, 12, 31)) > 2_000_000      # no loop over the days


def test_day_balance_counts_only_days_that_passed_and_are_owed():
    week = (MON, MON + timedelta(days=6))
    # Wednesday: Monday and Tuesday are over, today is not and owes nothing yet
    got = day_balance(*week, MON + timedelta(days=2), 8, {}, {})
    assert (got["expected"], got["missing_days"], got["short"]) == (16, 2, 16)
    # today counts once it has hours; an open shift has none yet
    got = day_balance(*week, MON + timedelta(days=2), 8, {MON + timedelta(days=2): 4.0}, {})
    assert (got["expected"], got["missing_days"]) == (24, 2)
    assert day_balance(*week, MON + timedelta(days=2), 8, {MON + timedelta(days=2): 0.0}, {})["expected"] == 16
    # a past day with a forgotten clock-out has zero hours, but the person was there
    assert day_balance(*week, MON + timedelta(days=2), 8, {MON: 0.0}, {})["missing_days"] == 1
    # days before the hire date are owed by nobody
    assert day_balance(*week, MON + timedelta(days=7), 8, {}, {}, MON + timedelta(days=3))["expected"] == 16
    # a card made inactive owes only what is recorded
    got = day_balance(*week, MON + timedelta(days=7), 8, {MON: 8.0}, {}, None, False)
    assert (got["expected"], got["missing_days"], got["short"]) == (8, 0, 0)
    # Saturday work is hours, but no day is owed for it
    got = day_balance(*week, MON + timedelta(days=7), 8, {MON + timedelta(days=5): 6.0}, {})
    assert (got["expected"], got["missing_days"], got["short"]) == (40, 5, 34)


def test_day_balance_leave():
    week = (MON, MON + timedelta(days=6))
    now = MON + timedelta(days=7)
    leaves = {MON: "annual", MON + timedelta(days=1): "sick", MON + timedelta(days=2): "excuse",
              MON + timedelta(days=3): "unpaid"}
    got = day_balance(*week, now, 8, {MON + timedelta(days=4): 8.0}, leaves)
    assert got["expected"] == 40 and got["covered"] == 24 and got["missing_days"] == 0
    assert got["short"] == 8          # the unpaid day: not missing, but not covered
    assert got["leave"] == {"annual": 1, "sick": 1, "excuse": 1, "unpaid": 1}
    # half a day worked and then leave: the leave covers the rest, not the whole day again
    got = day_balance(*week, now, 8, {MON: 3.0}, {MON: "annual"})
    assert got["covered"] == 5
    # leave ahead is shown but neither owed nor covered yet
    got = day_balance(*week, MON, 8, {}, {MON + timedelta(days=2): "annual"})
    assert (got["expected"], got["covered"], got["leave"]) == (0, 0, {"annual": 1})


# ---------- leave ----------
def test_worker_requests_and_balance_follows_every_step(client, admin_headers):
    h, emp = _worker(client, admin_headers, annual_leave_days=10)
    assert _balance(client, h) == {"year": MON.year, "entitled": 10, "used": 0, "pending": 0, "remaining": 10}
    r = _ask(client, h, MON, MON + timedelta(days=6))           # the weekend is not counted
    assert r.status_code == 201, r.text
    leave = r.json()
    assert leave["days"] == 5 and leave["status"] == "pending"
    assert _balance(client, h) == {"year": MON.year, "entitled": 10, "used": 0, "pending": 5, "remaining": 5}
    assert client.post(f"/api/leave/me/{leave['id']}/cancel", headers=h).status_code == 200
    assert _balance(client, h)["pending"] == 0
    assert client.post(f"/api/leave/me/{leave['id']}/cancel", headers=h).status_code == 409

    leave = _ask(client, h, MON, MON + timedelta(days=1)).json()
    d = _decide(client, admin_headers, leave["id"], note="İyi tatiller")
    assert d.status_code == 200 and d.json()["status"] == "approved" and d.json()["decided_by"] == "admin"
    assert d.json()["decision_note"] == "İyi tatiller"
    assert _balance(client, h) == {"year": MON.year, "entitled": 10, "used": 2, "pending": 0, "remaining": 8}
    assert client.post(f"/api/leave/me/{leave['id']}/cancel", headers=h).status_code == 409    # only a manager now
    assert _decide(client, admin_headers, leave["id"], False).status_code == 409               # no second decision
    assert client.post(f"/api/leave/{leave['id']}/cancel", headers=admin_headers, json={}).json()["status"] == "cancelled"
    assert _balance(client, h)["used"] == 0
    assert client.post(f"/api/leave/{leave['id']}/cancel", headers=admin_headers, json={}).status_code == 409


def test_entitlement_comes_from_the_card_then_the_setting(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    default = client.get("/api/admin/settings", headers=admin_headers).json()["system"]["production"]["annual_leave_days"]
    assert _balance(client, h)["entitled"] == default
    assert client.put(f"/api/employees/{emp}", headers=admin_headers, json={"annual_leave_days": 0}).status_code == 200
    assert _balance(client, h)["entitled"] == 0                # zero is an answer, not "use the default"
    r = _ask(client, h, MON, MON).json()
    assert _decide(client, admin_headers, r["id"]).status_code == 409
    assert client.put(f"/api/employees/{emp}", headers=admin_headers, json={"annual_leave_days": 20}).json()["annual_leave_days"] == 20
    assert client.put(f"/api/employees/{emp}", headers=admin_headers, json={"annual_leave_days": None}).status_code == 200
    assert _balance(client, h)["entitled"] == default
    assert client.put(f"/api/employees/{emp}", headers=admin_headers, json={"annual_leave_days": -1}).status_code == 422


def test_leave_range_rules(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    assert _ask(client, h, MON + timedelta(days=1), MON).status_code == 400
    assert _ask(client, h, MON + timedelta(days=5), MON + timedelta(days=6)).status_code == 400   # a weekend only
    assert _ask(client, h, MON, MON + timedelta(days=500)).status_code == 400
    assert _ask(client, h, MON, MON, kind="yok").status_code == 422
    first = _ask(client, h, MON, MON + timedelta(days=2)).json()
    assert _ask(client, h, MON + timedelta(days=2), MON + timedelta(days=3), "sick").status_code == 409
    second = _ask(client, h, MON + timedelta(days=3), MON + timedelta(days=4), "sick").json()
    _decide(client, admin_headers, second["id"])
    assert _ask(client, h, MON + timedelta(days=4), MON + timedelta(days=4)).status_code == 409   # approved blocks too
    _decide(client, admin_headers, first["id"], False)
    assert _ask(client, h, MON, MON + timedelta(days=2)).status_code == 201      # a rejected one frees its days
    other_h, _ = _worker(client, admin_headers)
    assert _ask(client, other_h, MON, MON).status_code == 201                    # overlap is per person


def test_only_annual_uses_the_balance_and_approval_rechecks_it(client, admin_headers):
    h, emp = _worker(client, admin_headers, annual_leave_days=3)
    sick = _ask(client, h, MON + timedelta(days=7), MON + timedelta(days=11), "sick").json()
    assert sick["days"] == 5 and _decide(client, admin_headers, sick["id"]).status_code == 200
    assert _balance(client, h)["used"] == 0
    # the request is above the balance only when it is approved
    a = _ask(client, h, MON, MON + timedelta(days=1)).json()
    b = _ask(client, h, MON + timedelta(days=2), MON + timedelta(days=3)).json()
    assert _balance(client, h)["remaining"] == -1
    assert _decide(client, admin_headers, a["id"]).status_code == 200      # waiting b does not block a
    r = _decide(client, admin_headers, b["id"])
    assert r.status_code == 409 and "kalan 1 gün" in r.json()["detail"]
    assert client.get("/api/leave", headers=admin_headers, params={"employee_id": emp, "status": "pending"}).json()["rows"][0]["id"] == b["id"]
    assert _decide(client, admin_headers, b["id"], False).status_code == 200   # a refused approval leaves it decidable


def test_leave_across_new_year_counts_on_both_years(client, admin_headers):
    h, emp = _worker(client, admin_headers, annual_leave_days=3)
    r = _ask(client, h, date(2027, 12, 30), date(2028, 1, 4)).json()       # Thu, Fri | Mon, Tue
    assert r["days"] == 4
    assert _decide(client, admin_headers, r["id"]).status_code == 200      # 2 + 2, each year holds 3
    assert _balance(client, h, 2027)["used"] == 2 and _balance(client, h, 2028)["used"] == 2


def test_manager_enters_and_filters_leave(client, admin_headers):
    h, emp = _worker(client, admin_headers, annual_leave_days=2)
    body = {"employee_id": emp, "kind": "annual", "start_date": str(MON), "end_date": str(MON + timedelta(days=4))}
    assert client.post("/api/leave", headers=admin_headers, json=body).status_code == 409      # above the balance
    assert client.post("/api/leave", headers=admin_headers, json={**body, "employee_id": 999999}).status_code == 404
    r = client.post("/api/leave", headers=admin_headers, json={**body, "kind": "sick"})
    assert r.status_code == 201 and r.json()["status"] == "approved" and r.json()["days"] == 5
    assert client.post("/api/leave", headers=admin_headers, json={**body, "kind": "excuse"}).status_code == 409    # overlap
    q = {"employee_id": emp, "kind": "sick", "status": "approved"}
    assert len(client.get("/api/leave", headers=admin_headers, params=q).json()["rows"]) == 1
    assert not client.get("/api/leave", headers=admin_headers, params={**q, "kind": "annual"}).json()["rows"]
    assert not client.get("/api/leave", headers=admin_headers, params={**q, "date_from": str(MON + timedelta(days=5))}).json()["rows"]
    assert len(client.get("/api/leave", headers=admin_headers, params={**q, "date_to": str(MON)}).json()["rows"]) == 1
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.entity == "leave", AuditLog.entity_id == str(r.json()["id"])))
    assert client.delete(f"/api/employees/{emp}", headers=admin_headers).status_code == 400


def test_leave_rights(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    other_h, _ = _worker(client, admin_headers)
    vm = _viewer_manager(client, admin_headers)
    mine = _ask(client, h, MON, MON).json()
    assert client.post(f"/api/leave/me/{mine['id']}/cancel", headers=other_h).status_code == 404
    assert mine["id"] not in {r["id"] for r in client.get("/api/leave/me", headers=other_h).json()["rows"]}
    body = {"employee_id": emp, "kind": "sick", "start_date": str(MON), "end_date": str(MON)}
    for user in (h, vm):
        assert client.post("/api/leave", headers=user, json=body).status_code == 403
        assert _decide(client, user, mine["id"]).status_code == 403
        assert client.post(f"/api/leave/{mine['id']}/cancel", headers=user, json={}).status_code == 403
    assert client.get("/api/leave", headers=h).status_code == 403
    assert client.get("/api/leave", headers=vm).status_code == 200
    assert client.get("/api/attendance/queue", headers=h).status_code == 403
    no_card, _ = _login(client, admin_headers, "viewer")
    assert client.get("/api/leave/me", headers=no_card).json()["employee"] is None
    assert _ask(client, no_card, MON, MON).status_code == 400
    client.put(f"/api/employees/{emp}", headers=admin_headers, json={"active": False})
    assert _ask(client, h, MON + timedelta(days=1), MON + timedelta(days=1)).status_code == 403


def test_decision_is_read_after_the_lock(client, admin_headers, monkeypatch):
    """Two managers at once: the second sees what the first committed while it waited for the lock."""
    h, emp = _worker(client, admin_headers)
    r = _ask(client, h, MON, MON).json()
    real = leave_api._lock_card

    def other_manager_got_there_first(db, emp_id):
        db.execute(update(LeaveRequest).where(LeaveRequest.id == r["id"]).values(status="rejected"))
        return real(db, emp_id)

    monkeypatch.setattr(leave_api, "_lock_card", other_manager_got_there_first)
    assert _decide(client, admin_headers, r["id"]).status_code == 409


def test_report_marks_leave_and_keeps_expected_hours_honest(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    mon = _last_week_monday()
    fri = mon + timedelta(days=4)
    for off, kind in ((0, "annual"), (1, "unpaid")):
        day = str(mon + timedelta(days=off))
        assert client.post("/api/leave", headers=admin_headers, json={"employee_id": emp, "kind": kind, "start_date": day,
                                                                      "end_date": day}).status_code == 201
    pending = _ask(client, h, mon + timedelta(days=4), mon + timedelta(days=4), "sick").json()
    for off in (2, 3):
        _shift(client, admin_headers, emp, mon + timedelta(days=off))
    d = _report(client, admin_headers, emp, mon, fri)
    p = d["people"][0]
    assert p["expected"] == 40 and p["hours"] == 16 and p["covered"] == 8
    assert p["missing_days"] == 1          # Friday: a request that only waits covers nothing
    assert p["short"] == 16                # the unpaid Tuesday and Friday
    assert p["leave"] == {"annual": 1, "unpaid": 1}
    assert d["total"]["expected"] == 40 and d["total"]["missing_days"] == 1
    assert [(x["kind"], x["label"]) for x in d["leave_days"]] == [("unpaid", "Ücretsiz izin"), ("annual", "Yıllık izin")]

    _decide(client, admin_headers, pending["id"])
    p = _report(client, admin_headers, emp, mon, fri)["people"][0]
    assert p["missing_days"] == 0 and p["covered"] == 16 and p["short"] == 8

    month = mon.strftime("%Y-%m")
    mine = client.get("/api/attendance/me", headers=h, params={"month": month}).json()
    assert {x["work_date"] for x in mine["leave_days"]} >= {str(mon), str(mon + timedelta(days=1))} or mon.month != fri.month
    assert {"expected", "covered", "missing_days", "short", "leave"} <= set(mine["summary"])


def test_inactive_person_with_only_leave_stays_in_the_report(client, admin_headers):
    _, emp = _worker(client, admin_headers)
    mon = _last_week_monday()
    client.post("/api/leave", headers=admin_headers, json={"employee_id": emp, "kind": "sick", "start_date": str(mon),
                                                           "end_date": str(mon)})
    client.put(f"/api/employees/{emp}", headers=admin_headers, json={"active": False})
    p = _report(client, admin_headers, emp, mon, mon + timedelta(days=4))["people"][0]
    assert p["expected"] == 8 and p["covered"] == 8 and p["missing_days"] == 0


# ---------- shift correction requests ----------
def _fix(client, h, day, start="08:00", end="17:00", reason="Unuttum", **extra):
    return client.post("/api/attendance/requests", headers=h, json={"work_date": str(day), "clock_in": start,
                                                                    "clock_out": end, "reason": reason, **extra})


def _fix_decide(client, headers, rid, approve=True):
    return client.post(f"/api/attendance/requests/{rid}/decide", headers=headers, json={"approve": approve})


def test_missing_shift_request_creates_the_shift(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    day = _last_week_monday()
    assert _fix(client, h, day, reason="   ").status_code == 400
    assert _fix(client, h, day, end=None).status_code == 400              # a whole shift needs both times
    assert _fix(client, h, date.today() + timedelta(days=1)).status_code == 400
    assert _fix(client, h, day, end="08:00").status_code == 400
    r = _fix(client, h, day)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert client.get("/api/attendance/queue", headers=admin_headers).json()["shifts"] >= 1
    assert rid in {x["id"] for x in client.get("/api/attendance/requests", headers=admin_headers,
                                               params={"status": "pending"}).json()["rows"]}
    assert not _report(client, admin_headers, emp, day, day)["rows"]      # nothing changes before the decision
    d = _fix_decide(client, admin_headers, rid)
    assert d.status_code == 200 and d.json()["status"] == "approved"
    row = _report(client, admin_headers, emp, day, day)["rows"][0]
    assert (row["start"], row["end"], row["hours"], row["break_minutes"], row["note"]) == ("08:00", "17:00", 8, 60, "Unuttum")
    assert row["corrected_by"] == "admin" and d.json()["attendance_id"] == row["id"]
    with SessionLocal() as db:
        log = db.scalar(select(AuditLog).where(AuditLog.entity == "attendance", AuditLog.entity_id == str(row["id"])))
        assert log.old is None and "08:00" in log.new
    assert _fix_decide(client, admin_headers, rid, False).status_code == 409
    assert client.post(f"/api/attendance/requests/{rid}/cancel", headers=h).status_code == 409


def test_correction_changes_the_row_and_keeps_what_it_did_not_ask_about(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    day = _last_week_monday()
    sid = _shift(client, admin_headers, emp, day, "08:00", "18:00", break_minutes=30, note="Bakım")
    r = _fix(client, h, day, "07:30", None, attendance_id=sid)            # about the clock-in only
    assert r.status_code == 201 and r.json()["end"] == "18:00" and "08:00" in r.json()["current"]
    assert _fix_decide(client, admin_headers, r.json()["id"]).status_code == 200
    row = _report(client, admin_headers, emp, day, day)["rows"][0]
    assert (row["start"], row["end"], row["break_minutes"], row["note"]) == ("07:30", "18:00", 30, "Bakım")
    with SessionLocal() as db:
        log = db.scalars(select(AuditLog).where(AuditLog.entity == "attendance", AuditLog.entity_id == str(sid),
                                                AuditLog.action == "update").order_by(AuditLog.id.desc())).first()
        assert "08:00" in log.old and "07:30" in log.new


def test_missing_clock_out_gets_the_default_break(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    day = _last_week_monday()
    sid = _shift(client, admin_headers, emp, day, "08:00", None)
    r = _fix(client, h, day, "08:00", "17:00", attendance_id=sid)
    assert _fix_decide(client, admin_headers, r.json()["id"]).status_code == 200
    row = _report(client, admin_headers, emp, day, day)["rows"][0]
    assert (row["end"], row["break_minutes"], row["status"]) == ("17:00", 60, "done")


def test_approval_rechecks_and_a_refused_request_stays_pending(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    day = _last_week_monday()
    rid = _fix(client, h, day, "08:00", "12:00").json()["id"]
    sid = _shift(client, admin_headers, emp, day, "10:00", "14:00")       # entered after the request
    assert _fix(client, h, day, "09:00", "11:00").status_code == 409      # refused at once when already known
    r = _fix_decide(client, admin_headers, rid)
    assert r.status_code == 409 and "çakışıyor" in r.json()["detail"]
    assert client.get("/api/attendance/requests/me", headers=h).json()["rows"][0]["status"] == "pending"
    assert len(_report(client, admin_headers, emp, day, day)["rows"]) == 1
    client.delete(f"/api/attendance/{sid}", headers=admin_headers)
    assert _fix_decide(client, admin_headers, rid).status_code == 200


def test_deleting_a_shift_closes_the_requests_about_it(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    day = _last_week_monday()
    sid = _shift(client, admin_headers, emp, day)
    rid = _fix(client, h, day, "07:00", "16:00", attendance_id=sid).json()["id"]
    assert client.delete(f"/api/attendance/{sid}", headers=admin_headers).status_code == 200
    row = client.get("/api/attendance/requests/me", headers=h).json()["rows"][0]
    assert row["status"] == "rejected" and row["decided_by"] == "admin" and row["decision_note"]
    assert _fix_decide(client, admin_headers, rid).status_code == 409       # it cannot bring the shift back
    assert not _report(client, admin_headers, emp, day, day)["rows"]


def test_correction_rights(client, admin_headers):
    h, emp = _worker(client, admin_headers)
    other_h, other = _worker(client, admin_headers)
    vm = _viewer_manager(client, admin_headers)
    day = _last_week_monday()
    theirs = _shift(client, admin_headers, other, day)
    assert _fix(client, h, day, attendance_id=theirs).status_code == 404
    rid = _fix(client, h, day).json()["id"]
    assert client.post(f"/api/attendance/requests/{rid}/cancel", headers=other_h).status_code == 404
    assert not client.get("/api/attendance/requests/me", headers=other_h).json()["rows"]
    assert client.get("/api/attendance/requests", headers=h).status_code == 403
    assert client.get("/api/attendance/requests", headers=vm).status_code == 200
    assert _fix_decide(client, h, rid).status_code == 403
    assert _fix_decide(client, vm, rid).status_code == 403
    assert client.post(f"/api/attendance/requests/{rid}/cancel", headers=h).json()["status"] == "cancelled"
    assert _fix_decide(client, admin_headers, rid).status_code == 409     # cancelled is decided too
    assert _fix_decide(client, admin_headers, 999999).status_code == 404
    no_card, _ = _login(client, admin_headers, "viewer")
    assert _fix(client, no_card, day).status_code == 400
    assert client.get("/api/attendance/requests/me", headers=no_card).json()["employee"] is None


def test_shift_decision_is_read_after_the_lock(client, admin_headers, monkeypatch):
    h, emp = _worker(client, admin_headers)
    rid = _fix(client, h, _last_week_monday()).json()["id"]
    real = attendance_api._lock_card

    def other_manager_got_there_first(db, emp_id):
        db.execute(update(AttendanceRequest).where(AttendanceRequest.id == rid).values(status="approved"))
        return real(db, emp_id)

    monkeypatch.setattr(attendance_api, "_lock_card", other_manager_got_there_first)
    assert _fix_decide(client, admin_headers, rid, False).status_code == 409


# ---------- hours to jobs ----------
@pytest.fixture
def job(client, admin_headers):
    """A project with an open work order."""
    pid = client.post("/api/projects", headers=admin_headers, json={"name": _u("Saat projesi")}).json()["id"]
    r = client.post("/api/work-orders", headers=admin_headers, json={"part_no": _u("P"), "qty": 1, "project_id": pid,
                                                                     "description": "Kaynak"})
    assert r.status_code == 201, r.text
    return pid, r.json()


def _time(client, h, day, hours, **target):
    return client.post("/api/hr/me/time", headers=h, json={"work_date": str(day), "hours": hours, **target})


def test_pick_list_shows_only_what_it_should(client, admin_headers, job):
    pid, wo = job
    h, _ = _worker(client, admin_headers)
    d = client.get("/api/hr/me/time/options", headers=h).json()
    row = next(w for w in d["work_orders"] if w["id"] == wo["id"])
    assert set(row) == {"id", "no", "description"} and row["description"] == "Kaynak"
    assert set(next(p for p in d["projects"] if p["id"] == pid)) == {"id", "name"}
    # the worker still has no rights on the real lists
    assert client.get("/api/work-orders", headers=_login(client, admin_headers, "viewer", permissions={"workorders": "none"})[0]).status_code == 403
    done = client.post("/api/work-orders", headers=admin_headers, json={"part_no": _u("Q"), "qty": 1, "project_id": pid}).json()
    assert client.post(f"/api/work-orders/{done['id']}/status", headers=admin_headers, json={"status": "cancelled"}).status_code == 200
    assert done["id"] not in {w["id"] for w in client.get("/api/hr/me/time/options", headers=h).json()["work_orders"]}
    assert _time(client, h, date.today(), 1, work_order_id=done["id"]).status_code == 400


def test_archived_project_leaves_the_pick_list(client, admin_headers, job):
    pid, wo = job
    h, _ = _worker(client, admin_headers)
    client.put(f"/api/projects/{pid}", headers=admin_headers, json={"archived": True})
    with SessionLocal() as db:
        from app.models import Project
        db.get(Project, pid).archived = True
        db.commit()
    d = client.get("/api/hr/me/time/options", headers=h).json()
    assert pid not in {p["id"] for p in d["projects"]} and wo["id"] not in {w["id"] for w in d["work_orders"]}
    assert _time(client, h, date.today(), 1, project_id=pid).status_code == 400
    assert _time(client, h, date.today(), 1, work_order_id=wo["id"]).status_code == 400


def test_hours_flow_into_project_cost_with_the_card_rate(client, admin_headers, job):
    pid, wo = job
    h, emp = _worker(client, admin_headers, hourly_cost=200)
    day = date.today() - timedelta(days=1)
    r = _time(client, h, day, 3, work_order_id=wo["id"])       # no project sent: the order brings it
    assert r.status_code == 201, r.text
    assert r.json()["project_id"] == pid and r.json()["work_order_no"] == wo["no"]
    assert "hourly_cost" not in r.json() and "cost" not in r.json()
    costs = client.get(f"/api/projects/{pid}/costs", headers=admin_headers).json()
    assert {"name": "İşçilik", "committed": 600, "actual": 600} in costs["by_source"]
    # the snapshot holds: a later raise does not rewrite an entry, nor does an edit by the worker
    client.put(f"/api/employees/{emp}", headers=admin_headers, json={"hourly_cost": 900})
    e = client.put(f"/api/hr/me/time/{r.json()['id']}", headers=h, json={"work_date": str(day), "hours": 2, "work_order_id": wo["id"]})
    assert e.status_code == 200, e.text
    costs = client.get(f"/api/projects/{pid}/costs", headers=admin_headers).json()
    assert {"name": "İşçilik", "committed": 400, "actual": 400} in costs["by_source"]
    # nothing the client sends reaches the snapshot
    r = client.post("/api/hr/me/time", headers=h, json={"work_date": str(day), "hours": 1, "project_id": pid, "hourly_cost": 1})
    with SessionLocal() as db:
        assert db.get(TimeEntry, r.json()["id"]).hourly_cost == 900


def test_day_view_and_cap_follow_the_attended_hours(client, admin_headers, job):
    pid, wo = job
    h, emp = _worker(client, admin_headers)
    day = date.today() - timedelta(days=2)
    _shift(client, admin_headers, emp, day)                    # 9 hours less the break: 8 net
    assert _time(client, h, day, 5, project_id=pid).status_code == 201
    d = client.get("/api/hr/me/time", headers=h, params={"day": str(day)}).json()
    assert (d["attended"], d["allocated"], d["remaining"], d["editable"]) == (8, 5, 3, True)
    assert not any("cost" in k for row in d["rows"] for k in row)
    r = _time(client, h, day, 3.5, work_order_id=wo["id"])
    assert r.status_code == 400 and "8 saat" in r.json()["detail"]
    ok = _time(client, h, day, 3, work_order_id=wo["id"])
    assert ok.status_code == 201
    # the entry's own hours do not count against it, the others' do
    rid = ok.json()["id"]
    assert client.put(f"/api/hr/me/time/{rid}", headers=h, json={"work_date": str(day), "hours": 3, "project_id": pid}).status_code == 200
    assert client.put(f"/api/hr/me/time/{rid}", headers=h, json={"work_date": str(day), "hours": 3.1, "project_id": pid}).status_code == 400
    assert client.delete(f"/api/hr/me/time/{rid}", headers=h).status_code == 200
    assert client.get("/api/hr/me/time", headers=h, params={"day": str(day)}).json()["remaining"] == 3


def test_tenths_do_not_trip_the_cap(client, admin_headers, job):
    pid, _ = job
    h, emp = _worker(client, admin_headers)
    day = date.today() - timedelta(days=2)
    _shift(client, admin_headers, emp, day, "08:00", "08:18", break_minutes=0)       # 0.3 hours
    assert _time(client, h, day, 0.1, project_id=pid).status_code == 201
    assert _time(client, h, day, 0.2, project_id=pid).status_code == 201             # 0.1 + 0.2 is 0.30000000000000004


def test_day_without_a_shift_caps_at_24(client, admin_headers, job):
    pid, _ = job
    h, _ = _worker(client, admin_headers)
    day = date.today() - timedelta(days=1)
    assert _time(client, h, day, 20, project_id=pid).status_code == 201
    assert _time(client, h, day, 5, project_id=pid).status_code == 400
    assert _time(client, h, day, 4, project_id=pid).status_code == 201
    d = client.get("/api/hr/me/time", headers=h, params={"day": str(day)}).json()
    assert d["attended"] is None and d["remaining"] == 0


def test_open_and_forgotten_shifts(client, admin_headers, job):
    pid, _ = job
    h, emp = _worker(client, admin_headers)
    now = datetime.now().replace(microsecond=0)
    with SessionLocal() as db:
        db.add(Attendance(employee_id=emp, work_date=now.date(), clock_in=now - timedelta(hours=2)))
        old = (now - timedelta(days=3))
        db.add(Attendance(employee_id=emp, work_date=old.date(), clock_in=old))
        db.commit()
    d = client.get("/api/hr/me/time", headers=h).json()
    assert d["open"] and d["attended"] == 2                      # counts up to now, under the break threshold
    assert _time(client, h, now.date(), 1.5, project_id=pid).status_code == 201
    assert _time(client, h, now.date(), 1, project_id=pid).status_code == 400
    r = _time(client, h, old.date(), 1, project_id=pid)
    assert r.status_code == 400 and "düzeltme" in r.json()["detail"]


def test_recent_days_only_for_the_worker(client, admin_headers, job):
    pid, _ = job
    h, emp = _worker(client, admin_headers)
    edge = date.today() - timedelta(days=7)
    old = date.today() - timedelta(days=8)
    assert _time(client, h, edge, 1, project_id=pid).status_code == 201
    assert _time(client, h, old, 1, project_id=pid).status_code == 403
    assert _time(client, h, date.today() + timedelta(days=1), 1, project_id=pid).status_code == 400
    assert _time(client, h, edge, 1).status_code == 400            # some job has to be named
    m = client.post("/api/time-entries", headers=admin_headers, json={"employee_id": emp, "work_date": str(old), "hours": 2, "project_id": pid}).json()
    body = {"work_date": str(old), "hours": 1, "project_id": pid}
    assert client.put(f"/api/hr/me/time/{m['id']}", headers=h, json=body).status_code == 403
    assert client.delete(f"/api/hr/me/time/{m['id']}", headers=h).status_code == 403
    assert client.get("/api/hr/me/time", headers=h, params={"day": str(old)}).json()["editable"] is False
    fresh = _time(client, h, edge, 1, project_id=pid).json()
    assert client.put(f"/api/hr/me/time/{fresh['id']}", headers=h, json=body).status_code == 403   # nor moved back there
    # the manager corrects it from the time entry screen and the wage stays
    r = client.put(f"/api/time-entries/{m['id']}", headers=admin_headers, json={**body, "hours": 1.5})
    assert r.status_code == 200 and r.json()["hours"] == 1.5
    assert client.put(f"/api/time-entries/{m['id']}", headers=h, json=body).status_code == 403


def test_worker_touches_only_own_entries(client, admin_headers, job):
    pid, _ = job
    h, _ = _worker(client, admin_headers)
    other_h, _ = _worker(client, admin_headers)
    e = _time(client, h, date.today(), 1, project_id=pid).json()
    body = {"work_date": str(date.today()), "hours": 1, "project_id": pid}
    assert client.put(f"/api/hr/me/time/{e['id']}", headers=other_h, json=body).status_code == 404
    assert client.delete(f"/api/hr/me/time/{e['id']}", headers=other_h).status_code == 404
    no_card, _ = _login(client, admin_headers, "viewer")
    assert client.get("/api/hr/me/time", headers=no_card).json()["employee"] is None
    assert _time(client, no_card, date.today(), 1, project_id=pid).status_code == 400
    assert client.post("/api/time-entries", headers=h, json={"employee_id": 1, "hours": 1}).status_code == 403


def test_work_order_and_project_must_agree(client, admin_headers, job):
    pid, wo = job
    other = client.post("/api/projects", headers=admin_headers, json={"name": _u("Başka")}).json()["id"]
    h, _ = _worker(client, admin_headers)
    assert _time(client, h, date.today(), 1, work_order_id=wo["id"], project_id=other).status_code == 400
    assert _time(client, h, date.today(), 1, work_order_id=999999).status_code == 404
    assert _time(client, h, date.today(), 1, project_id=999999).status_code == 404


def test_closed_order_does_not_block_fixing_hours_written_on_it(client, admin_headers, job):
    pid, wo = job
    h, _ = _worker(client, admin_headers)
    e = _time(client, h, date.today(), 2, work_order_id=wo["id"]).json()
    assert client.post(f"/api/work-orders/{wo['id']}/status", headers=admin_headers, json={"status": "cancelled"}).status_code == 200
    r = client.put(f"/api/hr/me/time/{e['id']}", headers=h, json={"work_date": str(date.today()), "hours": 1, "work_order_id": wo["id"]})
    assert r.status_code == 200, r.text


def test_annual_leave_setting_is_saved(client, admin_headers):
    h, _ = _worker(client, admin_headers)
    was = client.get("/api/admin/settings", headers=admin_headers).json()["system"]["production"]["annual_leave_days"]
    put = lambda days: client.put("/api/admin/settings/system", headers=admin_headers,        # noqa: E731
                                  json={"value": {"production": {"annual_leave_days": days}}})
    assert put(21).status_code == 200
    assert _balance(client, h)["entitled"] == 21
    assert put(99).status_code == 400
    assert put(was).status_code == 200
