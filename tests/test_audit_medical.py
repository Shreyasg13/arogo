"""
tests/test_audit_medical.py — Medical-domain audit suite (Medicines + Medical).

Product/QA stress-test of the Medicines and Medical (reports, symptoms,
vitals, emergency) surfaces. Each test documents a real defect found while
hammering the API against an in-memory SQLite instance.

Tests whose NAME starts with `test_bug_` assert the CURRENT (buggy) behaviour
so the suite is green today; each carries a comment describing the correct
behaviour and the fix. Flip the assertion once the underlying code is fixed.
Tests named `test_ok_` / `test_guard_` assert behaviour that is already correct
and guards against regressions.

Run:  pytest tests/test_audit_medical.py -v
"""
import io
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import datetime
import pytest

import auth as auth_module
from db.core import init_db, execute
from app import create_app

TODAY = datetime.date.today().isoformat()
PW = "audit-pw-123456"


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def _no_rate_limit():
    # Registering several clients per test trips the auth rate limiter otherwise.
    try:
        auth_module.reset_rate_limiter()
    except Exception:
        pass
    yield
    try:
        auth_module.reset_rate_limiter()
    except Exception:
        pass


def _client(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), (r.status_code, r.get_json())
    return c


_counter = {"n": 0}


@pytest.fixture
def client(app):
    """A fresh, unique authenticated user per test (isolation-safe)."""
    _counter["n"] += 1
    return _client(app, f"audit{_counter['n']}@medeasy.test")


@pytest.fixture(autouse=True)
def _clean():
    yield
    for t in ["medicines", "dose_logs", "symptoms", "vitals",
              "emergency_info", "reports"]:
        try:
            execute(f"DELETE FROM {t}", commit=True)
        except Exception:
            pass


def jpost(c, url, body=None):
    r = c.post(url, json=body if body is not None else {})
    return r.status_code, r.get_json()


def crashes(c, url, body):
    """True if the endpoint raises an unhandled exception (i.e. would be a
    500 in production). With app.config['TESTING']=True Flask re-raises the
    original exception into the test client instead of returning 500, so an
    unhandled crash surfaces here as a Python exception."""
    try:
        c.post(url, json=body)
        return False
    except Exception:
        return True


def jget(c, url):
    r = c.get(url)
    return r.status_code, r.get_json()


VALID_MED = {"name": "Metformin", "dosage": "500", "unit": "mg",
             "frequency": "twice_daily", "times": ["08:00", "20:00"]}


def _make_med(client, **over):
    body = {**VALID_MED, **over}
    _, d = jpost(client, "/api/medicines", body)
    return d["medicine"]["id"]


# ══════════════════════════════════════════════════════════════════════════════
# BUGS — 500 crashes on missing / bad input (no validation before DB insert)
# ══════════════════════════════════════════════════════════════════════════════

class TestMedicineValidation:
    """POST /api/medicines now validates input: a missing name returns a clean
    400; a missing dosage falls back to the schema default (''). No 500s."""

    def test_ok_missing_name_400(self, client):
        # FIXED: db/medicines.py insert_medicine rejects a blank name; the route
        # maps ValueError -> 400 instead of crashing on KeyError.
        code, d = jpost(client, "/api/medicines", {"dosage": "5"})
        assert code == 400
        assert "error" in d

    def test_ok_missing_dosage_defaulted(self, client):
        # FIXED: dosage defaults to '' (schema allows it) instead of KeyError.
        code, d = jpost(client, "/api/medicines", {"name": "X"})
        assert code == 200
        assert d["medicine"]["name"] == "X"

    def test_ok_empty_body_400(self, client):
        code, d = jpost(client, "/api/medicines", {})
        assert code == 400
        assert "error" in d


