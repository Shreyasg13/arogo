"""
tests/test_audit_food.py — Security/robustness audit of the Food & Water +
Barcode domain (routes/food.py, db/food.py, food_barcode.py, db/wellness.py
hydration, static/js/app.js food UI).

Modeled on tests/test_barcode.py. Open Food Facts is never hit for real.

Run:  pytest tests/test_audit_food.py -v

IMPORTANT — several tests below assert the *buggy* current behavior and are
marked `xfail(strict=False)` with a comment describing the bug and the fix.
When a bug is fixed, its xfail test will XPASS, flagging that the audit note
can be closed. Tests NOT marked xfail assert correct behavior that already
holds today (isolation, validation that does work) — those must stay green.
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import json
import pytest

import auth as auth_module
import food_barcode
from db.core import init_db
from app import create_app

PW = "audit-pw-123456789"
DAY = "2026-07-12"


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


@pytest.fixture(autouse=True)
def stub_off(monkeypatch):
    """No real network for barcode lookups."""
    monkeypatch.setattr(food_barcode, "lookup_barcode", lambda code: None)


_counter = {"n": 0}


def _user(app, email=None):
    """Fresh registered+session'd client. Unique email each call unless given."""
    if email is None:
        _counter["n"] += 1
        email = f"audit-{_counter['n']}@medeasy.test"
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), (r.status_code, r.data[:120])
    return c


# ══════════════════════════════════════════════════════════════════════════════
# BUGS — non-numeric input causes uncaught 500s (float()/int() with no guard)
# ══════════════════════════════════════════════════════════════════════════════
class TestNonNumericCrashes:
    # BUG #1 (HIGH) routes/food.py:65 — quantity_g coerced with bare float().
    # Non-numeric 'quantity_g' raises ValueError → HTTP 500.
    # FIX: wrap in a safe-float helper defaulting to 100 (or 400 on bad input).
    def test_log_nonnumeric_quantity_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/food/log", json={
            "food_id": "banana", "food_name": "B",
            "quantity_g": "lots", "calories": 10})
        assert r.status_code != 500

    # BUG #2 (HIGH) routes/food.py:88-94 — calories/protein/... coerced with
    # bare float(). Non-numeric 'calories' raises ValueError → HTTP 500.
    def test_log_nonnumeric_calories_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/food/log", json={
            "food_id": "banana", "food_name": "B",
            "quantity_g": 100, "calories": "abc"})
        assert r.status_code != 500

    # BUG #3 (HIGH) routes/food.py:155 — PATCH new_qty = float(...) unguarded.
    # A non-numeric quantity_g on the edit endpoint raises ValueError → 500
    # (should be the existing 400 "Invalid quantity").
    def test_patch_nonnumeric_quantity_does_not_500(self, app):
        c = _user(app)
        r = c.patch("/api/food/log/whatever", json={"quantity_g": "x"})
        assert r.status_code in (400, 404)

    # BUG #4 (HIGH) db/food.py:181-184 — save_custom_food float()s calories,
    # serving_g etc. with no guard. Non-numeric → ValueError → 500.
    def test_custom_nonnumeric_calories_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/food/custom", json={"name": "X", "calories": "abc"})
        assert r.status_code != 500

    def test_custom_nonnumeric_serving_does_not_500(self, app):
        c = _user(app)
        r = c.post("/api/food/custom", json={"name": "X", "serving_g": "big"})
        assert r.status_code != 500

    # BUG #5 (MEDIUM) routes/food.py:39 — limit = int(request.args.get('limit')).
    # A non-numeric ?limit= raises ValueError → 500 on the food database browse.
    def test_food_db_bad_limit_does_not_500(self, app):
        c = _user(app)
        r = c.get("/api/food/db?limit=abc")
        assert r.status_code != 500


# ══════════════════════════════════════════════════════════════════════════════
# BUGS — bad values are PERSISTED and then permanently brick a day's view
# ══════════════════════════════════════════════════════════════════════════════
class TestPoisonedRows:
    # BUG #6 (CRITICAL) routes/wellness.py:157-160 + db/wellness.py:169 —
    # POST /api/hydration passes amount_ml straight through with no coercion.
    # A string amount_ml is stored verbatim; get_hydration_day then does
    # sum(r['amount_ml']) → TypeError (int + str) → EVERY subsequent load of
    # that day 500s permanently. The user cannot see or fix their own data.
    # FIX: coerce amount_ml to a positive number at the route (reject/clamp).
    def test_string_amount_ml_does_not_brick_day(self, app):
        c = _user(app)
        assert c.post("/api/hydration",
                      json={"amount_ml": "lots", "date_key": DAY}).status_code < 500
        # The poison shows up here — this GET 500s today:
        r = c.get(f"/api/hydration/{DAY}")
        assert r.status_code == 200

    # BUG #7 (CRITICAL) routes/food.py:88 + food serialization —
    # calories = float(Infinity) is accepted and stored. Loading that day
    # (/api/food/log/<date>) then 500s (OverflowError converting inf to int
    # while building the nutrition summary / JSON). Day view is bricked.
    # FIX: reject non-finite numbers (math.isfinite) before logging.
    def test_infinity_calories_does_not_brick_day(self, app):
        c = _user(app)
        body = json.dumps({"food_id": "x", "food_name": "X",
                           "calories": float("inf"), "quantity_g": 100,
                           "date_key": DAY})
        r = c.post("/api/food/log", data=body, content_type="application/json")
        assert r.status_code < 500
        # This read now 500s:
        assert c.get(f"/api/food/log/{DAY}").status_code == 200

    # BUG #8 (HIGH) routes/food.py:65 + db/food.py — negative quantity is
    # accepted and produces negative calories/macros/nutrients that flow into
    # the day totals (a "meal" that subtracts calories). No validation.
    # FIX: reject quantity_g <= 0 (the PATCH endpoint already does this).
    def test_negative_quantity_rejected(self, app):
        c = _user(app)
        r = c.post("/api/food/log", json={
            "food_id": "banana", "food_name": "B", "calories": 100,
            "quantity_g": -500, "protein": 1, "carbs": 1, "fat": 1,
            "date_key": DAY})
        # Ideally rejected; today it succeeds and stores negatives.
        assert r.status_code >= 400 or r.get_json().get("log", {}).get("quantity_g", 0) >= 0


