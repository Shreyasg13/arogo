"""Dental & vision care — dated checkups (with an optional next-due countdown)
and the user's own glasses/contacts prescription, stored verbatim. Factual
records only: nothing scheduled, recommended, or interpreted; every row
user-scoped."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "dv-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def _days(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_add_and_list_visits_by_kind(app):
    c = _reg(app, "dv1@medeasy.test")
    c.post("/api/dental-vision/visits", json={
        "kind": "dental", "visit_date": _days(-120), "provider": "Dr. Rao", "summary": "Cleaning"})
    c.post("/api/dental-vision/visits", json={
        "kind": "eye", "visit_date": _days(-40), "provider": "City Optics"})
    allv = c.get("/api/dental-vision/visits").get_json()["visits"]
    assert len(allv) == 2
    eye = c.get("/api/dental-vision/visits?kind=eye").get_json()["visits"]
    assert len(eye) == 1 and eye[0]["provider"] == "City Optics"


def test_visit_requires_valid_kind_and_date(app):
    c = _reg(app, "dv2@medeasy.test")
    assert c.post("/api/dental-vision/visits",
                  json={"kind": "toenail", "visit_date": _days(-1)}).status_code == 400
    assert c.post("/api/dental-vision/visits",
                  json={"kind": "dental", "visit_date": "not-a-date"}).status_code == 400
    assert c.post("/api/dental-vision/visits",
                  json={"kind": "dental", "visit_date": _days(-1), "next_due": "soon"}).status_code == 400


def test_due_echoes_recorded_next_date_with_countdown(app):
    c = _reg(app, "dv3@medeasy.test")
    # A dental checkup with a next-due 20 days out, and an eye exam overdue.
    c.post("/api/dental-vision/visits", json={
        "kind": "dental", "visit_date": _days(-160), "next_due": _days(20)})
    c.post("/api/dental-vision/visits", json={
        "kind": "eye", "visit_date": _days(-400), "next_due": _days(-5)})
    due = {d["kind"]: d for d in c.get("/api/dental-vision/due").get_json()["due"]}
    assert due["dental"]["days_until"] == 20 and due["dental"]["due_soon"] is True
    assert due["dental"]["overdue"] is False
    assert due["eye"]["overdue"] is True and due["eye"]["days_until"] == -5


def test_due_uses_latest_visit_next_date(app):
    c = _reg(app, "dv4@medeasy.test")
    # Two dental visits; the newer one's next_due should drive the countdown.
    c.post("/api/dental-vision/visits", json={
        "kind": "dental", "visit_date": _days(-300), "next_due": _days(-100)})
    c.post("/api/dental-vision/visits", json={
        "kind": "dental", "visit_date": _days(-30), "next_due": _days(150)})
    due = c.get("/api/dental-vision/due").get_json()["due"]
    dental = next(d for d in due if d["kind"] == "dental")
    assert dental["days_until"] == 150      # from the newer visit, not the old overdue one


def test_visit_accepts_explicit_null_next_due(app):
    # The frontend sends next_due: null for a blank optional field — that must
    # be treated as "no next-due", not the string "None" (a 400 regression).
    c = _reg(app, "dv8@medeasy.test")
    r = c.post("/api/dental-vision/visits", json={
        "kind": "dental", "visit_date": _days(-2), "provider": "Dr. Null", "next_due": None})
    assert r.status_code == 200 and r.get_json()["success"] is True
    assert c.get("/api/dental-vision/visits").get_json()["visits"][0]["next_due"] in (None, "")


def test_prescription_stored_verbatim(app):
    c = _reg(app, "dv5@medeasy.test")
    # Optical values must be preserved exactly — including "PL" (plano) and signs —
    # never coerced to a number.
    c.post("/api/dental-vision/rx", json={
        "rx_date": _days(-10), "kind": "glasses",
        "right_sph": "-2.25", "right_cyl": "-0.50", "right_axis": "180",
        "left_sph": "PL", "left_cyl": "", "pd": "62"})
    rx = c.get("/api/dental-vision/rx").get_json()["prescriptions"]
    assert len(rx) == 1
    assert rx[0]["right_sph"] == "-2.25" and rx[0]["left_sph"] == "PL"
    assert rx[0]["right_axis"] == "180" and rx[0]["pd"] == "62"


def test_prescription_requires_valid_date(app):
    c = _reg(app, "dv6@medeasy.test")
    assert c.post("/api/dental-vision/rx", json={"rx_date": "whenever"}).status_code == 400


def test_everything_is_user_scoped(app):
    a = _reg(app, "dv7a@medeasy.test")
    b = _reg(app, "dv7b@medeasy.test")
    v = a.post("/api/dental-vision/visits", json={
        "kind": "dental", "visit_date": _days(-1)}).get_json()["visit"]
    a.post("/api/dental-vision/rx", json={"rx_date": _days(-1), "right_sph": "-1.00"})
    # B sees none of A's data.
    assert b.get("/api/dental-vision/visits").get_json()["visits"] == []
    assert b.get("/api/dental-vision/rx").get_json()["prescriptions"] == []
    assert b.get("/api/dental-vision/due").get_json()["due"] == []
    # B deleting A's visit id is a no-op for A.
    b.delete(f"/api/dental-vision/visits/{v['id']}")
    assert len(a.get("/api/dental-vision/visits").get_json()["visits"]) == 1


def test_requires_auth(app):
    anon = app.test_client()
    assert anon.get("/api/dental-vision/visits").status_code in (401, 403)
    assert anon.get("/api/dental-vision/rx").status_code in (401, 403)
    assert anon.get("/api/dental-vision/due").status_code in (401, 403)
