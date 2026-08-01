"""As-needed (PRN) medicines: no schedule, log a dose on demand, stock decrements,
and rescue doses never count against scheduled adherence."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "prn-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "prn@medeasy.test", "password": PW})
    return c


def _meds(client):
    return {m["id"]: m for m in client.get("/api/medicines").get_json()}


def test_as_needed_has_no_schedule(client):
    m = client.post("/api/medicines", json={
        "name": "Sumatriptan", "dosage": "50", "unit": "mg",
        "frequency": "as_needed", "times": ["09:00"]}).get_json()["medicine"]
    assert m["frequency"] == "as_needed"
    assert m["times"] == []                                  # times ignored for PRN
    # It never appears in the daily scheduled doses…
    assert not any(d["med_id"] == m["id"] for d in client.get("/api/medicines/today").get_json())


def test_take_now_logs_and_decrements_stock(client):
    m = client.post("/api/medicines", json={
        "name": "Salbutamol", "dosage": "100", "unit": "mcg",
        "frequency": "as_needed"}).get_json()["medicine"]
    client.post(f"/api/medicines/{m['id']}/stock",
                json={"pill_count": 10, "pills_per_dose": 1, "refill_threshold": 3})
    r = client.post(f"/api/medicines/{m['id']}/take-now")
    assert r.status_code == 200 and r.get_json()["success"]
    assert r.get_json()["taken_today"] >= 1
    meds = _meds(client)
    assert meds[m["id"]]["pill_count"] == 9                  # one puff consumed
    assert meds[m["id"]]["taken_today"] >= 1
    assert meds[m["id"]]["last_taken"]


def test_prn_dose_does_not_count_against_adherence(client):
    # Adherence is about SCHEDULED doses. A rescue dose has no schedule, so it
    # must change neither the denominator nor the count of scheduled 'taken'.
    before = client.get("/api/medicines/adherence").get_json()   # {total, taken, pct}
    m = client.post("/api/medicines", json={
        "name": "Antacid", "dosage": "1", "unit": "tablet",
        "frequency": "as_needed"}).get_json()["medicine"]
    client.post(f"/api/medicines/{m['id']}/take-now")
    after = client.get("/api/medicines/adherence").get_json()
    assert after["total"] == before["total"]                     # no scheduled slots added
    assert after["taken"] == before["taken"]                     # rescue dose isn't a scheduled taken


def test_take_now_unknown_medicine_404(client):
    assert client.post("/api/medicines/deadbeef/take-now").status_code == 404
