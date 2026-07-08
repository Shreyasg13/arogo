"""
tests/test_api.py — MedEasy Health OS Complete API Test Suite
==============================================================
Covers all 13 features across 55+ assertions verified against the
real database schema.

Run:
    python tests/test_api.py          # standalone (no pytest needed)
    pytest tests/test_api.py -v       # with pytest
    pytest tests/test_api.py -k food  # one feature
"""
import os, sys, datetime, json

# ── Ensure MEDEASY_DB=:memory: before any app import ──────────────────────────
os.environ["MEDEASY_DB"] = ":memory:"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    # Provide stub decorators so the class/method syntax still works standalone
    class _Pytest:
        class fixture:
            def __init__(self, *a, **kw): pass
            def __call__(self, fn): return fn
        class mark:
            parametrize = staticmethod(lambda *a, **kw: lambda fn: fn)
    pytest = _Pytest()
from db.core import init_db, execute
from app import create_app

TODAY     = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

TEST_EMAIL = "tester@medeasy.test"
TEST_PW    = "test-password-123"


def make_authed_client(application, email, password=TEST_PW):
    """Return a test client logged in as `email` (registers on first use)."""
    c = application.test_client()
    r = c.post("/auth/register", json={"email": email, "password": password})
    if r.status_code == 409:  # already registered — just log in
        r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code in (200, 201), f"auth failed: {r.status_code} {r.get_json()}"
    return c


@pytest.fixture(scope="session")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    yield application


@pytest.fixture(scope="session")
def client(app):
    """Authenticated client — all API routes require a session cookie."""
    return make_authed_client(app, TEST_EMAIL)


@pytest.fixture(autouse=True)
def clean(client):
    """Wipe all data between tests so each runs independently."""
    yield
    for t in ["medicines","dose_logs","fitness_activities","food_logs","custom_foods",
              "thoughts","todos","hydration_logs","sleep_logs","body_metrics",
              "habits","habit_logs","symptoms","vitals","notification_log","reports"]:
        try: execute(f"DELETE FROM {t}", commit=True)
        except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def jget(c, url):
    r = c.get(url); return r.status_code, r.get_json()

def jpost(c, url, body=None):
    r = c.post(url, json=body or {}); return r.status_code, r.get_json()

def jput(c, url, body=None):
    r = c.put(url, json=body or {}); return r.status_code, r.get_json()

def jdel(c, url):
    r = c.delete(url); return r.status_code, r.get_json()


# ══════════════════════════════════════════════════════════════════════════════
# 1. DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

class TestDashboard:
    """Feature: SPA root + wellness dashboard strip."""

    def test_root_200(self, client):
        assert client.get("/").status_code == 200

    def test_wellness_today_shape(self, client):
        code, d = jget(client, "/api/wellness/today")
        assert code == 200
        for key in ["hydration", "sleep", "habits", "symptoms"]:
            assert key in d

    def test_wellness_habits_structure(self, client):
        _, d = jget(client, "/api/wellness/today")
        h = d["habits"]
        assert "done" in h and "total" in h


# ══════════════════════════════════════════════════════════════════════════════
# 2. MEDICAL REPORTS
# ══════════════════════════════════════════════════════════════════════════════

class TestReports:
    """Feature: Report listing."""

    def test_list_reports_empty(self, client):
        code, d = jget(client, "/api/reports")
        assert code == 200
        assert isinstance(d, list)

    def test_stats_endpoint(self, client):
        code, _ = jget(client, "/api/stats")
        assert code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 3. MEDICINES
# ══════════════════════════════════════════════════════════════════════════════

MED = {"name":"Metformin","dosage":"500","unit":"mg",
       "frequency":"twice_daily","times":["08:00","20:00"],"icon":"💊","color":"teal"}

