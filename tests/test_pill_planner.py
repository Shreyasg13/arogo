"""Weekly pill planner: days×times grid of the upcoming plan."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "plan-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "plan@medeasy.test", "password": PW})
    return c


def test_planner_builds_time_rows_and_day_columns(client):
    client.post("/api/medicines", json={
        "name": "Metformin", "dosage": "500", "unit": "mg", "timing": "with_food",
        "frequency": "twice_daily", "times": ["09:00", "21:00"]})
    client.post("/api/medicines", json={
        "name": "Aspirin", "frequency": "once_daily", "times": ["09:00"]})

    p = client.get("/api/medicines/planner?days=7").get_json()
    assert p["has_schedule"] is True
    assert len(p["days"]) == 7 and p["days"][0]["is_today"] is True
    # rows are the union of scheduled times, sorted
    assert [r["time"] for r in p["rows"]] == ["09:00", "21:00"]
    # the 9am row on today (column 0) holds both meds; 9pm holds only Metformin
    row9 = next(r for r in p["rows"] if r["time"] == "09:00")
    names_today = sorted(m["name"] for m in row9["cells"][0])
    assert names_today == ["Aspirin", "Metformin"]
    row21 = next(r for r in p["rows"] if r["time"] == "21:00")
    assert [m["name"] for m in row21["cells"][0]] == ["Metformin"]
    # timing label rides along on the chip
    metf = next(m for m in row9["cells"][0] if m["name"] == "Metformin")
    assert metf["timing_text"] == "with food" and metf["dose"] == "500 mg"


def test_planner_respects_course_window(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "plan2@medeasy.test", "password": PW})
    # A med that ends tomorrow shouldn't appear on later days.
    end = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    c.post("/api/medicines", json={
        "name": "Antibiotic", "frequency": "once_daily", "times": ["08:00"],
        "end_date": end})
    p = c.get("/api/medicines/planner?days=7").get_json()
    row = next(r for r in p["rows"] if r["time"] == "08:00")
    assert len(row["cells"][0]) == 1        # today: due
    assert len(row["cells"][1]) == 1        # tomorrow (end day): due
    assert row["cells"][3] == []            # 3 days out: course ended


def test_planner_excludes_as_needed_meds(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "plan3@medeasy.test", "password": PW})
    c.post("/api/medicines", json={"name": "Painkiller", "frequency": "as_needed"})
    p = c.get("/api/medicines/planner").get_json()
    assert p["has_schedule"] is False and p["rows"] == []


def test_planner_requires_auth(app):
    assert app.test_client().get("/api/medicines/planner").status_code == 401
