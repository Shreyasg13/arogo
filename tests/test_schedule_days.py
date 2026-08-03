"""Day-of-week medication scheduling.

The core guarantee: a medicine with a day-of-week schedule is due ONLY on those
weekdays — in the today view, in adherence math, and (because the scheduler reads
get_today_doses) in reminders. Before this, every timed med was due seven days a
week, so a weekly medicine manufactured six false missed-doses per week.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context
from db.medicines import (clean_schedule_days, clean_interval_days, insert_medicine,
                          get_today_doses, get_adherence_stats, _days_of_supply,
                          _scheduled_on_day)

PW = "sched-pw-12345"


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


# ── clean_schedule_days normalisation ────────────────────────────────────────
def test_clean_schedule_days_normalises():
    assert clean_schedule_days([2, 0, 0, 5]) == [0, 2, 5]     # dedupe + sort
    assert clean_schedule_days([]) is None                    # empty → daily
    assert clean_schedule_days(None) is None
    assert clean_schedule_days([0, 1, 2, 3, 4, 5, 6]) is None  # all week → daily
    assert clean_schedule_days([9, -1, 'x']) is None          # invalid → daily
    assert clean_schedule_days(['1', '3']) == [1, 3]          # coerces strings


# ── The bug fix: due only on scheduled weekdays ──────────────────────────────
def test_med_due_only_on_scheduled_weekday(app):
    c, uid = _uid(app, "sched1@medeasy.test")
    today_wd = dt.date.today().weekday()
    other_wd = (today_wd + 1) % 7
    with user_context(uid):
        insert_medicine({"name": "TodayMed", "times": ["09:00"],
                         "schedule_days": [today_wd]})
        insert_medicine({"name": "OtherDayMed", "times": ["09:00"],
                         "schedule_days": [other_wd]})
        insert_medicine({"name": "DailyMed", "times": ["09:00"]})   # no schedule
        names = {d["med_name"] for d in get_today_doses()}
    assert "TodayMed" in names
    assert "DailyMed" in names
    assert "OtherDayMed" not in names        # the fix: not due today


def test_adherence_does_not_penalise_off_days(app):
    c, uid = _uid(app, "sched2@medeasy.test")
    today_wd = dt.date.today().weekday()
    other_wd = (today_wd + 3) % 7
    # start the course well before the window so every day in it is "in course".
    old_start = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    with user_context(uid):
        insert_medicine({"name": "WeeklyMed", "times": ["09:00"],
                         "schedule_days": [other_wd], "start_date": old_start})
        stats = get_adherence_stats(days=7)
    # Over any 7-day window a once-weekly med is scheduled exactly once → 1
    # expected dose, not 7. Without the fix this was 7 (six false misses).
    assert stats["total"] == 1


def test_days_of_supply_scales_with_schedule():
    # _days_of_supply is a pure function of the med dict — no DB needed.
    daily = {"pill_count": 30, "pills_per_dose": 1, "times": ["09:00"],
             "frequency": "once_daily", "schedule_days": None}
    weekly = {"pill_count": 30, "pills_per_dose": 1, "times": ["09:00"],
              "frequency": "once_daily", "schedule_days": [0]}
    # 30 pills, one a day ≈ 30 days; one a week ≈ 30 × 7 = 210 days.
    assert _days_of_supply(daily) == pytest.approx(30, abs=1)
    assert _days_of_supply(weekly) == pytest.approx(210, abs=5)


def test_clean_interval_days_normalises():
    assert clean_interval_days(2) == 2
    assert clean_interval_days("3") == 3
    assert clean_interval_days(1) is None      # 1 is just 'daily'
    assert clean_interval_days(0) is None
    assert clean_interval_days(None) is None
    assert clean_interval_days(999) is None    # out of range
    assert clean_interval_days("x") is None


def test_interval_med_due_every_n_days():
    start = "2026-08-01"
    m = {"interval_days": 2, "start_date": start, "schedule_days": None}
    assert _scheduled_on_day(m, "2026-08-01") is True    # day 0
    assert _scheduled_on_day(m, "2026-08-02") is False   # day 1
    assert _scheduled_on_day(m, "2026-08-03") is True    # day 2
    assert _scheduled_on_day(m, "2026-08-09") is True    # day 8
    # before the course starts → not due
    assert _scheduled_on_day(m, "2026-07-31") is False


def test_interval_days_of_supply_and_mutual_exclusion(app):
    # Supply: alternate-day med lasts ~2× the daily rate.
    alt = {"pill_count": 30, "pills_per_dose": 1, "times": ["09:00"],
           "interval_days": 2, "schedule_days": None, "frequency": "once_daily"}
    assert _days_of_supply(alt) == pytest.approx(60, abs=2)

    # Interval and weekdays are mutually exclusive — sending both keeps interval,
    # drops the days.
    c, uid = _uid(app, "sched5@medeasy.test")
    r = c.post("/api/medicines", json={"name": "AltDay", "times": ["09:00"],
                                       "interval_days": 2, "schedule_days": [0, 3]})
    med = r.get_json()["medicine"]
    assert med["interval_days"] == 2
    assert med["schedule_days"] is None


def test_api_round_trips_schedule_days(app):
    c, uid = _uid(app, "sched4@medeasy.test")
    r = c.post("/api/medicines", json={"name": "RxWeekly", "times": ["08:00"],
                                       "schedule_days": [0, 3]})
    assert r.status_code in (200, 201)
    med = r.get_json()["medicine"]
    assert med["schedule_days"] == [0, 3]
    # And a plain daily med reports None (not a redundant [0..6]).
    r2 = c.post("/api/medicines", json={"name": "RxDaily", "times": ["08:00"]})
    assert r2.get_json()["medicine"]["schedule_days"] is None