class TestMedicineTimesCorruption:
    """`times` is trusted to be a list. A string slips straight into jdump()
    and later `for t in times` iterates CHARACTERS -> phantom doses."""

    def test_ok_times_string_coerced_to_single_dose(self, client):
        # FIXED: a scalar time string is wrapped into a single-element list by
        # _clean_times, so it yields exactly one real dose (08:00) — not five
        # phantom doses from iterating the string character-by-character.
        _make_med(client, times="08:00")
        code, doses = jget(client, "/api/medicines/today")
        assert code == 200
        assert len(doses) == 1
        assert doses[0]["time"] == "08:00"

    def test_ok_empty_times_defaults_to_trackable_dose(self, client):
        # FIXED: an empty times list would create an untrackable ghost medicine.
        # _clean_times now falls back to a single 08:00 dose so the medicine is
        # visible on the timeline and counts toward adherence.
        _make_med(client, times=[])
        code, doses = jget(client, "/api/medicines/today")
        assert code == 200
        assert len(doses) == 1
        assert doses[0]["time"] == "08:00"

    def test_ok_huge_times_array_capped(self, client):
        # FIXED: _clean_times de-dupes and caps the schedule at 24 slots, so a
        # 5000-entry payload can't bloat the timeline / adherence grid.
        mid = _make_med(client, times=["08:00", "09:00"] * 5000)
        assert mid
        code, doses = jget(client, "/api/medicines/today")
        assert code == 200
        assert len(doses) == 2   # de-duped to the two distinct times


# ══════════════════════════════════════════════════════════════════════════════
# BUGS — Stock / refill: no validation, silent nonsense values
# ══════════════════════════════════════════════════════════════════════════════

class TestStock:
    def test_ok_non_int_pill_count_coerced(self, client):
        # FIXED: to_int() coerces a non-numeric pill_count to the default (0)
        # instead of raising ValueError -> 500.
        mid = _make_med(client)
        code, d = jpost(client, f"/api/medicines/{mid}/stock",
                        {"pill_count": "abc"})
        assert code == 200
        assert d["medicine"]["pill_count"] == 0

    def test_ok_negative_pill_count_clamped(self, client):
        # FIXED: pill_count is clamped to >= 0, so the med card can never render
        # "-5 pills · -5d left" or a negative-width bar.
        mid = _make_med(client)
        code, d = jpost(client, f"/api/medicines/{mid}/stock",
                        {"pill_count": -5, "pills_per_dose": 1})
        assert code == 200
        assert d["medicine"]["pill_count"] == 0   # clamped, not persisted as -5

    def test_bug_zero_pills_per_dose_silently_ignored(self, client):
        # A user who enters pills_per_dose = 0 gets NO error, and the days-left
        # math silently treats 0 as 1 (both `pills_per_dose or 1` in the backend
        # and `m.pills_per_dose||1` in app.js:1825). So "0 pills per dose" is
        # accepted and produces a misleading days-left figure instead of being
        # rejected. Not a 500 (the 0.01 floor prevents ZeroDivisionError), but a
        # data-integrity / UX defect.
        # file: db/medicines.py:135 & 149; static/js/app.js:1825.
        # CORRECT: reject pills_per_dose < 1 (400) at the route.
        mid = _make_med(client, frequency="once_daily", times=["08:00"])
        jpost(client, f"/api/medicines/{mid}/stock",
              {"pill_count": 10, "pills_per_dose": 0, "refill_threshold": 7})
        code, low = jget(client, "/api/medicines/low-stock")
        assert code == 200
        # 10 pills, "0" per dose -> treated as 1/day -> 10 days left, which is
        # ABOVE the 7-day threshold, so it is (mis)reported as NOT low.
        assert low == []

    def test_ok_no_zero_division_on_low_stock(self, client):
        # Guard test: even with pills_per_dose=0 the endpoint must not 500.
        mid = _make_med(client, times=["08:00"])
        jpost(client, f"/api/medicines/{mid}/stock",
              {"pill_count": 3, "pills_per_dose": 0, "refill_threshold": 7})
        code, _ = jget(client, "/api/medicines/low-stock")
        assert code == 200