class TestMedicines:
    """Feature: Medicine CRUD, dose logging, pill stock, low-stock alerts."""

    def _create(self, client):
        _, d = jpost(client, "/api/medicines", MED)
        assert d["success"]
        return d["medicine"]["id"]

    def test_create(self, client):
        assert self._create(client)

    def test_list_after_create(self, client):
        self._create(client)
        _, meds = jget(client, "/api/medicines")
        assert len(meds) == 1 and meds[0]["name"] == "Metformin"

    def test_today_doses_twice_daily(self, client):
        self._create(client)
        _, doses = jget(client, "/api/medicines/today")
        assert isinstance(doses, list) and len(doses) == 2

    def test_log_dose_taken(self, client):
        mid = self._create(client)
        code, d = jpost(client, f"/api/medicines/{mid}/log",
                        {"scheduled": "08:00", "taken": True})
        assert code == 200 and d["success"]

    def test_stock_update(self, client):
        mid = self._create(client)
        code, d = jpost(client, f"/api/medicines/{mid}/stock",
                        {"pill_count": 30, "pills_per_dose": 1, "refill_threshold": 7})
        assert code == 200 and d["success"]

    def test_low_stock_alert(self, client):
        mid = self._create(client)
        jpost(client, f"/api/medicines/{mid}/stock",
              {"pill_count": 5, "pills_per_dose": 1, "refill_threshold": 7})
        _, low = jget(client, "/api/medicines/low-stock")
        assert any(m["name"] == "Metformin" for m in low)

    def test_no_low_stock_when_sufficient(self, client):
        mid = self._create(client)
        jpost(client, f"/api/medicines/{mid}/stock",
              {"pill_count": 60, "pills_per_dose": 1, "refill_threshold": 7})
        _, low = jget(client, "/api/medicines/low-stock")
        assert not any(m["name"] == "Metformin" for m in low)

    def test_toggle_medicine(self, client):
        mid = self._create(client)
        code, d = jpost(client, f"/api/medicines/{mid}/toggle")
        assert code == 200

    def test_delete_medicine(self, client):
        mid = self._create(client)
        code, d = jdel(client, f"/api/medicines/{mid}")
        assert code == 200 and d["success"]
        _, meds = jget(client, "/api/medicines")
        assert len(meds) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. FITNESS
# ══════════════════════════════════════════════════════════════════════════════

ACT = {"name":"Morning Run","type":"running","date":TODAY,
       "duration":45,"calories":400,"distance":6.5,"source":"manual"}

