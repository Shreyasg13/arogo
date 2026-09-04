"""
tests/test_audit_wellness.py — Security/robustness audit of the WELLNESS domain
(routes/wellness.py, db/wellness.py, db/health.py habits): sleep, hydration,
thoughts/journal, todos/reminders, habits, body metrics.

Modeled on tests/test_audit_food.py and tests/test_stress_medical.py.

A hardening pass (commit 3b11287) added db.core.to_num/to_int/valid_date and
wired many write paths to coerce/clamp numbers and validate required strings.
This suite hammers the wellness write/read paths with hostile input and asserts
the CORRECT (post-fix) behaviour:

  - Malformed NUMERIC input (sleep quality, body weight/height/fat, hydration
    amount) -> coerced/clamped, never a 500 and never poison that bricks a
    later read.
  - Missing REQUIRED string identifiers (habit name, todo title, thought
    content) -> 400 from the route, not a KeyError/AttributeError 500.
  - Invalid explicit date_key -> defaulted to a navigable day (matching the
    "default missing/garbage date" style used elsewhere in wellness).

Tests NOT marked xfail assert behaviour that holds after the fixes and must
stay green. Any bug deliberately left unfixed is pinned with xfail + a reason.

Run:  pytest tests/test_audit_wellness.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import json
import datetime
import pytest

import auth as auth_module
from db.core import init_db, execute
from app import create_app

PW = "audit-pw-123456789"
DAY = "2026-07-12"
TODAY = datetime.date.today().isoformat()


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    # Let the JSON 500 handler answer instead of re-raising into the test —
    # the crash tests assert on the HTTP status of the endpoint.
    application.config["PROPAGATE_EXCEPTIONS"] = False
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


@pytest.fixture(autouse=True)
def clean_domain(app):
    yield
    for t in ["sleep_logs", "hydration_logs", "thoughts", "todos",
              "body_metrics", "habits", "habit_logs"]:
        try:
            execute("DELETE FROM %s" % t, commit=True)
        except Exception:
            pass


_counter = {"n": 0}


def _user(app, email=None):
    """Fresh registered+session'd client. Unique email each call unless given."""
    if email is None:
        _counter["n"] += 1
        email = f"welln-{_counter['n']}@medeasy.test"
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), (r.status_code, r.data[:120])
    return c