# ══════════════════════════════════════════════════════════════════════════════
# BUGS — Symptoms / Vitals: active wellness routes lack validation
#         (insights.py HAS guards but is DEAD CODE — wellness registers first)
# ══════════════════════════════════════════════════════════════════════════════

class TestSymptomsVitalsValidation:
    """routes/wellness.py registers before routes/insights.py, so the
    UNGUARDED wellness handlers win. The nicely-validated duplicates in
    insights.py (which DO return 400) never run."""

    def test_ok_symptom_missing_name_400(self, client):
        # FIXED: log_symptom rejects a blank name; wellness.api_log_symptom maps
        # ValueError -> 400 instead of a KeyError 500.
        code, d = jpost(client, "/api/symptoms", {"severity": 5})
        assert code == 400
        assert "error" in d

    def test_ok_symptom_non_numeric_severity_coerced(self, client):
        # FIXED: to_int() coerces a non-numeric severity to the default (5) and
        # clamps to 1..10 instead of raising ValueError -> 500.
        code, d = jpost(client, "/api/symptoms",
                        {"name": "ache", "severity": "bad"})
        assert code == 200
        assert d["symptom"]["severity"] == 5

    def test_ok_vital_missing_type_400(self, client):
        # FIXED: log_vital rejects a missing type -> 400, no KeyError.
        code, d = jpost(client, "/api/vitals", {"value1": 5})
        assert code == 400
        assert "error" in d

    def test_ok_vital_missing_value1_400(self, client):
        # FIXED: log_vital rejects a missing reading -> 400, no KeyError.
        code, d = jpost(client, "/api/vitals", {"type": "blood_pressure"})
        assert code == 400
        assert "error" in d

    def test_ok_vital_non_numeric_value1_400(self, client):
        # FIXED: a non-numeric reading is rejected with a clean 400.
        code, d = jpost(client, "/api/vitals",
                        {"type": "blood_pressure", "value1": "high"})
        assert code == 400
        assert "error" in d

    def test_ok_valid_symptom_and_vital(self, client):
        c1, _ = jpost(client, "/api/symptoms",
                      {"name": "headache", "severity": 6})
        assert c1 == 200
        c2, _ = jpost(client, "/api/vitals",
                      {"type": "heart_rate", "value1": 72})
        assert c2 == 200


# ══════════════════════════════════════════════════════════════════════════════
# Reports upload — extension / file / traversal handling
# ══════════════════════════════════════════════════════════════════════════════

class TestUpload:
    def test_ok_missing_file_400(self, client):
        code, d = jpost(client, "/api/upload", {})  # json, no multipart file
        assert code == 400
        assert "error" in d

    def test_ok_disallowed_extension_400(self, client):
        r = client.post("/api/upload",
                        data={"file": (io.BytesIO(b"x"), "evil.exe")},
                        content_type="multipart/form-data")
        assert r.status_code == 400

    def test_ok_no_extension_400(self, client):
        r = client.post("/api/upload",
                        data={"file": (io.BytesIO(b"x"), "noext")},
                        content_type="multipart/form-data")
        assert r.status_code == 400

    def test_guard_path_traversal_filename_neutralised(self, client):
        # secure_filename() strips the traversal; the stored name must not
        # contain path separators or '..'.
        r = client.post("/api/upload",
                        data={"file": (io.BytesIO(b"PDF"),
                                       "../../etc/passwd.pdf")},
                        content_type="multipart/form-data")
        assert r.status_code == 200
        stored = r.get_json()["report"]["filename"]
        assert ".." not in stored
        assert "/" not in stored and "\\" not in stored
        assert stored.endswith("passwd.pdf")


