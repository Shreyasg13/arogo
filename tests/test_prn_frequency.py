"""J4 — PRN / rescue-med frequency. How often the user reaches for an as-needed
medicine, by week, with a 'more than usual' flag vs the recent baseline. Own dose
logs only; a heads-up, never a diagnosis."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.medicines import insert_medicine, get_prn_frequency

PW = "prn-pw-123456"


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


def _prn_dose(uid, mid, day):
    execute("""INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at,user_id)
               VALUES (?,?,?,?,1,?,?)""",
            (new_id(), mid, day, "14:30:00", f"{day}T14:30:00", uid), commit=True)


def test_empty_without_prn_meds(app):
    _, uid = _uid(app, "prn1@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Daily", "frequency": "once_daily", "times": ["09:00"]})
        d = get_prn_frequency()
    assert d["has_data"] is False


def test_counts_by_week(app):
    _, uid = _uid(app, "prn2@medeasy.test")
    today = dt.date.today()
    with user_context(uid):
        mid = insert_medicine({"name": "Inhaler", "frequency": "as_needed"})["id"]
        _prn_dose(uid, mid, today.isoformat())                              # this week
        _prn_dose(uid, mid, (today - dt.timedelta(days=1)).isoformat())     # this week
        _prn_dose(uid, mid, (today - dt.timedelta(days=8)).isoformat())     # last week
        d = get_prn_frequency()
    m = d["meds"][0]
    assert m["name"] == "Inhaler"
    assert m["this_week"] == 2 and m["total"] == 3
    assert len(m["weekly"]) == 8 and m["weekly"][-1] == 2   # newest last


def test_elevated_flag_when_well_above_baseline(app):
    _, uid = _uid(app, "prn3@medeasy.test")
    today = dt.date.today()
    with user_context(uid):
        mid = insert_medicine({"name": "Rescue", "frequency": "as_needed"})["id"]
        # Prior weeks: ~1/week. This week: 6 → clearly elevated.
        for w in range(1, 5):
            _prn_dose(uid, mid, (today - dt.timedelta(days=7 * w)).isoformat())
        for i in range(6):
            _prn_dose(uid, mid, (today - dt.timedelta(days=i % 7)).isoformat())
        d = get_prn_frequency()
    m = d["meds"][0]
    assert m["this_week"] == 6 and m["elevated"] is True
    assert d["any_elevated"] is True


def test_normal_week_not_flagged(app):
    _, uid = _uid(app, "prn4@medeasy.test")
    today = dt.date.today()
    with user_context(uid):
        mid = insert_medicine({"name": "Steady", "frequency": "as_needed"})["id"]
        # ~2/week every week including this one → no spike.
        for w in range(0, 5):
            _prn_dose(uid, mid, (today - dt.timedelta(days=7 * w)).isoformat())
            _prn_dose(uid, mid, (today - dt.timedelta(days=7 * w + 1)).isoformat())
        d = get_prn_frequency()
    assert d["meds"][0]["elevated"] is False


def test_first_ever_use_not_flagged(app):
    _, uid = _uid(app, "prn5@medeasy.test")
    today = dt.date.today()
    with user_context(uid):
        mid = insert_medicine({"name": "New PRN", "frequency": "as_needed"})["id"]
        for i in range(4):     # 4 this week, no prior history
            _prn_dose(uid, mid, (today - dt.timedelta(days=i)).isoformat())
        d = get_prn_frequency()
    m = d["meds"][0]
    # A first-ever burst has no established "usual" (baseline 0) → not flagged.
    assert m["this_week"] == 4 and m["baseline_per_week"] == 0.0
    assert m["elevated"] is False


def test_api(app):
    c, uid = _uid(app, "prn6@medeasy.test")
    today = dt.date.today()
    with user_context(uid):
        mid = insert_medicine({"name": "PRN", "frequency": "as_needed"})["id"]
        _prn_dose(uid, mid, today.isoformat())
    body = c.get("/api/medicines/prn-frequency?weeks=8").get_json()
    assert body["has_data"] is True and body["meds"][0]["this_week"] == 1