# ══════════════════════════════════════════════════════════════════════════════
# SLEEP — quality/date coercion, no 500, no poison
# ══════════════════════════════════════════════════════════════════════════════
class TestSleep:
    # BUG (HIGH) db/wellness.py:151 — int(data.get('quality',3)) 500s on a
    # non-numeric or None quality. FIXED: to_int(...,3,lo=1,hi=5).
    def test_nonnumeric_quality_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/sleep", json={"bedtime": "2026-07-12T23:00",
                                       "wake_time": "2026-07-13T07:00",
                                       "quality": "great", "date_key": DAY})
        assert r.status_code == 200
        assert r.get_json()["log"]["quality"] == 3  # coerced to default

    def test_none_quality_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/sleep", json={"bedtime": "2026-07-12T23:00",
                                       "wake_time": "2026-07-13T07:00",
                                       "quality": None, "date_key": DAY})
        assert r.status_code == 200

    def test_out_of_range_quality_clamped(self, app):
        c = _user(app)
        r = c.post("/api/sleep", json={"bedtime": "2026-07-12T23:00",
                                       "wake_time": "2026-07-13T07:00",
                                       "quality": 999, "date_key": DAY})
        assert r.status_code == 200
        assert 1 <= r.get_json()["log"]["quality"] <= 5

    def test_relogging_a_night_replaces_it_not_duplicates(self, app):
        """One night, one entry. Logging the same date again is a correction,
        not a second night — it must update the row, not stack a duplicate,
        so the history and the average reflect the latest values only."""
        c = _user(app, "sleep-upsert@medeasy.test")
        # Relative to today so the nights stay inside the API's rolling window —
        # absolute dates silently aged out of it and broke this test on any run
        # dated past them.
        import datetime as _dt
        night_d = _dt.date.today() - _dt.timedelta(days=2)
        night = night_d.isoformat()
        morning = (night_d + _dt.timedelta(days=1)).isoformat()
        for wake, q in [("06:30", 3), ("07:00", 4), ("07:30", 5)]:
            r = c.post("/api/sleep", json={"bedtime": night + "T23:00",
                                           "wake_time": morning + "T" + wake,
                                           "quality": q, "date_key": night})
            assert r.status_code == 200

        rows = [s for s in c.get("/api/sleep").get_json() if s["date_key"] == night]
        assert len(rows) == 1, f"re-logging duplicated the night: {len(rows)} rows"
        # The surviving row holds the LAST values (7h30m, quality 5)
        assert rows[0]["quality"] == 5
        assert rows[0]["duration_h"] == 8.5

        # A genuinely different night is still its own entry.
        prev_d = night_d - _dt.timedelta(days=1)
        prev = prev_d.isoformat()
        c.post("/api/sleep", json={"bedtime": prev + "T23:00",
                                   "wake_time": night + "T07:00",
                                   "quality": 4, "date_key": prev})
        nights = {s["date_key"] for s in c.get("/api/sleep").get_json()}
        assert {prev, night} <= nights

    def test_night_is_keyed_to_the_wake_date_not_bedtime(self, app):
        """A night is the morning you woke, so 11pm→7am and 1am→7am are the
        same night — even though one bedtime is before midnight and the other
        after. Without an explicit date_key the server derives it from the wake
        date, so re-logging replaces rather than splitting into two rows."""
        c = _user(app, "sleep-wakekey@medeasy.test")
        # Anchor to a recent morning so the row stays inside the default 14-day
        # read window (GET /api/sleep) — fixed calendar dates silently age out.
        wake_d = datetime.date.today() - datetime.timedelta(days=2)
        wake   = wake_d.isoformat()
        eve    = (wake_d - datetime.timedelta(days=1)).isoformat()
        c.post("/api/sleep", json={"bedtime": eve + "T23:00",       # 8h, bed before midnight
                                   "wake_time": wake + "T07:00", "quality": 4})
        c.post("/api/sleep", json={"bedtime": wake + "T01:00",      # 6h, bed after midnight
                                   "wake_time": wake + "T07:00", "quality": 3})
        rows = [s for s in c.get("/api/sleep").get_json() if s["date_key"] == wake]
        assert len(rows) == 1, "same wake morning split into two rows"
        assert rows[0]["duration_h"] == 6   # the replacement won

    # Garbage date_key must not orphan the log on a non-navigable day.
    def test_garbage_date_key_defaulted(self, app):
        c = _user(app)
        r = c.post("/api/sleep", json={"bedtime": "2026-07-12T23:00",
                                       "wake_time": "2026-07-13T07:00",
                                       "quality": 3, "date_key": "not-a-date"})
        assert r.status_code == 200
        dk = r.get_json()["log"]["date_key"]
        # Falls back to the bedtime date (2026-07-12), which IS a real date.
        datetime.date.fromisoformat(dk)  # raises if not a real ISO date

    def test_bad_quality_does_not_brick_trend(self, app):
        c = _user(app)
        c.post("/api/sleep", json={"bedtime": "2026-07-12T23:00",
                                   "wake_time": "2026-07-13T07:00",
                                   "quality": "meh", "date_key": DAY})
        # The trend endpoint sums quality — a stored string would 500 it.
        assert c.get("/api/sleep/trend").status_code == 200

    def test_trend_needs_a_week_before_it_calls_worsening(self, app):
        """A "worsening" verdict off two or three nights (really off one short
        night) is a false alarm the data can't support. Below a week of nights
        the trend is 'insufficient', not a red arrow."""
        import datetime as dt

        def log_night(client, morning_iso, wake_hhmm):
            morning = dt.date.fromisoformat(morning_iso)
            prev = (morning - dt.timedelta(days=1)).isoformat()
            client.post("/api/sleep", json={"bedtime": prev + "T23:00",
                                            "wake_time": morning_iso + "T" + wake_hhmm,
                                            "quality": 4, "date_key": morning_iso})

        # Three nights, the last one short — exactly what the old code flagged.
        # Dated relative to today (not hardcoded) so this doesn't age out of the
        # trend endpoint's `days` window as real time passes.
        today = dt.date.today()
        c = _user(app, "sleep-trend@medeasy.test")
        for offset, wake in [(3, "07:45"), (2, "07:45"), (1, "06:00")]:
            log_night(c, (today - dt.timedelta(days=offset)).isoformat(), wake)
        assert c.get("/api/sleep/trend?days=30").get_json()["stats"]["dur_trend"] \
            == "insufficient", "classified a trend off 3 nights"

        # Seven nights with a real decline in the second half → now it may speak.
        c2 = _user(app, "sleep-trend7@medeasy.test")
        for i, wake in enumerate(["07:00"] * 4 + ["04:00"] * 3):   # 8h ×4, then 5h ×3
            log_night(c2, (today - dt.timedelta(days=7 - i)).isoformat(), wake)
        assert c2.get("/api/sleep/trend?days=30").get_json()["stats"]["dur_trend"] \
            == "worsening"

    def test_duration_is_never_negative(self, app):
        c = _user(app)
        r = c.post("/api/sleep", json={"bedtime": "2026-07-12T23:00",
                                       "wake_time": "2026-07-13T07:00",
                                       "quality": 4, "date_key": DAY})
        assert r.get_json()["log"]["duration_h"] >= 0


