"""Trips, illness episodes and short courses.

Three states a life goes through that the app had no way to represent:

Crossing a time zone. A dose is a wall-clock time and "now" came from the
profile, so flying somewhere else meant reminders kept firing on home time and a
tablet taken at breakfast in Tokyo was filed against yesterday.

A bout of illness. Symptoms were a flat stream, so "when did this start?" — the
first question in every consultation — had to be reconstructed from memory.

A short course. The end date was stored and nothing read it, so there was no
answer to "how far through am I".

The recurring constraint in all three: report the arithmetic, never the advice.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today

PW = "situ-pw-12345"


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


def _days(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


# ── Trips ───────────────────────────────────────────────────────────────────

def test_a_trip_takes_over_the_apps_clock(app):
    """This is the whole point: one chokepoint decides what time it is, so a
    trip moves reminders, "today" and every date_key with the user."""
    from db.trips import create_trip
    from db.food import get_user_timezone, get_home_timezone, update_profile
    _, uid = _uid(app, "situ1@medeasy.test")
    with user_context(uid):
        update_profile({"timezone": "Asia/Kolkata"})
        assert get_user_timezone() == "Asia/Kolkata"
        create_trip({"label": "Tokyo", "timezone": "Asia/Tokyo",
                     "start_date": _days(-1), "end_date": _days(5)})
        assert get_user_timezone() == "Asia/Tokyo", "the trip must win while it runs"
        assert get_home_timezone() == "Asia/Kolkata", "home must still be knowable"


def test_a_finished_trip_gives_the_clock_back(app):
    from db.trips import create_trip
    from db.food import get_user_timezone, update_profile
    _, uid = _uid(app, "situ2@medeasy.test")
    with user_context(uid):
        update_profile({"timezone": "Asia/Kolkata"})
        create_trip({"label": "Past", "timezone": "Asia/Tokyo",
                     "start_date": _days(-30), "end_date": _days(-20)})
        assert get_user_timezone() == "Asia/Kolkata"


def test_an_upcoming_trip_does_not_move_the_clock_yet(app):
    from db.trips import create_trip
    from db.food import get_user_timezone, update_profile
    _, uid = _uid(app, "situ3@medeasy.test")
    with user_context(uid):
        update_profile({"timezone": "Asia/Kolkata"})
        create_trip({"label": "Later", "timezone": "Europe/London",
                     "start_date": _days(10), "end_date": _days(20)})
        assert get_user_timezone() == "Asia/Kolkata"


def test_an_unknown_time_zone_is_refused(app):
    """Storing a bad zone would make every later 'what time is it' call fall
    back to the server clock — silently, which is the bug this prevents."""
    from db.trips import create_trip
    _, uid = _uid(app, "situ4@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_trip({"timezone": "Mars/Olympus", "start_date": _days(0),
                         "end_date": _days(3)})


def test_trip_dates_are_validated(app):
    from db.trips import create_trip
    _, uid = _uid(app, "situ5@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_trip({"timezone": "Asia/Tokyo", "start_date": _days(5),
                         "end_date": _days(1)})            # ends before it starts
        with pytest.raises(ValueError):
            create_trip({"timezone": "Asia/Tokyo", "start_date": _days(0),
                         "end_date": _days(500)})          # longer than a year


def test_the_dose_clock_shows_both_times_and_recommends_nothing(app):
    """Whether to move an 8am tablet to 8am local is a medical question, and a
    consequential one for insulin or anticoagulants. Show the shift; say nothing
    about what to do with it."""
    from db.trips import create_trip, dose_clock
    c, uid = _uid(app, "situ6@medeasy.test")
    c.post("/api/medicines", json={"name": "Warfarin", "frequency": "once_daily",
                                   "times": ["08:00"]})
    with user_context(uid):
        create_trip({"label": "Tokyo", "timezone": "Asia/Tokyo",
                     "start_date": _days(-1), "end_date": _days(5)})
        clock = dose_clock("Asia/Kolkata")
    assert clock["has_trip"] is True
    assert clock["shift_minutes"] == 210          # IST +5:30 → JST +9:00
    dose = next(d for d in clock["doses"] if d["medicine"] == "Warfarin")
    assert dose["home_time"] == "08:00"
    assert dose["same_moment_local"] == "11:30"
    blob = " ".join(str(v) for v in clock.values()).lower()
    for word in ("should", "recommend", "we suggest", "take it at"):
        assert word not in blob, f"the clock must not advise: found {word!r}"


def test_no_trip_means_no_clock_comparison(app):
    from db.trips import dose_clock
    _, uid = _uid(app, "situ7@medeasy.test")
    with user_context(uid):
        assert dose_clock("Asia/Kolkata") == {"has_trip": False}


def test_a_trip_feeds_the_supply_planner_that_already_existed(app):
    c, uid = _uid(app, "situ8@medeasy.test")
    c.post("/api/medicines", json={"name": "Metformin", "frequency": "once_daily",
                                   "times": ["09:00"]})
    tid = c.post("/api/trips", json={"label": "Goa", "timezone": "Asia/Kolkata",
                                     "start_date": _days(1), "end_date": _days(7)}
                 ).get_json()["trip"]["id"]
    plan = c.get(f"/api/trips/{tid}/supply").get_json()
    assert plan["ok"] is True and plan["trip_days"] == 7


def test_trips_are_scoped_per_user(app):
    ca, _ = _uid(app, "situ9a@medeasy.test")
    cb, _ = _uid(app, "situ9b@medeasy.test")
    ca.post("/api/trips", json={"label": "Mine", "timezone": "Asia/Tokyo",
                                "start_date": _days(0), "end_date": _days(2)})
    assert cb.get("/api/trips").get_json()["trips"] == []


# ── Illness episodes ────────────────────────────────────────────────────────

def test_an_episode_reads_back_what_was_logged_in_its_window(app):
    from db.episodes import create_episode, episode_summary
    c, uid = _uid(app, "situ10@medeasy.test")
    today = user_today()
    with user_context(uid):
        from db.health import log_symptom, log_vital
        log_symptom({"name": "Fever", "severity": 8, "date_key": today})
        log_symptom({"name": "Cough", "severity": 4, "date_key": today})
        log_vital({"type": "temperature", "value1": 39.2, "date_key": today})
        ep = create_episode({"name": "Flu", "started_on": today})
        s = episode_summary(ep["id"])
    names = [x["name"] for x in s["symptoms"]]
    assert names == ["Fever", "Cough"], "worst first"
    assert s["symptoms"][0]["worst"] == 8
    assert s["peak_temperature_c"] == 39.2
    assert s["ongoing"] is True


def test_a_symptom_outside_the_window_is_not_swept_in(app):
    from db.episodes import create_episode, episode_summary
    c, uid = _uid(app, "situ11@medeasy.test")
    with user_context(uid):
        from db.health import log_symptom
        log_symptom({"name": "Unrelated", "severity": 3, "date_key": _days(-40)})
        log_symptom({"name": "InWindow", "severity": 5, "date_key": _days(-2)})
        ep = create_episode({"name": "Cold", "started_on": _days(-3),
                             "ended_on": _days(-1)})
        s = episode_summary(ep["id"])
    assert [x["name"] for x in s["symptoms"]] == ["InWindow"]


def test_days_logged_is_reported_next_to_days_long(app):
    """A quiet day means nothing was written down, which is not the same as
    nothing happening — so both numbers are shown."""
    from db.episodes import create_episode, episode_summary
    c, uid = _uid(app, "situ12@medeasy.test")
    with user_context(uid):
        from db.health import log_symptom
        log_symptom({"name": "Ache", "severity": 3, "date_key": _days(-5)})
        ep = create_episode({"name": "Bug", "started_on": _days(-6),
                             "ended_on": _days(-1)})
        s = episode_summary(ep["id"])
    assert s["days"] == 6
    assert s["days_logged"] == 1


def test_deleting_an_episode_keeps_every_symptom(app):
    """Only the grouping goes. Losing the underlying records would make the
    feature actively dangerous."""
    from db.episodes import create_episode, delete_episode
    c, uid = _uid(app, "situ13@medeasy.test")
    today = user_today()
    with user_context(uid):
        from db.health import log_symptom
        log_symptom({"name": "Keepme", "severity": 5, "date_key": today})
        ep = create_episode({"name": "Whatever", "started_on": today})
        delete_episode(ep["id"])
        left = execute("SELECT COUNT(*) AS n FROM symptoms WHERE user_id=? AND name=?",
                       (uid, "Keepme"), fetchone=True)["n"]
    assert left == 1


def test_an_episode_needs_a_name_and_sane_dates(app):
    from db.episodes import create_episode
    _, uid = _uid(app, "situ14@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_episode({"name": "  "})
        with pytest.raises(ValueError):
            create_episode({"name": "x", "started_on": _days(0), "ended_on": _days(-5)})


def test_ending_an_episode_never_lands_before_it_started(app):
    from db.episodes import create_episode, end_episode
    _, uid = _uid(app, "situ15@medeasy.test")
    with user_context(uid):
        ep = create_episode({"name": "Bout", "started_on": _days(-1)})
        ended = end_episode(ep["id"], _days(-10))
    assert ended["ended_on"] == ep["started_on"]


def test_episodes_are_scoped_per_user(app):
    ca, _ = _uid(app, "situ16a@medeasy.test")
    cb, _ = _uid(app, "situ16b@medeasy.test")
    ca.post("/api/episodes", json={"name": "Mine", "started_on": user_today()})
    assert cb.get("/api/episodes").get_json()["episodes"] == []


# ── Courses ─────────────────────────────────────────────────────────────────

def test_a_course_reports_progress_as_arithmetic(app):
    from db.courses import list_courses
    c, uid = _uid(app, "situ17@medeasy.test")
    c.post("/api/medicines", json={"name": "Amoxicillin", "frequency": "twice_daily",
                                   "times": ["08:00", "20:00"],
                                   "start_date": _days(-2), "end_date": _days(4)})
    with user_context(uid):
        course = list_courses()[0]
    assert course["total_days"] == 7
    assert course["doses_per_day"] == 2
    assert course["doses_scheduled"] == 14
    # Three days elapsed (start, +1, today) × 2 a day.
    assert course["doses_due_so_far"] == 6
    assert course["days_left"] == 4
    assert course["finished"] is False


def test_an_open_ended_medicine_is_not_a_course(app):
    """A daily blood-pressure tablet has no end date; showing it as 12% complete
    would be noise."""
    from db.courses import list_courses
    c, uid = _uid(app, "situ18@medeasy.test")
    c.post("/api/medicines", json={"name": "Amlodipine", "frequency": "once_daily",
                                   "times": ["08:00"]})
    with user_context(uid):
        assert list_courses() == []


def test_a_year_long_prescription_is_not_a_course(app):
    from db.courses import list_courses
    c, uid = _uid(app, "situ19@medeasy.test")
    c.post("/api/medicines", json={"name": "LongTerm", "frequency": "once_daily",
                                   "times": ["08:00"], "start_date": _days(-10),
                                   "end_date": _days(300)})
    with user_context(uid):
        assert list_courses() == []


def test_stopping_early_is_stated_as_a_fact_not_an_instruction(app):
    """"Finish the course" is a clinical instruction, is not always right, and
    is not this app's to give."""
    from db.courses import list_courses
    c, uid = _uid(app, "situ20@medeasy.test")
    c.post("/api/medicines", json={"name": "Flucloxacillin", "frequency": "once_daily",
                                   "times": ["08:00"], "start_date": _days(-10),
                                   "end_date": _days(-4)})
    with user_context(uid):
        course = list_courses()[0]
    assert course["finished"] is True
    assert course["stopped_early"] is True
    assert course["doses_taken"] == 0
    assert "advice" not in course and "recommendation" not in course