# ══════════════════════════════════════════════════════════════════════════════
# BUGS — dates are never validated
# ══════════════════════════════════════════════════════════════════════════════
class TestDateValidation:
    # BUG #9 (LOW/MEDIUM) routes/food.py:86 — date_key is stored verbatim.
    # Garbage ("not-a-date") or far-future ("2099-01-01") dates are accepted,
    # so logs can be orphaned on non-navigable days.
    # FIX: validate date_key is a real ISO date and (optionally) not future.
    def test_garbage_date_key_rejected(self, app):
        c = _user(app)
        r = c.post("/api/food/log", json={
            "food_id": "x", "food_name": "X", "calories": 10,
            "quantity_g": 100, "date_key": "not-a-date"})
        assert r.status_code >= 400


# ══════════════════════════════════════════════════════════════════════════════
# Things that already work — these MUST stay green (regression guards)
# ══════════════════════════════════════════════════════════════════════════════
class TestCorrectBehaviorHolds:
    def test_custom_food_requires_name(self, app):
        c = _user(app)
        r = c.post("/api/food/custom", json={"calories": 10})
        assert r.status_code == 400

    def test_missing_food_and_calories_is_404_not_500(self, app):
        c = _user(app)
        r = c.post("/api/food/log", json={"food_name": "X"})
        assert r.status_code == 404

    def test_empty_body_log_is_404_not_500(self, app):
        c = _user(app)
        assert c.post("/api/food/log", json={}).status_code == 404

    def test_patch_unknown_id_404(self, app):
        c = _user(app)
        assert c.patch("/api/food/log/nope",
                       json={"quantity_g": 50}).status_code == 404

    def test_barcode_shape_validation(self, app):
        c = _user(app)
        assert c.get("/api/food/barcode/123").status_code == 400
        assert c.get("/api/food/barcode/abcd1234").status_code == 400

    def test_partial_profile_returns_null_targets_not_crash(self, app):
        """calc_tdee must return None targets (not 500) when profile is
        incomplete — the JS formats None as '—'."""
        c = _user(app)
        c.post("/api/food/profile", json={"weight_kg": 70})  # only weight
        t = c.get("/api/food/profile").get_json()["targets"]
        assert t["target_calories"] is None and t["bmr"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Per-user isolation (this domain) — MUST stay green
# ══════════════════════════════════════════════════════════════════════════════
class TestIsolation:
    def test_food_logs_are_private(self, app):
        alice = _user(app, "iso-food-a@medeasy.test")
        bob = _user(app, "iso-food-b@medeasy.test")
        alice.post("/api/food/log", json={
            "food_id": "banana", "food_name": "AliceBanana", "calories": 100,
            "quantity_g": 100, "protein": 1, "carbs": 1, "fat": 1,
            "date_key": DAY})
        assert alice.get(f"/api/food/log/{DAY}").get_json()["summary"]["log_count"] == 1
        assert bob.get(f"/api/food/log/{DAY}").get_json()["summary"]["log_count"] == 0

    def test_bob_cannot_edit_alice_log(self, app):
        alice = _user(app, "iso-edit-a@medeasy.test")
        bob = _user(app, "iso-edit-b@medeasy.test")
        alice.post("/api/food/log", json={
            "food_id": "banana", "food_name": "AliceBanana", "calories": 100,
            "quantity_g": 100, "date_key": DAY})
        lid = (alice.get(f"/api/food/log/{DAY}").get_json()
               ["summary"]["by_meal"]["lunch"]["items"][0]["id"])
        # PATCH by the wrong user must not touch the row.
        assert bob.patch(f"/api/food/log/{lid}",
                         json={"quantity_g": 50}).status_code == 404
        # DELETE is user-scoped in SQL so Alice's data survives...
        bob.delete(f"/api/food/log/{lid}")
        assert alice.get(f"/api/food/log/{DAY}").get_json()["summary"]["log_count"] == 1

    # FIXED: DELETE /api/food/log/<id> now returns an honest 404 when nothing
    # matched (missing / another user's), instead of a misleading success:true.
    def test_delete_foreign_log_should_signal_not_found(self, app):
        alice = _user(app, "iso-del-a@medeasy.test")
        bob = _user(app, "iso-del-b@medeasy.test")
        alice.post("/api/food/log", json={
            "food_id": "banana", "food_name": "A", "calories": 100,
            "quantity_g": 100, "date_key": DAY})
        lid = (alice.get(f"/api/food/log/{DAY}").get_json()
               ["summary"]["by_meal"]["lunch"]["items"][0]["id"])
        assert bob.delete(f"/api/food/log/{lid}").status_code == 404

    def test_hydration_requires_auth(self, app):
        assert app.test_client().post("/api/hydration",
                                      json={"amount_ml": 250}).status_code == 401