# ══════════════════════════════════════════════════════════════════════════════
# HYDRATION — already hardened; verify it holds
# ══════════════════════════════════════════════════════════════════════════════
class TestHydration:
    def test_string_amount_ml_does_not_brick_day(self, app):
        c = _user(app)
        assert c.post("/api/hydration",
                      json={"amount_ml": "lots", "date_key": DAY}).status_code < 500
        r = c.get(f"/api/hydration/{DAY}")
        assert r.status_code == 200

    def test_infinity_amount_ml_does_not_brick_day(self, app):
        c = _user(app)
        body = json.dumps({"amount_ml": float("inf"), "date_key": DAY})
        assert c.post("/api/hydration", data=body,
                      content_type="application/json").status_code < 500
        assert c.get(f"/api/hydration/{DAY}").status_code == 200

    def test_negative_amount_clamped_non_negative(self, app):
        c = _user(app)
        c.post("/api/hydration", json={"amount_ml": -500, "date_key": DAY})
        total = c.get(f"/api/hydration/{DAY}").get_json()["total_ml"]
        assert total >= 0


# ══════════════════════════════════════════════════════════════════════════════
# BODY METRICS — the worst offender (KeyError + TypeError + poison)
# ══════════════════════════════════════════════════════════════════════════════
class TestBodyMetrics:
    def test_weighing_in_moves_the_numbers_derived_from_your_weight(self, app):
        """Logging your weight should change the things that depend on it.

        body_metrics fed the trend chart; user_profile.weight_kg fed the
        calorie target (calc_tdee) and the hydration goal (35ml/kg). Nothing
        connected them, so weighing in moved the chart and left every
        body-derived number sitting at whatever the profile last said — or at
        an assumed 70kg if it had never said anything.
        """
        import datetime as dt
        c = _user(app)
        c.post("/api/food/profile", json={"height_cm": 175, "age": 34,
                                          "gender": "male", "activity_level": "moderate",
                                          "goal": "maintain", "weight_kg": 70})
        today = dt.date.today().isoformat()
        before_cal = c.get("/api/food/profile").get_json()["targets"]["target_calories"]
        before_water = c.get(f"/api/hydration/{today}").get_json()["goal_ml"]

        r = c.post("/api/body-metrics", json={"weight_kg": 82, "date_key": today})
        assert r.status_code == 200

        after_cal = c.get("/api/food/profile").get_json()["targets"]["target_calories"]
        after_water = c.get(f"/api/hydration/{today}").get_json()["goal_ml"]
        assert after_cal > before_cal, "calorie target ignored the new weight"
        assert after_water > before_water, "hydration goal ignored the new weight"
        assert c.get("/api/food/profile").get_json()["profile"]["weight_kg"] == 82

    def test_bmi_uses_the_height_already_on_the_profile(self, app):
        """No logging path sends height_cm, so bmi was always NULL — a dead
        column the UI still reported ("BMI: —") after every weigh-in. We
        already know their height; use it."""
        import datetime as dt
        c = _user(app)
        c.post("/api/food/profile", json={"height_cm": 180, "weight_kg": 75,
                                          "age": 30, "gender": "female"})
        r = c.post("/api/body-metrics",
                   json={"weight_kg": 81, "date_key": dt.date.today().isoformat()})
        assert r.get_json()["metric"]["bmi"] == pytest.approx(25.0, abs=0.1)

    def test_backfilling_an_old_weight_does_not_rewrite_your_current_one(self, app):
        """Correcting last month's entry shouldn't tell the app what you weigh
        today — only today's entry is your current weight."""
        import datetime as dt
        c = _user(app)
        today = dt.date.today().isoformat()
        c.post("/api/food/profile", json={"height_cm": 175, "age": 34, "gender": "male"})
        c.post("/api/body-metrics", json={"weight_kg": 82, "date_key": today})
        c.post("/api/body-metrics", json={"weight_kg": 60, "date_key": "2026-06-01"})
        assert c.get("/api/food/profile").get_json()["profile"]["weight_kg"] == 82

    # BUG (HIGH) db/wellness.py:218 — data['date_key'] KeyError -> 500 when the
    # client omits the date. FIXED: default to today.
    def test_missing_date_key_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/body-metrics", json={"weight_kg": 70})
        assert r.status_code == 200

    # BUG (HIGH) db/wellness.py:215 — bmi = w/((h/100)**2) TypeErrors when
    # weight/height arrive as strings. FIXED: coerce numerics, NULL on garbage.
    def test_string_weight_height_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/body-metrics",
                   json={"date_key": DAY, "weight_kg": "heavy", "height_cm": "tall"})
        assert r.status_code == 200
        assert r.get_json()["metric"]["bmi"] is None

    def test_implausible_weight_is_rejected_not_quietly_clamped(self, app):
        """A typed -5 or 700 is a typo. This used to clamp to 0 / 1000 and
        store it — inventing a number the user never typed — which now matters
        more, because weighing in feeds the calorie target and hydration goal.
        Ask them to check instead. (A non-numeric value is different: that's
        "not provided", and stays lenient — see the string test above.)"""
        c = _user(app)
        for bad in (-5, 0, 700, 1500):
            r = c.post("/api/body-metrics", json={"date_key": DAY, "weight_kg": bad})
            assert r.status_code == 400, f"{bad}kg was accepted"
            assert "double-check" in r.get_json()["error"]
        # …and a real weight still logs fine.
        assert c.post("/api/body-metrics",
                      json={"date_key": DAY, "weight_kg": 72.5}).status_code == 200

    def test_valid_bmi_still_computes(self, app):
        c = _user(app)
        r = c.post("/api/body-metrics",
                   json={"date_key": DAY, "weight_kg": 70, "height_cm": 170})
        assert r.status_code == 200
        assert r.get_json()["metric"]["bmi"] == 24.2

    def test_garbage_date_key_defaulted(self, app):
        c = _user(app)
        r = c.post("/api/body-metrics",
                   json={"date_key": "not-a-date", "weight_kg": 68})
        assert r.status_code == 200
        datetime.date.fromisoformat(r.get_json()["metric"]["date_key"])

    # BUG (HIGH) routes/wellness.py:293 — /api/body-metrics/trend did
    # float(profile.get('weight_kg', 70)); a fresh user's profile row has
    # weight_kg=None (key present) -> float(None) -> 500 on an everyday view.
    # FIXED: to_num(profile.get('weight_kg'), 70).
    def test_trend_no_profile_weight_does_not_500(self, app):
        c = _user(app)
        assert c.get("/api/body-metrics/trend").status_code == 200
        c.post("/api/body-metrics",
               json={"date_key": DAY, "weight_kg": 70, "height_cm": 170})
        assert c.get("/api/body-metrics/trend").status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# HABITS — missing name -> 400, hostile target_days
