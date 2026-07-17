"""
tests/test_stress_food.py — Food & Water domain stress tests.

Locks in the *correct* current behaviour of the food / hydration APIs
under hostile or sloppy input: proper rejections (400/404), idempotent
deletes, unicode round-trips, and safe handling of oversized input.

Known genuine bugs (500s on quantity_g='abc', NaN/Infinity PATCH
poisoning, /api/calorie-balance with an empty profile, hydration
amount_ml type poisoning, negative quantities silently accepted) are
deliberately NOT tested here — they are documented in the audit report
and should get regression tests alongside their fixes.

Run:  pytest tests/test_stress_food.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import datetime
import json
import pytest
import auth as auth_module
from db.core import init_db, execute
from app import create_app

PW = "stress-pw-12345"
TODAY = datetime.date.today().isoformat()


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


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": "stress-food@medeasy.test",
                                       "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": "stress-food@medeasy.test",
                                        "password": PW})
    assert r.status_code in (200, 201)
    return c


@pytest.fixture(autouse=True)
def clean_food_tables():
    """Each test starts from an empty food/hydration slate."""
    yield
    for t in ("food_logs", "custom_foods", "hydration_logs"):
        try:
            execute(f"DELETE FROM {t}", commit=True)
        except Exception:
            pass


def _log(client, **overrides):
    body = {"food_name": "Test Rice", "meal_type": "lunch", "date_key": TODAY,
            "quantity_g": 100, "calories": 200, "protein": 5,
            "carbs": 40, "fat": 2, "fiber": 1}
    body.update(overrides)
    return client.post("/api/food/log", json=body)


# ══════════════════════════════════════════════════════════════════════════════
# Food log — request-shape rejections
# ══════════════════════════════════════════════════════════════════════════════

class TestFoodLogRejections:
    def test_requires_auth(self, app):
        anon = app.test_client()
        assert anon.post("/api/food/log", json={}).status_code == 401
        assert anon.get(f"/api/food/log/{TODAY}").status_code == 401

    def test_malformed_json_body_400(self, client):
        r = client.post("/api/food/log", data="{not json",
                        content_type="application/json")
        assert r.status_code == 400

    def test_empty_body_400(self, client):
        r = client.post("/api/food/log", data="",
                        content_type="application/json")
        assert r.status_code == 400

    def test_empty_object_unknown_food_404(self, client):
        # No pre-calculated calories and no known food_id → legacy lookup fails
        r = client.post("/api/food/log", json={})
        assert r.status_code == 404
        assert r.get_json()["success"] is False

    def test_missing_macros_unknown_food_id_404(self, client):
        r = client.post("/api/food/log",
                        json={"food_id": "no_such_food", "quantity_g": 100})
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Food log — PATCH quantity guardrails
# ══════════════════════════════════════════════════════════════════════════════

class TestFoodLogPatch:
    def _make(self, client):
        r = _log(client)
        assert r.status_code == 200
        return r.get_json()["log"]["id"]

    def test_patch_zero_quantity_rejected(self, client):
        lid = self._make(client)
        r = client.patch(f"/api/food/log/{lid}", json={"quantity_g": 0})
        assert r.status_code == 400

    def test_patch_negative_quantity_rejected(self, client):
        lid = self._make(client)
        r = client.patch(f"/api/food/log/{lid}", json={"quantity_g": -10})
        assert r.status_code == 400

    def test_patch_missing_quantity_rejected(self, client):
        lid = self._make(client)
        r = client.patch(f"/api/food/log/{lid}", json={})
        assert r.status_code == 400

    def test_patch_nonexistent_id_404(self, client):
        r = client.patch("/api/food/log/nope-123", json={"quantity_g": 50})
        assert r.status_code == 404

    def test_patch_scales_macros_proportionally(self, client):
        lid = self._make(client)
        r = client.patch(f"/api/food/log/{lid}", json={"quantity_g": 200})
        assert r.status_code == 200 and r.get_json()["success"]
        row = execute("SELECT * FROM food_logs WHERE id=?", (lid,), fetchone=True)
        assert row["quantity_g"] == 200
        assert row["calories"] == pytest.approx(400, abs=0.11)
        assert row["protein"] == pytest.approx(10, abs=0.11)

    def test_patch_scales_sugar_sodium_and_micronutrients_too(self, client):
        """Every per-portion value scales, not just the macros the UI shows.

        The PATCH used to rescale quantity/calories/protein/carbs/fat/fiber and
        silently leave sugar, sodium and the whole nutrients blob at their
        original values — so halving a portion halved the calories while sodium
        stayed put, permanently over-reporting it in the day's totals and in
        the nutrition advice built on them. For someone tracking sodium because
        of their blood pressure, a downward correction that leaves sodium
        untouched is the wrong direction to fail in.
        """
        # A real food, so the route derives micronutrients from the food DB.
        from food_data import FOOD_BY_ID
        food = next(f for f in FOOD_BY_ID.values() if f.get("calcium"))

        r = _log(client, food_id=food["id"], food_name=food["name"],
                 quantity_g=200, calories=100, sugar=20, sodium=50)
        lid = r.get_json()["log"]["id"]
        before = json.loads(execute("SELECT nutrients FROM food_logs WHERE id=?",
                                    (lid,), fetchone=True)["nutrients"])
        assert before["calcium"] > 0, "test needs a food with micronutrients"

        assert client.patch(f"/api/food/log/{lid}",
                            json={"quantity_g": 100}).status_code == 200

        row = execute("SELECT * FROM food_logs WHERE id=?", (lid,), fetchone=True)
        assert row["calories"] == pytest.approx(50, abs=0.11)
        assert row["sugar"] == pytest.approx(10, abs=0.11), "sugar didn't follow the portion"
        assert row["sodium"] == pytest.approx(25, abs=0.11), "sodium didn't follow the portion"
        after = json.loads(row["nutrients"])
        assert after["calcium"] == pytest.approx(before["calcium"] / 2, abs=0.11), \
            "micronutrients didn't follow the portion"

    def test_nutrients_are_stored_as_a_dict_not_double_encoded(self, client):
        """The route json.dumps()'d the nutrients dict and log_food jdump()'d it
        again, so the column held a string inside a string and one jload() gave
        back a str. get_nutrition_summary papered over it with an isinstance
        check; anything else reading the column would break on it."""
        from food_data import FOOD_BY_ID
        food = next(f for f in FOOD_BY_ID.values() if f.get("calcium"))
        r = _log(client, food_id=food["id"], food_name=food["name"], quantity_g=100)
        lid = r.get_json()["log"]["id"]

        raw = execute("SELECT nutrients FROM food_logs WHERE id=?", (lid,), fetchone=True)["nutrients"]
        assert isinstance(json.loads(raw), dict), \
            f"nutrients is double-encoded: {raw[:60]}"
        # …and the API hands back a dict, not a string
        assert isinstance(r.get_json()["log"]["nutrients"], dict)

    def test_patching_a_drink_keeps_its_hydration_credit_honest(self, client):
        """The auto-credited water has to follow the drink it came from.

        Deleting a food log already removed its credit; editing one didn't
        touch it. So correcting a 200ml chai down to a 100ml cup left the day
        still counting 200ml of water — for a drink that no longer exists at
        that size — quietly inflating the hydration total and its goal %.
        """
        from food_data import FOOD_BY_ID
        drink = next(f for f in FOOD_BY_ID.values()
                     if str(f.get("category", "")).lower() in
                     ("beverages", "indian beverages"))

        r = _log(client, food_id=drink["id"], food_name=drink["name"], quantity_g=200)
        lid = r.get_json()["log"]["id"]

        def credit():
            rows = execute("SELECT amount_ml FROM hydration_logs WHERE source_id=?",
                           (lid,), fetchall=True)
            return [x["amount_ml"] for x in rows]

        assert credit() == [200], "a logged drink should credit hydration"

        client.patch(f"/api/food/log/{lid}", json={"quantity_g": 100})
        assert credit() == [100], "the credit drifted from the drink it represents"

        # Below the 30ml threshold it stops representing anything.
        client.patch(f"/api/food/log/{lid}", json={"quantity_g": 20})
        assert credit() == [], "a sip too small to credit should leave no credit"

        # …and comes back when it's a real drink again.
        client.patch(f"/api/food/log/{lid}", json={"quantity_g": 250})
        assert credit() == [250]

    def test_patch_round_trip_does_not_drift(self, client):
        """Scaling is applied to the current row each time, so a there-and-back
        edit must land exactly where it started — not a rounding-error away."""
        r = _log(client, quantity_g=200, calories=100, sugar=20, sodium=50)
        lid = r.get_json()["log"]["id"]
        for qty in (100, 20, 200):
            client.patch(f"/api/food/log/{lid}", json={"quantity_g": qty})
        row = execute("SELECT * FROM food_logs WHERE id=?", (lid,), fetchone=True)
        assert row["quantity_g"] == 200
        assert row["calories"] == pytest.approx(100, abs=0.11)
        assert row["sugar"] == pytest.approx(20, abs=0.11)
        assert row["sodium"] == pytest.approx(50, abs=0.11)

    def test_patch_row_of_other_user_404(self, app, client):
        lid = self._make(client)
        other = app.test_client()
        r = other.post("/auth/register",
                       json={"email": "stress-food-b@medeasy.test", "password": PW})
        if r.status_code == 409:
            other.post("/auth/login",
                       json={"email": "stress-food-b@medeasy.test", "password": PW})
        r = other.patch(f"/api/food/log/{lid}", json={"quantity_g": 999})
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Food log — deletes are idempotent and safe
# ══════════════════════════════════════════════════════════════════════════════

class TestFoodLogDelete:
    def test_delete_then_double_delete(self, client):
        lid = _log(client).get_json()["log"]["id"]
        assert client.delete(f"/api/food/log/{lid}").status_code == 200
        # Row really gone
        row = execute("SELECT * FROM food_logs WHERE id=?", (lid,), fetchone=True)
        assert row is None
        # Second delete of the same id is now an honest 404 (already gone)
        assert client.delete(f"/api/food/log/{lid}").status_code == 404

    def test_delete_nonexistent_is_safe(self, client):
        # Safe (no crash / no cross-user effect) and honest about the miss.
        assert client.delete("/api/food/log/never-existed").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Food log — text content round-trips safely
# ══════════════════════════════════════════════════════════════════════════════

class TestFoodNameContent:
    def test_unicode_emoji_name_round_trip(self, client):
        name = "🍕🔥 पिज़्ज़ा με φέτα"
        r = _log(client, food_name=name)
        assert r.status_code == 200
        day = client.get(f"/api/food/log/{TODAY}").get_json()
        items = day["summary"]["by_meal"]["lunch"]["items"]
        assert any(i["food_name"] == name for i in items)

    def test_xss_string_stored_verbatim_not_executed_serverside(self, client):
        # Server treats names as opaque text; escaping is the client's job
        # (renderMealSections uses escHtml). Verify no mangling and no error.
        payload = "<img src=x onerror=alert(1)>"
        r = _log(client, food_name=payload)
        assert r.status_code == 200
        assert r.get_json()["log"]["food_name"] == payload

    def test_huge_name_does_not_crash(self, client):
        r = _log(client, food_name="x" * 10000)
        assert r.status_code == 200
        # Day view still renders (no 500)
        assert client.get(f"/api/food/log/{TODAY}").status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Nutrition summary — resilient reads
# ══════════════════════════════════════════════════════════════════════════════

class TestNutritionSummaryReads:
    def test_day_with_no_logs_is_zeroed(self, client):
        d = client.get("/api/food/log/1999-01-01").get_json()
        assert d["summary"]["log_count"] == 0
        assert d["summary"]["totals"]["calories"] == 0

    def test_garbage_date_key_returns_empty_not_500(self, client):
        # Dates are opaque keys server-side; a garbage key is just an empty day
        r = client.get("/api/food/log/garbage")
        assert r.status_code == 200
        assert r.get_json()["summary"]["log_count"] == 0

    def test_weekly_shape(self, client):
        _log(client)
        week = client.get("/api/food/weekly").get_json()
        assert len(week) == 7
        assert week[-1]["date"] == TODAY
        assert week[-1]["calories"] == pytest.approx(200, abs=0.11)

    def test_totals_aggregate_across_meals(self, client):
        _log(client, meal_type="breakfast", calories=100)
        _log(client, meal_type="dinner", calories=300)
        d = client.get(f"/api/food/log/{TODAY}").get_json()
        assert d["summary"]["totals"]["calories"] == pytest.approx(400, abs=0.11)
        assert set(d["summary"]["by_meal"]) == {"breakfast", "dinner"}


# ══════════════════════════════════════════════════════════════════════════════
# Hydration — happy paths and safe deletes
# ══════════════════════════════════════════════════════════════════════════════

class TestHydration:
    def test_requires_auth(self, app):
        anon = app.test_client()
        assert anon.post("/api/hydration", json={"amount_ml": 250}).status_code == 401

    def test_log_and_read_back(self, client):
        r = client.post("/api/hydration",
                        json={"amount_ml": 250, "drink_type": "water",
                              "date_key": TODAY})
        assert r.status_code == 200 and r.get_json()["success"]
        day = client.get(f"/api/hydration/{TODAY}").get_json()
        assert day["total_ml"] == 250
        assert day["goal_ml"] > 0
        assert 0 <= day["pct"] <= 100

    def test_pct_capped_at_100(self, client):
        client.post("/api/hydration",
                    json={"amount_ml": 99999, "date_key": TODAY})
        day = client.get(f"/api/hydration/{TODAY}").get_json()
        assert day["pct"] == 100

    def test_malformed_json_400(self, client):
        r = client.post("/api/hydration", data="{oops",
                        content_type="application/json")
        assert r.status_code == 400

    def test_empty_day_zeroed(self, client):
        day = client.get("/api/hydration/1999-01-01").get_json()
        assert day["total_ml"] == 0 and day["logs"] == []

    def test_week_shape(self, client):
        week = client.get("/api/hydration/week").get_json()
        assert len(week) == 7
        assert all("date" in d and "total_ml" in d for d in week)

    def test_delete_nonexistent_and_double_delete(self, client):
        client.post("/api/hydration", json={"amount_ml": 100, "date_key": TODAY})
        row = execute("SELECT id FROM hydration_logs LIMIT 1", fetchone=True)
        assert client.delete(f"/api/hydration/{row['id']}").status_code == 200
        assert client.delete(f"/api/hydration/{row['id']}").status_code == 200
        assert client.delete("/api/hydration/never-existed").status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Custom foods — validation
# ══════════════════════════════════════════════════════════════════════════════

class TestCustomFoods:
    def test_missing_name_400(self, client):
        r = client.post("/api/food/custom", json={"calories": 100})
        assert r.status_code == 400

    def test_empty_name_400(self, client):
        r = client.post("/api/food/custom", json={"name": "", "calories": 100})
        assert r.status_code == 400

    def test_unicode_name_round_trip(self, client):
        r = client.post("/api/food/custom",
                        json={"name": "माँ का खाना 🍲", "calories": 350})
        assert r.status_code == 200
        db = client.get("/api/food/db").get_json()
        assert any(f["name"] == "माँ का खाना 🍲" for f in db["custom"])

    def test_custom_food_search_filter(self, client):
        client.post("/api/food/custom", json={"name": "ZebraShake", "calories": 90})
        client.post("/api/food/custom", json={"name": "Other", "calories": 10})
        db = client.get("/api/food/db?q=zebrashake").get_json()
        names = [f["name"] for f in db["custom"]]
        assert names == ["ZebraShake"]


# ══════════════════════════════════════════════════════════════════════════════
# Food DB search — hostile query strings
# ══════════════════════════════════════════════════════════════════════════════

class TestFoodDbSearch:
    def test_huge_query_no_crash(self, client):
        r = client.get("/api/food/db?q=" + "z" * 5000)
        assert r.status_code == 200
        assert r.get_json()["foods"] == []

    def test_nonsense_category_empty(self, client):
        r = client.get("/api/food/db?category=NotARealCategory")
        assert r.status_code == 200
        assert r.get_json()["foods"] == []

    def test_default_search_returns_foods_and_categories(self, client):
        d = client.get("/api/food/db").get_json()
        assert len(d["foods"]) > 0
        assert len(d["categories"]) > 0
        # every result exposes a calories key (legacy 'cal' normalised)
        assert all("calories" in f or "cal" in f for f in d["foods"])


# ══════════════════════════════════════════════════════════════════════════════
# Barcode — input validation (no network: invalid codes fail pre-lookup)
# ══════════════════════════════════════════════════════════════════════════════

class TestBarcodeValidation:
    @pytest.mark.parametrize("code", [
        "abcdefgh",          # letters
        "1234567",           # 7 digits — too short
        "123456789012345",   # 15 digits — too long
        "1234%20678",        # url junk
    ])
    def test_invalid_codes_400(self, client, code):
        assert client.get(f"/api/food/barcode/{code}").status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# Profile / TDEE — empty profile degrades gracefully (except calorie-balance,
# which is a known bug and not asserted here)
# ══════════════════════════════════════════════════════════════════════════════

class TestEmptyProfile:
    def test_profile_get_with_no_data(self, client):
        d = client.get("/api/food/profile").get_json()
        assert "profile" in d and "targets" in d

    def test_tdee_targets_null_when_profile_incomplete(self, client):
        from db.food import calc_tdee
        t = calc_tdee({"weight_kg": None, "height_cm": None,
                       "age": None, "gender": None})
        assert t["target_calories"] is None
        assert t["bmr"] is None and t["tdee"] is None
        assert t["fiber_g"] == 30  # only universal default survives

    def test_food_day_view_works_with_empty_profile(self, client):
        # /api/food/log/<date> must not 500 for a brand-new user
        r = client.get(f"/api/food/log/{TODAY}")
        assert r.status_code == 200
        d = r.get_json()
        assert d["targets"]["target_calories"] is None
        assert isinstance(d["suggestions"], list)

    def test_recent_meals_empty_state(self, client):
        d = client.get("/api/food/recent-meals").get_json()
        assert d["combos"] == []
        assert d["yesterday"] == {}
        assert d["yesterday_total_cal"] == 0

    def test_calorie_balance_works_once_profile_complete(self, client):
        client.post("/api/food/profile",
                    json={"weight_kg": 70, "height_cm": 175, "age": 30,
                          "gender": "male", "activity_level": "moderate",
                          "goal": "maintain"})
        r = client.get("/api/calorie-balance")
        assert r.status_code == 200
        d = r.get_json()
        assert d["today"]["target"] > 0
        assert len(d["daily"]) == 7
        # reset profile fields so other tests keep the empty-profile world
        execute("UPDATE user_profile SET weight_kg=NULL, height_cm=NULL, "
                "age=NULL, gender=NULL", commit=True)


# ══════════════════════════════════════════════════════════════════════════════
# Recent meals — combos group and rank correctly
# ══════════════════════════════════════════════════════════════════════════════

class TestRecentMeals:
    def test_yesterday_combo_appears(self, client):
        yday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        _log(client, date_key=yday, meal_type="dinner",
             food_name="Dal", calories=180)
        _log(client, date_key=yday, meal_type="dinner",
             food_name="Rice", calories=210)
        d = client.get("/api/food/recent-meals").get_json()
        assert d["yesterday_total_cal"] == 390
        assert len(d["combos"]) == 1
        combo = d["combos"][0]
        assert combo["meal_type"] == "dinner"
        assert combo["item_count"] == 2
        assert combo["total_cal"] == pytest.approx(390, abs=0.11)
        assert "Dal" in combo["label"] and "Rice" in combo["label"]

    def test_today_logs_not_in_combos(self, client):
        _log(client, date_key=TODAY, food_name="Today Only")
        d = client.get("/api/food/recent-meals").get_json()
        assert all("Today Only" not in c["label"] for c in d["combos"])