# ══════════════════════════════════════════════════════════════════════════════
# Per-user isolation + medical-file ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestIsolation:
    def test_medicine_isolation(self, app):
        alice = _client(app, "iso_alice_med@medeasy.test")
        bob = _client(app, "iso_bob_med@medeasy.test")
        _make_med(alice, name="AlicePill")
        _, bob_meds = jget(bob, "/api/medicines")
        assert all(m["name"] != "AlicePill" for m in bob_meds)

    def test_symptom_vital_emergency_isolation(self, app):
        alice = _client(app, "iso_alice_h@medeasy.test")
        bob = _client(app, "iso_bob_h@medeasy.test")
        jpost(alice, "/api/symptoms", {"name": "alice-only", "severity": 4})
        jpost(alice, "/api/vitals", {"type": "heart_rate", "value1": 61})
        jpost(alice, "/api/emergency", {"blood_type": "AB-",
                                        "allergies": "alice-secret"})
        _, bob_syms = jget(bob, "/api/symptoms")
        _, bob_vitals = jget(bob, "/api/vitals")
        _, bob_emerg = jget(bob, "/api/emergency")
        assert all(s["name"] != "alice-only" for s in bob_syms)
        assert all(v["value1"] != 61 for v in bob_vitals)
        assert bob_emerg.get("allergies", "") != "alice-secret"

    def test_uploaded_file_ownership_enforced(self, app):
        alice = _client(app, "own_alice@medeasy.test")
        bob = _client(app, "own_bob@medeasy.test")
        r = alice.post("/api/upload",
                       data={"file": (io.BytesIO(b"SECRET LAB"),
                                      "labresult.pdf")},
                       content_type="multipart/form-data")
        fn = r.get_json()["report"]["filename"]
        # Owner can fetch.
        assert alice.get("/uploads/" + fn).status_code == 200
        # Non-owner is denied (must be 404, not the file bytes).
        rb = bob.get("/uploads/" + fn)
        assert rb.status_code == 404
        assert b"SECRET LAB" not in rb.get_data()

    def test_delete_report_scoped(self, app):
        alice = _client(app, "del_alice@medeasy.test")
        bob = _client(app, "del_bob@medeasy.test")
        r = alice.post("/api/upload",
                       data={"file": (io.BytesIO(b"x"), "a.pdf")},
                       content_type="multipart/form-data")
        rid = r.get_json()["report"]["id"]
        # Bob cannot delete Alice's report.
        assert bob.delete(f"/api/reports/{rid}").status_code == 404
        # Alice still can.
        assert alice.delete(f"/api/reports/{rid}").status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Adherence / streak math edge cases (no NaN / Infinity / crash)
# ══════════════════════════════════════════════════════════════════════════════

class TestAdherenceMath:
    def test_ok_adherence_zero_doses_is_zero_not_nan(self, client):
        # /api/medicines/adherence with no doses -> pct 0 (guarded), not NaN.
        code, d = jget(client, "/api/medicines/adherence")
        assert code == 200

    def test_ok_streaks_empty_and_no_division(self, client):
        # streaks endpoint with a med that has empty times must not crash.
        _make_med(client, times=[])
        code, d = jget(client, "/api/medicines/streaks")
        assert code == 200
        assert d["overall_pct"] == 0   # 0/0 guarded to 0, not NaN

    def test_ok_adherence_days_zero(self, client):
        # get_adherence_stats(days=0): total stays 0 -> pct 0, no ZeroDivision.
        code, d = jget(client, "/api/medicines/adherence?days=0")
        # medicines.py adherence route returns get_adherence_stats(0)
        assert code == 200

    def test_log_dose_bad_medicine_id_noop(self, client):
        # Logging against a non-existent / other-user's medicine is a silent
        # no-op (owner check) and returns success — arguably should 404, but at
        # least it does not corrupt data or crash.
        code, d = jpost(client, "/api/medicines/does-not-exist/log",
                        {"time": "08:00", "taken": True})
        assert code == 200
        assert d["success"] is True