# ══════════════════════════════════════════════════════════════════════════════
class TestHabits:
    # BUG (HIGH) db/health.py:25 — data['name'] KeyError -> 500 on a nameless
    # habit. FIXED: raise ValueError -> route maps to 400.
    def test_missing_name_is_client_error(self, app):
        c = _user(app)
        r = c.post("/api/habits", json={"emoji": "x"})
        assert 400 <= r.status_code < 500

    def test_blank_name_is_client_error(self, app):
        c = _user(app)
        r = c.post("/api/habits", json={"name": "   "})
        assert 400 <= r.status_code < 500

    # target_days as a string used to round-trip as a non-list; must not crash
    # create OR the habit-stats read.
    def test_string_target_days_does_not_break_stats(self, app):
        c = _user(app)
        r = c.post("/api/habits", json={"name": "Walk", "target_days": "monday"})
        assert r.status_code == 200
        assert r.get_json()["habit"]["target_days"] == []
        assert c.get("/api/habits").status_code == 200

    def test_valid_habit_round_trips(self, app):
        c = _user(app)
        r = c.post("/api/habits",
                   json={"name": "Meditate", "target_days": [0, 1, 2]})
        assert r.status_code == 200
        assert r.get_json()["habit"]["target_days"] == [0, 1, 2]

    def test_toggle_unknown_habit_is_noop(self, app):
        c = _user(app)
        r = c.post("/api/habits/no-such-id/toggle", json={"date_key": DAY})
        assert r.status_code == 200
        assert r.get_json().get("done") is False


