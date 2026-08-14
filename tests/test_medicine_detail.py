"""L1 — per-medicine detail drill-down. One medicine's whole story (its own
adherence, skip reasons, on-time quality, supply, and change history) gathered
from the scattered account-wide panels into a single view. All from the user's
own logs; a foreign/missing medicine 404s."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "meddet-pw-1234"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def _days_ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_missing_or_foreign_medicine_404s(app):
    c = _register(app, "meddet1@medeasy.test")
    assert c.get("/api/medicines/does-not-exist/detail").status_code == 404
    # A medicine owned by someone else is invisible — same 404, not a leak.
    other = _register(app, "meddet1b@medeasy.test")
    mine = other.post("/api/medicines", json={
        "name": "Theirs", "frequency": "once_daily", "times": ["08:00"]}).get_json()["medicine"]
    assert c.get(f"/api/medicines/{mine['id']}/detail").status_code == 404


def test_own_adherence_and_skip_reasons(app):
    c = _register(app, "meddet2@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Metformin", "frequency": "once_daily",
        "times": ["09:00"], "start_date": _days_ago(10)}).get_json()["medicine"]
    # 11 scheduled days (today back to day 10). Take 7, skip 1 with a reason,
    # leave 3 unlogged (missed, no reason).
    for i in range(7):
        c.post(f"/api/medicines/{m['id']}/log",
               json={"date": _days_ago(i), "time": "09:00", "taken": True})
    c.post(f"/api/medicines/{m['id']}/log",
           json={"date": _days_ago(7), "time": "09:00", "taken": False, "reason": "forgot"})

    d = c.get(f"/api/medicines/{m['id']}/detail?days=30").get_json()
    assert d["name"] == "Metformin" and d["is_prn"] is False
    assert d["adherence"]["has_data"] is True
    assert d["adherence"]["taken"] == 7
    assert d["adherence"]["total"] == 11
    assert d["adherence"]["missed"] == 4
    assert d["adherence"]["pct"] == round(7 / 11 * 100)
    # The one tagged skip surfaces as this medicine's own reason.
    reasons = {r["reason"]: r["count"] for r in d["skip_reasons"]}
    assert reasons.get("forgot") == 1
    # A single 09:00 slot, ranked.
    assert len(d["slots"]) == 1 and d["slots"][0]["time"] == "09:00"


def test_ontime_quality_registers_a_same_day_take(app):
    c = _register(app, "meddet3@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Aspirin", "frequency": "once_daily",
        "times": ["09:00"], "start_date": _days_ago(5)}).get_json()["medicine"]
    # Logged today for a scheduled HH:MM slot → a real scheduled-vs-logged delay.
    c.post(f"/api/medicines/{m['id']}/log",
           json={"date": _days_ago(0), "time": "09:00", "taken": True})
    d = c.get(f"/api/medicines/{m['id']}/detail").get_json()
    assert d["ontime"]["has_data"] is True
    assert d["ontime"]["count"] >= 1
    # buckets always present, sum to the counted total
    assert sum(b["count"] for b in d["ontime"]["buckets"]) == d["ontime"]["count"]


def test_backfill_a_past_dose_updates_adherence(app):
    # L5: logging a dose for an EARLIER day (the modal's backfill) flows through
    # the same /log endpoint and is reflected in the medicine's own numbers.
    c = _register(app, "meddet5@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Levothyroxine", "frequency": "once_daily",
        "times": ["07:00"], "start_date": _days_ago(6)}).get_json()["medicine"]
    before = c.get(f"/api/medicines/{m['id']}/detail").get_json()["adherence"]["taken"]
    # Backfill 3 earlier days as taken.
    for i in (2, 3, 4):
        r = c.post(f"/api/medicines/{m['id']}/log",
                   json={"date": _days_ago(i), "time": "07:00", "taken": True})
        assert r.get_json()["success"] is True
    after = c.get(f"/api/medicines/{m['id']}/detail").get_json()["adherence"]["taken"]
    assert after == before + 3


def test_prn_with_stock_shows_no_fabricated_supply(app):
    # Review finding 1: a PRN med that tracks pills must NOT report a
    # days-of-supply — it has no daily rate, so any figure would be invented.
    c = _register(app, "meddet6@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Rescue Inhaler", "frequency": "as_needed"}).get_json()["medicine"]
    c.post(f"/api/medicines/{m['id']}/stock",
           json={"pill_count": 30, "pills_per_dose": 1, "refill_threshold": 7})
    d = c.get(f"/api/medicines/{m['id']}/detail").get_json()
    assert d["is_prn"] is True
    assert d["days_of_supply"] is None          # not a fabricated ~30 days


def test_log_rejects_future_date_and_bad_time(app):
    # Review finding 2: the server, not just the client, blocks a future-dated
    # or malformed dose so it can't consume stock or skew the math.
    c = _register(app, "meddet7@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Ramipril", "frequency": "once_daily", "times": ["08:00"]}).get_json()["medicine"]
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    r1 = c.post(f"/api/medicines/{m['id']}/log",
                json={"date": future, "time": "08:00", "taken": True})
    assert r1.status_code == 400
    r2 = c.post(f"/api/medicines/{m['id']}/log",
                json={"date": _days_ago(1), "time": "not-a-time", "taken": True})
    assert r2.status_code == 400
    # A valid past-dated backfill still works.
    r3 = c.post(f"/api/medicines/{m['id']}/log",
                json={"date": _days_ago(1), "time": "08:00", "taken": True})
    assert r3.status_code == 200 and r3.get_json()["success"] is True


def test_detail_history_carries_no_internal_ids(app):
    # Review finding 3: the /detail payload must not ship internal row ids.
    c = _register(app, "meddet8@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Atorvastatin", "frequency": "once_daily", "times": ["21:00"]}).get_json()["medicine"]
    d = c.get(f"/api/medicines/{m['id']}/detail").get_json()
    assert d["history"], "expected at least a 'started' event"
    for e in d["history"]:
        assert "id" not in e and "medicine_id" not in e and "user_id" not in e
        assert set(e.keys()) <= {"kind", "at", "detail"}


def test_prn_has_no_adherence_but_shows_history(app):
    c = _register(app, "meddet4@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Sumatriptan", "frequency": "as_needed"}).get_json()["medicine"]
    d = c.get(f"/api/medicines/{m['id']}/detail").get_json()
    assert d["is_prn"] is True
    # No schedule to hold a PRN med to — adherence stays honest-empty, never a
    # fabricated miss count.
    assert d["adherence"]["has_data"] is False
    assert d["adherence"]["pct"] is None
    # The 'started' event still tells its history.
    assert any(e["kind"] == "started" for e in d["history"])
