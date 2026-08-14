"""K3 — pill burden / deprescribing prompt. Total pills/day across active meds +
medicine count, with a polypharmacy review nudge at the threshold. From the
user's own list; never advises stopping anything."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import insert_medicine, get_pill_burden

PW = "pbur-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def _stock(mid, per_dose):
    execute("UPDATE medicines SET pills_per_dose=? WHERE id=?", (per_dose, mid), commit=True)


def test_empty(app):
    _, uid = _uid(app, "pbur1@medeasy.test")
    with user_context(uid):
        d = get_pill_burden()
    assert d["has_data"] is False


def test_daily_pill_sum(app):
    _, uid = _uid(app, "pbur2@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "A", "frequency": "twice_daily", "times": ["09:00", "21:00"]})  # 2/day
        m = insert_medicine({"name": "B", "frequency": "once_daily", "times": ["09:00"]})         # 1/day
        _stock(m["id"], 2)     # 2 pills per dose → 2/day
        d = get_pill_burden()
    assert d["daily_pills"] == 4.0        # 2 + 2
    assert d["medicine_count"] == 2
    assert d["polypharmacy"] is False


def test_weekly_med_counts_fractionally(app):
    _, uid = _uid(app, "pbur3@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Wk", "frequency": "once_daily", "times": ["09:00"],
                         "schedule_days": [0]})       # Mondays only → 1/7 per day
        d = get_pill_burden()
    assert d["daily_pills"] == round(1 / 7.0, 1)


def test_polypharmacy_flag(app):
    _, uid = _uid(app, "pbur4@medeasy.test")
    with user_context(uid):
        for i in range(5):
            insert_medicine({"name": f"M{i}", "frequency": "once_daily", "times": ["09:00"]})
        d = get_pill_burden()
    assert d["medicine_count"] == 5 and d["polypharmacy"] is True


def test_as_needed_counted_but_not_in_daily_pills(app):
    _, uid = _uid(app, "pbur5@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Daily", "frequency": "once_daily", "times": ["09:00"]})
        insert_medicine({"name": "PRN", "frequency": "as_needed"})
        d = get_pill_burden()
    assert d["medicine_count"] == 2 and d["as_needed_count"] == 1
    assert d["daily_pills"] == 1.0     # PRN adds nothing to the daily total


def test_api(app):
    c, uid = _uid(app, "pbur6@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "A", "frequency": "once_daily", "times": ["09:00"]})
        insert_medicine({"name": "B", "frequency": "once_daily", "times": ["09:00"]})
    body = c.get("/api/medicines/pill-burden").get_json()
    assert body["has_data"] is True and body["medicine_count"] == 2