# ══════════════════════════════════════════════════════════════════════════════
# THOUGHTS / JOURNAL — content required, no .strip() 500
# ══════════════════════════════════════════════════════════════════════════════
class TestThoughts:
    # BUG (HIGH) db/wellness.py:29 — content.strip() AttributeErrors on a
    # non-string content. FIXED: coerce to str; empty -> 400.
    def test_numeric_content_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/thoughts",
                   json={"content": 123, "mood": "happy", "date_key": DAY})
        assert r.status_code == 200

    def test_empty_content_is_client_error(self, app):
        c = _user(app)
        r = c.post("/api/thoughts",
                   json={"content": "   ", "mood": "neutral", "date_key": DAY})
        assert 400 <= r.status_code < 500

    def test_garbage_date_key_defaulted(self, app):
        c = _user(app)
        r = c.post("/api/thoughts",
                   json={"content": "hi", "date_key": "not-a-date"})
        assert r.status_code == 200
        datetime.date.fromisoformat(r.get_json()["thought"]["date_key"])

    def test_max_thoughts_per_day_enforced(self, app):
        c = _user(app)
        for i in range(10):
            assert c.post("/api/thoughts",
                          json={"content": f"t{i}", "date_key": DAY}).status_code == 200
        # 11th is rejected (ValueError -> 400)
        r = c.post("/api/thoughts", json={"content": "over", "date_key": DAY})
        assert 400 <= r.status_code < 500


