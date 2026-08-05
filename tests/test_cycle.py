"""Menstrual cycle tracking — everything derived from the sequence of period
starts, predictions only with enough history, all framed as estimates."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context
from db.cycle import log_period_start, log_period_end, get_cycle_summary, delete_cycle

PW = "cycle-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    from db.core import execute
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def _day(offset):
    return (dt.date.today() - dt.timedelta(days=offset)).isoformat()


def test_no_data_is_empty(app):
    _, uid = _uid(app, "cyc0@medeasy.test")
    with user_context(uid):
        s = get_cycle_summary()
    assert s["has_data"] is False
    assert s["predicted_next_start"] is None


def test_single_start_is_ongoing_with_no_prediction(app):
    _, uid = _uid(app, "cyc1@medeasy.test")
    with user_context(uid):
        s = log_period_start(_day(2))       # started 2 days ago, no end
    assert s["has_data"] is True
    assert s["ongoing"] is True
    assert s["ongoing_day"] == 3            # day 1 = start day
    assert s["predicted_next_start"] is None   # need >=2 cycles


def test_two_cycles_predict_next_start(app):
    _, uid = _uid(app, "cyc2@medeasy.test")
    with user_context(uid):
        log_period_start(_day(30))          # ~one cycle ago
        s = log_period_start(_day(2))       # 28 days later
    assert s["cycle_length"] == 28
    # next ≈ last start (2 days ago) + 28 = 26 days out
    assert s["days_until_next"] == pytest.approx(26, abs=1)
    assert s["predicted_next_start"] is not None


def test_period_length_from_start_and_end(app):
    _, uid = _uid(app, "cyc3@medeasy.test")
    with user_context(uid):
        log_period_start(_day(10))
        s = log_period_end(_day(6))         # 10th → 6th inclusive = 5 days
    assert s["period_length"] == 5


def test_end_before_start_is_rejected(app):
    _, uid = _uid(app, "cyc4@medeasy.test")
    with user_context(uid):
        log_period_start(_day(3))
        with pytest.raises(ValueError):
            log_period_end(_day(9))         # earlier than the start


def test_start_is_idempotent_per_date(app):
    _, uid = _uid(app, "cyc5@medeasy.test")
    with user_context(uid):
        log_period_start(_day(4), notes="cramps")
        log_period_start(_day(4), notes="updated")   # same date again
        s = get_cycle_summary()
    assert len(s["history"]) == 1           # not duplicated


def test_api_round_trip(app):
    c, uid = _uid(app, "cyc6@medeasy.test")
    assert c.post("/api/cycle/start", json={"start_date": _day(1)}).status_code == 200
    r = c.get("/api/cycle").get_json()
    assert r["has_data"] is True and r["ongoing"] is True
    # bad date rejected
    assert c.post("/api/cycle/start", json={"start_date": "not-a-date"}).status_code == 400


def test_fertile_window_needs_two_cycles(app):
    _, uid = _uid(app, "cyc7@medeasy.test")
    with user_context(uid):
        s = log_period_start(_day(2))          # single cycle → no prediction, no fertility
    assert s["fertility"] is None


def test_fertile_window_estimate(app):
    _, uid = _uid(app, "cyc8@medeasy.test")
    with user_context(uid):
        log_period_start(_day(30))
        s = log_period_start(_day(2))          # 28-day cycle, last start 2 days ago
    f = s["fertility"]
    assert f is not None and f["estimate_only"] is True
    # next start ≈ today+26; ovulation = next−14 ≈ today+12
    next_d = dt.date.fromisoformat(s["predicted_next_start"])
    assert f["ovulation"] == (next_d - dt.timedelta(days=14)).isoformat()
    assert f["window_start"] == (next_d - dt.timedelta(days=19)).isoformat()   # ovulation−5
    assert f["window_end"] == (next_d - dt.timedelta(days=13)).isoformat()     # ovulation+1
    assert f["days_to_ovulation"] == pytest.approx(12, abs=1)
    assert f["in_window"] is False             # ovulation ~12 days out


def test_fertile_window_suppressed_for_short_cycles(app):
    _, uid = _uid(app, "cyc9@medeasy.test")
    with user_context(uid):
        log_period_start(_day(38))
        s = log_period_start(_day(20))         # 18-day cycle (<21) → suppressed
    assert s["cycle_length"] == 18
    assert s["fertility"] is None              # −14 model is nonsense here; honest None