class TestFitness:
    """Feature: Activity CRUD, fitness stats."""

    def _create(self, client):
        _, d = jpost(client, "/api/fitness/activities", ACT)
        assert d["success"]
        return d["activity"]["id"]

    def test_create_activity(self, client):
        assert self._create(client)

    def test_list_activities(self, client):
        self._create(client)
        _, acts = jget(client, "/api/fitness/activities")
        assert len(acts) == 1

    def test_fitness_stats(self, client):
        self._create(client)
        code, _ = jget(client, "/api/fitness/stats")
        assert code == 200

    def test_calendar_endpoint(self, client):
        code, _ = jget(client, "/api/fitness/calendar")
        assert code == 200

    def test_delete_activity(self, client):
        aid = self._create(client)
        code, d = jdel(client, f"/api/fitness/activities/{aid}")
        assert code == 200 and d["success"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. FOOD TRACKER
# ══════════════════════════════════════════════════════════════════════════════

FOOD_LOG = {"food_name":"Dal Tarka","meal_type":"lunch","date_key":TODAY,
            "quantity_g":200,"calories":232,"protein":15,"carbs":35,"fat":5.6,"fiber":6.4}

class TestFood:
    """Feature: Food DB search/category filter, meal log CRUD, custom foods, profile."""

    def test_food_db_returns_foods(self, client):
        _, d = jget(client, "/api/food/db")
        assert len(d["foods"]) > 0

    def test_food_db_42_categories(self, client):
        _, d = jget(client, "/api/food/db")
        assert len(d["categories"]) == 42

    def test_search_whey(self, client):
        _, d = jget(client, "/api/food/db?q=whey")
        assert len(d["foods"]) >= 1
        assert any("whey" in f["name"].lower() for f in d["foods"])

    def test_category_filter_dairy(self, client):
        _, d = jget(client, "/api/food/db?category=Dairy")
        assert all(f["category"] == "Dairy" for f in d["foods"])

    def test_all_foods_have_calories_key(self, client):
        _, d = jget(client, "/api/food/db?q=dal")
        for f in d["foods"]:
            assert "calories" in f, f"Missing calories in {f['name']}"

    def test_log_food(self, client):
        code, d = jpost(client, "/api/food/log", FOOD_LOG)
        assert code == 200 and d["success"]

    def test_get_food_log_by_date(self, client):
        jpost(client, "/api/food/log", FOOD_LOG)
        code, _ = jget(client, f"/api/food/log/{TODAY}")
        assert code == 200

    def test_delete_food_log(self, client):
        _, d = jpost(client, "/api/food/log", FOOD_LOG)
        lid = d["log"]["id"]
        code, d2 = jdel(client, f"/api/food/log/{lid}")
        assert code == 200 and d2["success"]

    def test_custom_food_create(self, client):
        code, d = jpost(client, "/api/food/custom",
                        {"name":"My Shake","calories":150,"protein":30,"carbs":5,"fat":2,"serving_g":40})
        assert code == 200 and d["success"]
        assert d["food"]["name"] == "My Shake"

    def test_custom_food_rejected_without_name(self, client):
        code, d = jpost(client, "/api/food/custom", {"calories": 100})
        assert code in (400, 200)
        if code == 200:
            assert not d.get("success")

    def test_custom_food_appears_in_search(self, client):
        jpost(client, "/api/food/custom",
              {"name":"Ayush Shake","calories":200,"protein":40,"carbs":5,"fat":1,"serving_g":50})
        _, d = jget(client, "/api/food/db?q=ayush")
        all_foods = d.get("foods", []) + d.get("custom", [])
        assert any("Ayush" in f["name"] for f in all_foods)

    def test_food_profile_get(self, client):
        code, d = jget(client, "/api/food/profile")
        assert code == 200 and "profile" in d and "targets" in d

    def test_food_profile_update(self, client):
        code, d = jpost(client, "/api/food/profile",
                        {"name":"Ayush","weight_kg":70,"height_cm":175,
                         "age":25,"gender":"male",
                         "activity_level":"moderate","goal":"maintain"})
        assert code == 200 and d["success"]
        assert d["targets"]["target_calories"] > 0

    def test_weekly_nutrition(self, client):
        code, _ = jget(client, "/api/food/weekly")
        assert code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 6. HABITS
# ══════════════════════════════════════════════════════════════════════════════

class TestHabits:
    """Feature: Habit CRUD, daily toggle, streak tracking, 7-day/28-day history."""

    def _create(self, client):
        _, d = jpost(client, "/api/habits",
                     {"name":"Meditate","emoji":"🧘","color":"#7C3AED"})
        assert d["success"]
        return d["habit"]["id"]

    def test_create_habit(self, client):
        assert self._create(client)

    def test_habit_fields_present(self, client):
        hid = self._create(client)
        jpost(client, f"/api/habits/{hid}/toggle", {"date_key": TODAY})
        _, d = jget(client, "/api/habits")
        h = d["habits"][0]
        for field in ["id","name","emoji","color","done_today","streak","week7","cal28"]:
            assert field in h, f"Missing field: {field}"

    def test_week7_is_7_days(self, client):
        hid = self._create(client)
        _, d = jget(client, "/api/habits")
        assert len(d["habits"][0]["week7"]) == 7

    def test_cal28_is_28_days(self, client):
        hid = self._create(client)
        _, d = jget(client, "/api/habits")
        assert len(d["habits"][0]["cal28"]) == 28

    def test_toggle_marks_done(self, client):
        hid = self._create(client)
        jpost(client, f"/api/habits/{hid}/toggle", {"date_key": TODAY})
        _, d = jget(client, "/api/habits")
        h = next(x for x in d["habits"] if x["id"] == hid)
        assert h["done_today"] is True

    def test_double_toggle_undoes(self, client):
        hid = self._create(client)
        jpost(client, f"/api/habits/{hid}/toggle", {"date_key": TODAY})
        jpost(client, f"/api/habits/{hid}/toggle", {"date_key": TODAY})
        _, d = jget(client, "/api/habits")
        h = next(x for x in d["habits"] if x["id"] == hid)
        assert h["done_today"] is False

    def test_delete_habit(self, client):
        hid = self._create(client)
        code, d = jdel(client, f"/api/habits/{hid}")
        assert code == 200 and d["success"]
        _, d2 = jget(client, "/api/habits")
        assert not any(h["id"] == hid for h in d2["habits"])


# ══════════════════════════════════════════════════════════════════════════════
# 7. THOUGHTS / JOURNAL
# ══════════════════════════════════════════════════════════════════════════════

class TestThoughts:
    """Feature: Daily journal CRUD, mood tracking."""

    def test_save_thought(self, client):
        code, d = jpost(client, "/api/thoughts",
                        {"content":"Feeling great!","mood":"happy","date_key":TODAY})
        assert code == 200 and d["success"]
        assert d["thought"]["content"] == "Feeling great!"

    def test_update_thought(self, client):
        _, c1 = jpost(client, "/api/thoughts",
                      {"content":"Original","mood":"neutral","date_key":TODAY})
        tid = c1["thought"]["id"]
        code, d = jput(client, f"/api/thoughts/{tid}",
                       {"content":"Updated","mood":"happy"})
        assert code == 200
        assert d["thought"]["content"] == "Updated"

    def test_delete_thought(self, client):
        _, c1 = jpost(client, "/api/thoughts",
                      {"content":"To delete","mood":"sad","date_key":TODAY})
        tid = c1["thought"]["id"]
        code, d = jdel(client, f"/api/thoughts/{tid}")
        assert code == 200 and d["success"]

    def test_get_thoughts_by_date(self, client):
        jpost(client, "/api/thoughts",
              {"content":"Day thought","mood":"calm","date_key":TODAY})
        code, _ = jget(client, f"/api/thoughts/{TODAY}")
        assert code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 8. TO-DO LIST
# ══════════════════════════════════════════════════════════════════════════════

class TestTodos:
    """Feature: Task CRUD, status toggle, priorities."""

    def _create(self, client):
        _, d = jpost(client, "/api/todos",
                     {"title":"Call doctor","priority":"high"})
        assert d["success"]
        return d["todo"]["id"]

    def test_create_todo(self, client):
        assert self._create(client)

    def test_default_status_pending(self, client):
        tid = self._create(client)
        _, d = jget(client, "/api/todos")
        t = next(x for x in d["todos"] if x["id"] == tid)
        assert t["status"] == "pending"

    def test_toggle_makes_done(self, client):
        tid = self._create(client)
        jpost(client, f"/api/todos/{tid}/toggle")
        _, d = jget(client, "/api/todos")
        t = next(x for x in d["todos"] if x["id"] == tid)
        assert t["status"] == "done"

    def test_update_todo(self, client):
        tid = self._create(client)
        code, d = jput(client, f"/api/todos/{tid}", {"title":"Reschedule"})
        assert code == 200 and d["todo"]["title"] == "Reschedule"

    def test_delete_todo(self, client):
        tid = self._create(client)
        code, d = jdel(client, f"/api/todos/{tid}")
        assert code == 200 and d["success"]


# ══════════════════════════════════════════════════════════════════════════════
# 9. HYDRATION
# ══════════════════════════════════════════════════════════════════════════════

class TestHydration:
    """Feature: Water logging, goal calculation (35ml/kg), percentage tracking."""

    def test_get_empty_day(self, client):
        code, d = jget(client, f"/api/hydration/{TODAY}")
        assert code == 200

    def test_goal_ml_present(self, client):
        _, d = jget(client, f"/api/hydration/{TODAY}")
        assert d.get("goal_ml", 0) > 0

    def test_pct_is_number_not_undefined(self, client):
        _, d = jget(client, f"/api/hydration/{TODAY}")
        assert isinstance(d.get("pct"), (int, float))

    def test_log_water(self, client):
        code, d = jpost(client, "/api/hydration",
                        {"amount_ml": 500, "drink_type": "water", "date_key": TODAY})
        assert code == 200 and d["success"]

    def test_total_ml_accumulates(self, client):
        jpost(client, "/api/hydration", {"amount_ml": 250, "drink_type": "water", "date_key": TODAY})
        jpost(client, "/api/hydration", {"amount_ml": 500, "drink_type": "water", "date_key": TODAY})
        _, d = jget(client, f"/api/hydration/{TODAY}")
        assert d["total_ml"] == 750

    def test_pct_capped_at_100(self, client):
        jpost(client, "/api/hydration", {"amount_ml": 9999, "drink_type": "water", "date_key": TODAY})
        _, d = jget(client, f"/api/hydration/{TODAY}")
        assert d["pct"] <= 100

    def test_delete_hydration_log(self, client):
        jpost(client, "/api/hydration", {"amount_ml": 250, "drink_type": "water", "date_key": TODAY})
        _, d = jget(client, f"/api/hydration/{TODAY}")
        lid = d["logs"][0]["id"]
        code, d2 = jdel(client, f"/api/hydration/{lid}")
        assert code == 200 and d2["success"]


# ══════════════════════════════════════════════════════════════════════════════
# 10. SLEEP
# ══════════════════════════════════════════════════════════════════════════════

class TestSleep:
    """Feature: Sleep log, auto duration calculation, quality rating, CRUD."""

    SLEEP = {"bedtime": f"{YESTERDAY}T23:00", "wake_time": f"{TODAY}T07:00", "quality": 4}

    def test_log_sleep(self, client):
        code, d = jpost(client, "/api/sleep", self.SLEEP)
        assert code == 200 and d["success"]

    def test_duration_8_hours(self, client):
        _, d = jpost(client, "/api/sleep", self.SLEEP)
        assert abs(d["log"]["duration_h"] - 8.0) < 0.1

    def test_duration_derived_no_date_key(self, client):
        """date_key should be derived from bedtime if not provided."""
        _, d = jpost(client, "/api/sleep",
                     {"bedtime": f"{YESTERDAY}T22:00",
                      "wake_time": f"{TODAY}T06:00", "quality": 3})
        assert d["success"]
        assert d["log"]["duration_h"] == 8.0

    def test_list_sleep(self, client):
        jpost(client, "/api/sleep", self.SLEEP)
        code, logs = jget(client, "/api/sleep")
        assert code == 200 and len(logs) == 1

    def test_delete_sleep(self, client):
        _, d = jpost(client, "/api/sleep", self.SLEEP)
        lid = d["log"]["id"]
        code, d2 = jdel(client, f"/api/sleep/{lid}")
        assert code == 200 and d2["success"]


# ══════════════════════════════════════════════════════════════════════════════
# 11. MEDICAL — SYMPTOMS, VITALS, EMERGENCY
# ══════════════════════════════════════════════════════════════════════════════

class TestMedical:
    """Feature: Symptom diary, vitals (BP/HR/BG), emergency health card."""

    def test_log_symptom(self, client):
        code, d = jpost(client, "/api/symptoms",
                        {"name":"Headache","severity":6,
                         "date_key":TODAY,"time_of_day":"evening"})
        assert code == 200 and d["success"]

    def test_list_symptoms(self, client):
        jpost(client, "/api/symptoms",
              {"name":"Fatigue","severity":4,"date_key":TODAY,"time_of_day":"morning"})
        code, d = jget(client, "/api/symptoms")
        assert code == 200 and len(d) >= 1

    def test_delete_symptom(self, client):
        _, d = jpost(client, "/api/symptoms",
                     {"name":"Back Pain","severity":5,"date_key":TODAY,"time_of_day":"all_day"})
        sid = d["symptom"]["id"]
        code, d2 = jdel(client, f"/api/symptoms/{sid}")
        assert code == 200 and d2["success"]

    def test_log_vital_blood_pressure(self, client):
        code, d = jpost(client, "/api/vitals",
                        {"type":"blood_pressure","value1":120,"value2":80,
                         "unit":"mmHg","date_key":TODAY})
        assert code == 200 and d["success"]

    def test_log_vital_heart_rate(self, client):
        code, d = jpost(client, "/api/vitals",
                        {"type":"heart_rate","value1":72,"unit":"bpm","date_key":TODAY})
        assert code == 200 and d["success"]

    def test_delete_vital(self, client):
        _, d = jpost(client, "/api/vitals",
                     {"type":"blood_sugar","value1":95,"unit":"mg/dL","date_key":TODAY})
        vid = d["vital"]["id"]
        code, d2 = jdel(client, f"/api/vitals/{vid}")
        assert code == 200 and d2["success"]

    def test_emergency_save_and_get(self, client):
        code, d = jpost(client, "/api/emergency",
                        {"blood_type":"O+","allergies":"Penicillin",
                         "contact1_name":"Mum","contact1_phone":"+91-9876543210"})
        assert code == 200 and d["success"]
        code2, _ = jget(client, "/api/emergency")
        assert code2 == 200


# ══════════════════════════════════════════════════════════════════════════════
# 12. BODY METRICS
# ══════════════════════════════════════════════════════════════════════════════

class TestBodyMetrics:
    """Feature: Weight/BMI/body-fat tracking."""

    def test_log_body_metrics(self, client):
        code, d = jpost(client, "/api/body-metrics",
                        {"weight_kg":72.5,"body_fat_pct":18.0,"date_key":TODAY})
        assert code == 200 and d["success"]

    def test_bmi_calculated(self, client):
        jpost(client, "/api/food/profile",
              {"weight_kg":72.5,"height_cm":175,"age":28,"activity_level":"moderate","goal":"maintain"})
        _, d = jpost(client, "/api/body-metrics", {"weight_kg":72.5,"date_key":TODAY})
        if d["metric"].get("bmi"):
            assert 15 < d["metric"]["bmi"] < 40

    def test_list_body_metrics(self, client):
        jpost(client, "/api/body-metrics", {"weight_kg":70,"date_key":TODAY})
        code, d = jget(client, "/api/body-metrics")
        assert code == 200 and isinstance(d, list)


# ══════════════════════════════════════════════════════════════════════════════
# 13. NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifications:
    """Feature: Notification centre, unread count, mark read/mark all."""

    def test_list_empty(self, client):
        code, d = jget(client, "/api/notifications")
        assert code == 200 and "unread" in d and "notifications" in d

    def test_create_notification(self, client):
        code, d = jpost(client, "/api/notifications",
                        {"type":"medicine","title":"Take Metformin","body":"500mg"})
        assert code == 200 and d["success"]

    def test_unread_count_increments(self, client):
        jpost(client, "/api/notifications", {"type":"refill","title":"Restock"})
        jpost(client, "/api/notifications", {"type":"system","title":"Welcome"})
        _, d = jget(client, "/api/notifications")
        assert d["unread"] == 2

    def test_mark_single_read(self, client):
        _, d = jpost(client, "/api/notifications", {"type":"sleep","title":"Log sleep"})
        nid = d["notification"]["id"]
        code, d2 = jpost(client, f"/api/notifications/{nid}/read")
        assert code == 200 and d2["unread"] == 0

    def test_mark_all_read(self, client):
        jpost(client, "/api/notifications", {"type":"medicine","title":"Dose 1"})
        jpost(client, "/api/notifications", {"type":"medicine","title":"Dose 2"})
        code, _ = jpost(client, "/api/notifications/read-all")
        assert code == 200
        _, d = jget(client, "/api/notifications")
        assert d["unread"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 14. INSIGHTS — SEARCH, PROGRESS, REPORT, EXPORT
# ══════════════════════════════════════════════════════════════════════════════

class TestInsights:
    """Feature: Global search, goal progress, weekly report, data export."""

    def test_search_empty(self, client):
        code, d = jget(client, "/api/search?q=test")
        assert code == 200 and "total" in d and "sections" in d

    def test_short_query_returns_empty(self, client):
        _, d = jget(client, "/api/search?q=a")
        assert d["total"] == 0

    def test_search_finds_symptom(self, client):
        jpost(client, "/api/symptoms",
              {"name":"Migraine","severity":8,"date_key":TODAY,"time_of_day":"morning"})
        _, d = jget(client, "/api/search?q=migraine")
        assert d["total"] >= 1
        assert any(s["type"] == "symptom" for s in d["sections"])

    def test_search_finds_todo(self, client):
        jpost(client, "/api/todos", {"title":"Buy omega-3 supplements","priority":"low"})
        _, d = jget(client, "/api/search?q=omega")
        assert d["total"] >= 1

    def test_progress_shape(self, client):
        code, d = jget(client, "/api/progress")
        assert code == 200
        for key in ["profile","workouts","habits","sleep","nutrition"]:
            assert key in d, f"Missing key in progress: {key}"

    def test_weekly_report_shape(self, client):
        code, d = jget(client, "/api/report/weekly")
        assert code == 200
        for key in ["period","sleep","fitness","nutrition","habits","symptoms"]:
            assert key in d



# ══════════════════════════════════════════════════════════════════════════════
# 15. INTEGRATION — multi-step real-world workflows
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """End-to-end workflows that cross multiple features."""

    def test_full_medicine_refill_workflow(self, client):
        _, m = jpost(client, "/api/medicines",
                     {"name":"Vitamin D","dosage":"1000","unit":"IU",
                      "frequency":"once_daily","times":["09:00"],"icon":"💊","color":"teal"})
        mid = m["medicine"]["id"]
        # Set low stock → alert fires
        jpost(client, f"/api/medicines/{mid}/stock",
              {"pill_count": 5, "pills_per_dose": 1, "refill_threshold": 7})
        _, low = jget(client, "/api/medicines/low-stock")
        assert any(m["name"] == "Vitamin D" for m in low)
        # Restock → alert clears
        jpost(client, f"/api/medicines/{mid}/stock",
              {"pill_count": 60, "pills_per_dose": 1, "refill_threshold": 7})
        _, low2 = jget(client, "/api/medicines/low-stock")
        assert not any(m["name"] == "Vitamin D" for m in low2)

    def test_full_day_wellness_workflow(self, client):
        """Log food + water + habit + sleep → wellness strip reflects all."""
        jpost(client, "/api/food/log",
              {"food_name":"Boiled Egg","meal_type":"breakfast","date_key":TODAY,
               "quantity_g":50,"calories":78,"protein":6.3,"carbs":0.6,"fat":5.3,"fiber":0})

        jpost(client, "/api/hydration",
              {"amount_ml": 500, "drink_type": "water", "date_key": TODAY})

        _, h = jpost(client, "/api/habits", {"name":"Walk","emoji":"🚶","color":"#0E8F7E"})
        hid = h["habit"]["id"]
        jpost(client, f"/api/habits/{hid}/toggle", {"date_key": TODAY})

        jpost(client, "/api/sleep",
              {"bedtime": f"{YESTERDAY}T22:30", "wake_time": f"{TODAY}T06:30", "quality": 4})

        code, w = jget(client, "/api/wellness/today")
        assert code == 200
        assert w["hydration"]["total_ml"] == 500
        assert w["habits"]["done"] == 1
        assert w["habits"]["total"] == 1

    def test_search_across_multiple_data_types(self, client):
        """Seed multiple types and verify search returns them all."""
        jpost(client, "/api/symptoms",
              {"name":"Back Pain","severity":5,"date_key":TODAY,"time_of_day":"all_day"})
        jpost(client, "/api/todos",
              {"title":"Buy back pain relief patches","priority":"medium"})

        _, d_sym  = jget(client, "/api/search?q=back")
        _, d_todo = jget(client, "/api/search?q=patches")

        assert d_sym["total"] >= 1
        assert d_todo["total"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner (no pytest required)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    os.environ["MEDEASY_DB"] = ":memory:"
    init_db()
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()

    passed = failed = 0
    TABLES = ["medicines","dose_logs","fitness_activities","food_logs","custom_foods",
              "thoughts","todos","hydration_logs","sleep_logs","body_metrics",
              "habits","habit_logs","symptoms","vitals","notification_log"]

    def clean():
        for t in TABLES:
            try: execute(f"DELETE FROM {t}", commit=True)
            except Exception: pass

    def run(name, fn):
        global passed, failed
        try:
            fn(c)
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        finally:
            clean()

    print("\n" + "="*60)
    print("  MedEasy Health OS — API Test Suite (standalone)")
    print("="*60 + "\n")

    suites = [
        TestDashboard, TestReports, TestMedicines, TestFitness,
        TestFood, TestHabits, TestThoughts, TestTodos, TestHydration,
        TestSleep, TestMedical, TestBodyMetrics, TestNotifications,
        TestInsights, TestIntegration,
    ]

    for Suite in suites:
        suite = Suite()
        label = Suite.__doc__.split(".")[0] if Suite.__doc__ else Suite.__name__
        print(f"── {label} ──")
        for attr in dir(suite):
            if attr.startswith("test_"):
                run(f"{Suite.__name__}.{attr}", getattr(suite, attr))
        print()

    print("="*60)
    print(f"  {passed} passed  •  {failed} failed  •  {passed+failed} total")
    print("="*60)
    sys.exit(0 if failed == 0 else 1)