# ══════════════════════════════════════════════════════════════════════════════
# TODOS — title required, hostile fields
# ══════════════════════════════════════════════════════════════════════════════
class TestTodos:
    # BUG (HIGH) db/wellness.py:75 — title.strip() AttributeErrors on a
    # non-string title. FIXED: coerce; empty -> 400.
    def test_numeric_title_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/todos", json={"title": 123})
        assert r.status_code == 200

    def test_missing_title_is_client_error(self, app):
        c = _user(app)
        r = c.post("/api/todos", json={"notes": "no title here"})
        assert 400 <= r.status_code < 500

    def test_string_tags_stored_as_list(self, app):
        c = _user(app)
        r = c.post("/api/todos", json={"title": "Task", "tags": "urgent"})
        assert r.status_code == 200
        assert r.get_json()["todo"]["tags"] == []
        # list read stays clean
        assert c.get("/api/todos").status_code == 200

    def test_update_missing_title_is_client_error(self, app):
        c = _user(app)
        tid = c.post("/api/todos", json={"title": "Orig"}).get_json()["todo"]["id"]
        r = c.put(f"/api/todos/{tid}", json={"title": ""})
        assert 400 <= r.status_code < 500

    def test_valid_todo_round_trips(self, app):
        c = _user(app)
        r = c.post("/api/todos", json={"title": "Buy milk", "priority": "high",
                                       "tags": ["shopping"]})
        assert r.status_code == 200
        d = r.get_json()["todo"]
        assert d["title"] == "Buy milk" and d["tags"] == ["shopping"]


# ══════════════════════════════════════════════════════════════════════════════
# Per-user isolation — MUST stay green
# ══════════════════════════════════════════════════════════════════════════════
class TestIsolation:
    def test_sleep_logs_private(self, app):
        alice = _user(app, "iso-sleep-a@medeasy.test")
        bob = _user(app, "iso-sleep-b@medeasy.test")
        # Use last night (relative to today), not a fixed date: /api/sleep
        # returns a rolling 14-day window, so a hardcoded date silently ages
        # out of it. Anchored to the wake date, which is what the API returns.
        today = datetime.date.today()
        bed = (today - datetime.timedelta(days=1)).isoformat()
        wake = today.isoformat()
        alice.post("/api/sleep", json={"bedtime": f"{bed}T23:00",
                                       "wake_time": f"{wake}T07:00",
                                       "quality": 4, "date_key": wake})
        assert len(alice.get("/api/sleep").get_json()) == 1
        assert len(bob.get("/api/sleep").get_json()) == 0

    def test_thoughts_private(self, app):
        alice = _user(app, "iso-th-a@medeasy.test")
        bob = _user(app, "iso-th-b@medeasy.test")
        alice.post("/api/thoughts", json={"content": "secret", "date_key": DAY})
        assert len(alice.get(f"/api/thoughts/{DAY}").get_json()["thoughts"]) == 1
        assert len(bob.get(f"/api/thoughts/{DAY}").get_json()["thoughts"]) == 0

    def test_todos_private(self, app):
        alice = _user(app, "iso-td-a@medeasy.test")
        bob = _user(app, "iso-td-b@medeasy.test")
        alice.post("/api/todos", json={"title": "Alice task"})
        assert len(alice.get("/api/todos").get_json()["todos"]) == 1
        assert len(bob.get("/api/todos").get_json()["todos"]) == 0

    def test_wellness_endpoints_require_auth(self, app):
        anon = app.test_client()
        for url in ["/api/sleep", "/api/sleep/trend", "/api/body-metrics",
                    "/api/body-metrics/trend", "/api/habits", "/api/todos",
                    f"/api/thoughts/{DAY}", f"/api/hydration/{DAY}"]:
            assert anon.get(url).status_code == 401, url
        for url in ["/api/sleep", "/api/body-metrics", "/api/habits",
                    "/api/todos", "/api/thoughts", "/api/hydration"]:
            assert anon.post(url, json={}).status_code == 401, url
