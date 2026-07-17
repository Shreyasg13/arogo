"""
tests/test_audit_fitness_insights.py — Product/QA audit of the
Fitness + Insights + Dashboard domain.

Written during a stress-test pass against an in-memory DB. Each test
documents a real defect (or asserts correct behaviour we want to keep).
Tests that currently FAIL mark live bugs; their docstring links to the
findings report. Where a test asserts the *buggy* behaviour so the suite
stays green as a regression guard, it says so explicitly and is marked
xfail for the "this is what it SHOULD be" expectation.

Run:  pytest tests/test_audit_fitness_insights.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
import auth as auth_module
from db.core import init_db
from app import create_app

TODAY = datetime.date.today().isoformat()
PW = "audit-pw-123456"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    # Let 500s surface as 500 (don't re-raise into the test) so we can assert on them
    application.config["PROPAGATE_EXCEPTIONS"] = False
    init_db()
    return application


@pytest.fixture(autouse=True)
def _no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    return c


@pytest.fixture(scope="module")
def fresh(app):
    """A brand-new user: profile row exists but weight/height/age/gender are NULL."""
    return _register(app, "fresh@audit.test")


@pytest.fixture(scope="module")
def profiled(app):
    """A user with a complete profile so calc_tdee() returns real numbers."""
    c = _register(app, "profiled@audit.test")
    r = c.post("/api/food/profile", json={
        "weight_kg": 70, "height_cm": 175, "age": 30, "gender": "male",
        "activity_level": "moderate", "goal": "maintain"})
    assert r.status_code == 200
    return c


def _complete_profile(c):
    c.post("/api/food/profile", json={
        "weight_kg": 70, "height_cm": 175, "age": 30, "gender": "male",
        "activity_level": "moderate", "goal": "maintain"})


# ══════════════════════════════════════════════════════════════════════════════
# BUGS
# ══════════════════════════════════════════════════════════════════════════════

class TestCalorieBalanceCrash:
    """
    BUG #1 (HIGH): GET /api/calorie-balance 500s for any user without a
    complete profile — i.e. essentially every brand-new user.

    routes/insights.py:37
        target = int(targets.get('target_calories', 2000))
    calc_tdee() returns {'target_calories': None} (the key EXISTS), so the
    default 2000 is never used and int(None) raises TypeError -> 500.

    Suggested fix:
        target = int(targets.get('target_calories') or 2000)
    """

    def test_calorie_balance_no_profile_reports_no_target(self, fresh):
        """Without weight/height/age/gender there IS no calorie target, and the
        endpoint must say so rather than invent one. `or 2000` used to fill the
        hole, and the dashboard printed the result as "2000 kcal remaining" —
        the most confident number on a new user's first screen, about a budget
        nobody had computed. Still must not 500 (int(None) once did)."""
        r = fresh.get("/api/calorie-balance")
        assert r.status_code == 200
        body = r.get_json()
        assert body["has_target"] is False
        assert body["today"]["target"] is None, "a target we can't compute must not be invented"
        assert body["today"]["budget"] is None, "no target means no budget…"
        assert body["today"]["net"] is None, "…and nothing 'remaining'"
        # Eaten is still true without a target, and still reported.
        assert body["today"]["eaten"] == 0

    def test_calorie_balance_ok_with_profile(self, profiled):
        r = profiled.get("/api/calorie-balance")
        assert r.status_code == 200
        assert r.get_json()["today"]["target"] > 0


class TestActivityValidation:
    """
    BUG #2 (HIGH): POST /api/fitness/activities does no validation.

    db/fitness.py:26-30 blindly int()/float()s the incoming fields.
      - non-numeric duration/calories/distance -> ValueError -> 500
      - negative values are stored verbatim and poison every downstream metric
      - absurd values (1e15) are stored verbatim
    routes/fitness.py:20-24 passes request.json straight through.

    Suggested fix: coerce defensively (try/except -> 0) and clamp negatives
    to 0 in insert_activity(), and 400 on non-numeric in the route.
    """

    def test_non_numeric_duration_should_not_500(self, profiled):
        r = profiled.post("/api/fitness/activities",
                          json={"type": "running", "duration": "abc"})
        assert r.status_code != 500, (
            "non-numeric duration raises ValueError inside int() -> 500. "
            "Coerce/validate before insert.")

    def test_negative_values_should_be_rejected_or_clamped(self, app):
        c = _register(app, "neg@audit.test")
        r = c.post("/api/fitness/activities",
                   json={"type": "running", "duration": -50,
                         "calories": -999, "distance": -3})
        assert r.status_code in (200, 201)
        act = r.get_json()["activity"]
        assert act["duration"] >= 0, "negative duration was stored verbatim"
        assert act["calories"] >= 0, "negative calories were stored verbatim"
        assert act["distance"] >= 0, "negative distance was stored verbatim"

    def test_missing_type_defaults_but_succeeds(self, profiled):
        # Missing type is tolerated (defaults to 'running') — documents behaviour.
        r = profiled.post("/api/fitness/activities", json={})
        assert r.status_code in (200, 201)


# The dashboard health-score ring and /api/health-score are gone (see the
# commit removing them): a user with perfect medication adherence scored
# 0/100 grade "E", because adherence was not one of its five components and
# every untracked component counted as a zero. The negative-total guard that
# used to live here went with the endpoint. The real numbers it sat on top of
# — next action, meds taken today — are covered in test_stress_medical.py.



class TestCalorieBalanceNegativeBurn:
    """
    BUG #4 (MEDIUM): a negative-calorie activity REDUCES the daily calorie
    budget instead of being ignored.

    routes/insights.py:51  budget = target + burned_today
    With burned_today = -999 the budget drops below target, so the user is
    told they have *less* room to eat because of "exercise". `burned` should
    be floored at 0 (again downstream of BUG #2).
    """

    def test_negative_burn_does_not_shrink_budget(self, app):
        c = _register(app, "cbneg@audit.test")
        _complete_profile(c)
        base = c.get("/api/calorie-balance").get_json()["today"]
        c.post("/api/fitness/activities",
               json={"type": "running", "duration": 30, "calories": -999})
        after = c.get("/api/calorie-balance").get_json()["today"]
        assert after["burned"] >= 0, f"burned is negative: {after['burned']}"
        assert after["budget"] >= base["target"], (
            "a 'workout' lowered the calorie budget below target")


class TestFitnessStatsNegativeText:
    """
    BUG #5 (LOW / UX): fitness suggestions surface raw negative numbers to
    the user, e.g. "You've done -50 of the recommended 150 min/week."
    db/fitness.py:83. Downstream of BUG #2; clamp week_dur for display.
    """

    def test_suggestion_text_has_no_negative_minutes(self, app):
        import re
        c = _register(app, "fsneg@audit.test")
        c.post("/api/fitness/activities",
               json={"type": "running", "duration": -50})
        fs = c.get("/api/fitness/stats").get_json()
        joined = " ".join(s["text"] for s in fs["suggestions"])
        # A negative number is a minus sign glued to a digit ("-50"). Plain
        # hyphens in copy ("30-min jog") are fine.
        assert not re.search(r"-\d", joined), (
            f"negative number leaked into suggestion copy: {joined}")


# ══════════════════════════════════════════════════════════════════════════════
# EMPTY / PARTIAL DATA — endpoints must not 500 (regression guards)
# ══════════════════════════════════════════════════════════════════════════════

class TestEmptyDataEndpoints:
    """Every insights/dashboard endpoint must return 200 with sane zeros for a
    brand-new user. calorie-balance is the known offender (see BUG #1)."""

    @pytest.mark.parametrize("path", [
        "/api/weekly-digest",
        "/api/report/weekly",
        "/api/progress",
        "/api/insights/cards",
        "/api/fitness/stats",
        "/api/fitness/prs",
        "/api/fitness/consistency",
        "/api/fitness/calendar",
    ])
    def test_empty_user_no_500(self, fresh, path):
        r = fresh.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code} on empty data"

    def test_calorie_balance_listed_separately(self, fresh):
        # Kept out of the parametrize above so its failure is unambiguous.
        assert fresh.get("/api/calorie-balance").status_code == 200

    def test_empty_insight_cards_is_empty_list(self, fresh):
        assert fresh.get("/api/insights/cards").get_json()["cards"] == []

    def test_empty_prs_flagged_has_data_false(self, fresh):
        body = fresh.get("/api/fitness/prs").get_json()
        assert body["has_data"] is False and body["prs"] == []

    def test_weekly_digest_scores_are_absent_or_bounded(self, fresh):
        """A score is either a real 0-100 or None — never a 0 standing in for
        "not tracked". This account tracks nothing, so every score is None:
        scoring absences as zeros is what emailed people "Tough week" for not
        using features they'd never opened."""
        d = fresh.get("/api/weekly-digest").get_json()
        assert d["overall_score"] is None
        for k in ["sleep", "workouts", "habits", "hydration", "nutrition"]:
            assert k in d["scores"], f"{k} missing from scores"
            assert d["scores"][k] is None, f"{k} isn't tracked — must be None, not 0"

    def test_progress_math_no_nan_or_infinity(self, fresh):
        """No NaN/Infinity/None where the frontend does bare ${...} math."""
        p = fresh.get("/api/progress").get_json()
        assert p["workouts"]["frequency_pct"] >= 0
        assert p["habits"]["completion_pct"] == 0        # not None
        assert p["nutrition"]["adherence_pct"] == 0      # not None


class TestPartialData:
    """Partial data (profile but no logs, or logs but no profile) is where
    divide-by-zero and null math typically hide."""

    def test_calorie_balance_food_but_no_profile(self, app):
        """Logs exist but calc_tdee still returns None target — BUG #1 path."""
        c = _register(app, "partial2@audit.test")
        # Log a workout (doesn't require a profile)
        c.post("/api/fitness/activities",
               json={"type": "running", "duration": 30, "calories": 300})
        r = c.get("/api/calorie-balance")
        assert r.status_code == 200, "calorie-balance 500s when profile incomplete"


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL SEARCH — robustness (these all PASS today; guards against regressions)
# ══════════════════════════════════════════════════════════════════════════════

class TestGlobalSearch:
    def test_single_char_returns_empty(self, profiled):
        r = profiled.get("/api/search?q=a")
        assert r.status_code == 200
        assert r.get_json()["total"] == 0

    def test_empty_query(self, profiled):
        r = profiled.get("/api/search?q=")
        assert r.status_code == 200
        assert r.get_json()["total"] == 0

    def test_sql_metacharacters_are_safe(self, profiled):
        for q in ["%", "%'\"_", "'; DROP TABLE food_logs;--", "100%%", "a_b%c"]:
            r = profiled.get("/api/search", query_string={"q": q})
            assert r.status_code == 200, f"metachar query 500'd: {q!r}"

    def test_huge_query_no_500(self, profiled):
        r = profiled.get("/api/search", query_string={"q": "x" * 5000})
        assert r.status_code == 200

    def test_date_phrase_only_query(self, profiled):
        # "last week" with no text term must not blow up
        r = profiled.get("/api/search", query_string={"q": "last week"})
        assert r.status_code == 200

    def test_wildcard_only_does_not_leak_other_users(self, app):
        """A search whose clean term collapses to '%' must still be user-scoped."""
        a = _register(app, "searchA@audit.test")
        b = _register(app, "searchB@audit.test")
        a.post("/api/fitness/activities",
               json={"type": "running", "name": "Alice secret run",
                     "duration": 30, "calories": 300})
        # b searches 'today' (date-only) — clean term is None -> LIKE '%'
        res = b.get("/api/search", query_string={"q": "today"}).get_json()
        blob = str(res)
        assert "Alice secret run" not in blob, "search leaked another user's activity"


# ══════════════════════════════════════════════════════════════════════════════
# PER-USER ISOLATION (fitness / insights domain)
# ══════════════════════════════════════════════════════════════════════════════

class TestIsolation:
    def test_activities_not_shared(self, app):
        a = _register(app, "isoA@audit.test")
        b = _register(app, "isoB@audit.test")
        a.post("/api/fitness/activities",
               json={"type": "cycling", "name": "A-ride", "duration": 40, "calories": 400})
        b_acts = b.get("/api/fitness/activities").get_json()
        assert all(x["name"] != "A-ride" for x in b_acts)

    def test_b_cannot_delete_a_activity(self, app):
        a = _register(app, "isoDelA@audit.test")
        b = _register(app, "isoDelB@audit.test")
        aid = a.post("/api/fitness/activities",
                     json={"type": "running", "duration": 20, "calories": 100}
                     ).get_json()["activity"]["id"]
        b.delete(f"/api/fitness/activities/{aid}")
        # A's activity must still exist
        still = a.get("/api/fitness/activities").get_json()
        assert any(x["id"] == aid for x in still), "user B deleted user A's activity"

    def test_stats_isolated(self, app):
        a = _register(app, "isoStatA@audit.test")
        b = _register(app, "isoStatB@audit.test")
        a.post("/api/fitness/activities",
               json={"type": "running", "duration": 60, "calories": 500})
        assert b.get("/api/fitness/stats").get_json()["total"] == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