def test_an_as_needed_medicine_is_never_a_course(app):
    from db.courses import list_courses
    c, uid = _uid(app, "situ21@medeasy.test")
    c.post("/api/medicines", json={"name": "Paracetamol", "frequency": "as_needed",
                                   "start_date": _days(-3), "end_date": _days(3)})
    with user_context(uid):
        assert list_courses() == []


# ── Disposal ────────────────────────────────────────────────────────────────

def test_disposal_guidance_refuses_to_invent_local_rules(app):
    """The app knows a country well enough to pick a currency symbol. Inventing
    a disposal regulation from that would be worse than saying less."""
    c, _ = _uid(app, "situ22@medeasy.test")
    g = c.get("/api/medicines/disposal").get_json()
    assert g["steps"] and g["ask_first"]
    assert "does not know" in g["not_advice"].lower()
    blob = " ".join(g["steps"]).lower()
    for claim in ("law requires", "regulation", "you must by law", "illegal"):
        assert claim not in blob, f"invented a legal claim: {claim!r}"


def test_expiry_still_answered_by_the_endpoint_that_already_existed(app):
    """Guarding against re-adding a duplicate: /api/medicines/expiring predates
    this work and remains the single answer to which medicines are out of date."""
    c, _ = _uid(app, "situ23@medeasy.test")
    r = c.get("/api/medicines/expiring")
    assert r.status_code == 200
    assert {"expired", "soon"} <= set(r.get_json())


# ── Routes ──────────────────────────────────────────────────────────────────

def test_routes_require_auth(app):
    anon = app.test_client()
    for path in ("/api/trips", "/api/trips/clock", "/api/episodes",
                 "/api/courses", "/api/medicines/disposal"):
        assert anon.get(path).status_code == 401, path
