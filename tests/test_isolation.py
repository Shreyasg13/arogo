"""
tests/test_isolation.py — Multi-user data isolation suite.

Proves that user A can never see, modify, or delete user B's data —
the core guarantee of Phase 2. Every data domain gets:
  1. a "B cannot read A's rows" check
  2. where applicable, a "B cannot modify/delete A's rows by id" check

Run:  pytest tests/test_isolation.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
from db.core import init_db
from app import create_app

TODAY = datetime.date.today().isoformat()


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


def _authed(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": "isolation-pw-123"})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": "isolation-pw-123"})
    assert r.status_code in (200, 201)
    return c


@pytest.fixture(scope="module")
def alice(app):
    return _authed(app, "alice@medeasy.test")


@pytest.fixture(scope="module")
def bob(app):
    return _authed(app, "bob@medeasy.test")


# ── Auth basics ────────────────────────────────────────────────────────────────

class TestAuthBoundary:
    def test_unauthenticated_gets_401(self, app):
        anon = app.test_client()
        for url in ["/api/reports", "/api/medicines", "/api/todos",
                    "/api/sleep", "/api/vitals", "/api/notifications"]:
            assert anon.get(url).status_code == 401, url

    def test_two_users_have_distinct_sessions(self, alice, bob):
        a = alice.get("/auth/me").get_json()
        b = bob.get("/auth/me").get_json()
        assert a["id"] != b["id"]
        assert a["email"] == "alice@medeasy.test"
        assert b["email"] == "bob@medeasy.test"


# ── Per-domain isolation ───────────────────────────────────────────────────────

def _food_logs(client, date_key):
    """Flatten GET /api/food/log/<date> (summary.by_meal.*.items) into one list."""
    summary = client.get(f"/api/food/log/{date_key}").get_json()["summary"]
    return [item for meal in summary["by_meal"].values() for item in meal["items"]]


class TestFoodIsolation:
    def test_food_logs_are_private(self, alice, bob):
        r = alice.post("/api/food/log", json={
            "food_name": "Alice Secret Salad", "meal_type": "lunch",
            "date_key": TODAY, "calories": 350})
        assert r.status_code == 200
        assert all(l["food_name"] != "Alice Secret Salad" for l in _food_logs(bob, TODAY))
        assert any(l["food_name"] == "Alice Secret Salad" for l in _food_logs(alice, TODAY))

    def test_bob_cannot_delete_alices_food(self, alice, bob):
        r = alice.post("/api/food/log", json={
            "food_name": "Alice Toast", "date_key": TODAY, "calories": 120})
        lid = r.get_json()["log"]["id"]
        bob.delete(f"/api/food/log/{lid}")  # returns success but must be a no-op
        assert any(l["id"] == lid for l in _food_logs(alice, TODAY)), \
            "Bob deleted Alice's food log!"

    def test_custom_foods_are_private(self, alice, bob):
        alice.post("/api/food/custom", json={"name": "Alice Protein Mix", "calories": 400})
        bob_foods = bob.get("/api/food/db").get_json()["custom"]
        assert all(f["name"] != "Alice Protein Mix" for f in bob_foods)
        alice_foods = alice.get("/api/food/db").get_json()["custom"]
        assert any(f["name"] == "Alice Protein Mix" for f in alice_foods)


class TestWellnessIsolation:
    def test_hydration_is_private(self, alice, bob):
        alice.post("/api/hydration", json={"amount_ml": 777, "date_key": TODAY})
        bob_day = bob.get(f"/api/hydration/{TODAY}").get_json()
        assert all(l["amount_ml"] != 777 for l in bob_day["logs"])

    def test_sleep_is_private(self, alice, bob):
        alice.post("/api/sleep", json={
            "bedtime": f"{TODAY}T23:00", "wake_time": f"{TODAY}T07:00",
            "date_key": TODAY, "quality": 4, "notes": "alice-sleep-marker"})
        bob_logs = bob.get("/api/sleep?days=2").get_json()
        assert all(l.get("notes") != "alice-sleep-marker" for l in bob_logs)

    def test_bob_cannot_delete_alices_sleep(self, alice, bob):
        r = alice.post("/api/sleep", json={
            "bedtime": f"{TODAY}T22:00", "wake_time": f"{TODAY}T06:00",
            "date_key": TODAY})
        sid = r.get_json()["log"]["id"]
        bob.delete(f"/api/sleep/{sid}")
        logs = alice.get("/api/sleep?days=2").get_json()
        assert any(l["id"] == sid for l in logs), "Bob deleted Alice's sleep log!"

    def test_thoughts_are_private(self, alice, bob):
        alice.post("/api/thoughts", json={"content": "alice private thought", "mood": "happy",
                                          "date_key": TODAY})
        bob_thoughts = bob.get(f"/api/thoughts/{TODAY}").get_json()
        assert all("alice private" not in t.get("content", "") for t in bob_thoughts)

    def test_todos_are_private_and_protected(self, alice, bob):
        r = alice.post("/api/todos", json={"title": "alice secret task"})
        tid = r.get_json()["todo"]["id"]
        bob_todos = bob.get("/api/todos").get_json()["todos"]
        assert all(t["title"] != "alice secret task" for t in bob_todos)
        # Bob tries to toggle & delete Alice's todo by id
        bob.post(f"/api/todos/{tid}/toggle")
        bob.delete(f"/api/todos/{tid}")
        alice_todos = alice.get("/api/todos").get_json()["todos"]
        mine = [t for t in alice_todos if t["id"] == tid]
        assert mine, "Bob deleted Alice's todo!"
        assert mine[0]["status"] == "pending", "Bob toggled Alice's todo!"

    def test_body_metrics_are_private(self, alice, bob):
        alice.post("/api/body-metrics", json={"date_key": TODAY, "weight_kg": 61.5})
        bob_metrics = bob.get("/api/body-metrics").get_json()
        assert all(m.get("weight_kg") != 61.5 for m in bob_metrics)


class TestHealthIsolation:
    def test_habits_are_private_and_protected(self, alice, bob):
        r = alice.post("/api/habits", json={"name": "alice-habit"})
        hid = r.get_json()["habit"]["id"]
        bob_habits = bob.get("/api/habits").get_json()["habits"]
        assert all(h["name"] != "alice-habit" for h in bob_habits)
        # Bob cannot toggle Alice's habit
        bob.post(f"/api/habits/{hid}/toggle", json={"date_key": TODAY})
        alice_habits = alice.get("/api/habits").get_json()["habits"]
        mine = [h for h in alice_habits if h["id"] == hid][0]
        assert not mine["done_today"], "Bob toggled Alice's habit!"

    def test_symptoms_are_private(self, alice, bob):
        alice.post("/api/symptoms", json={"name": "alice-headache", "severity": 6,
                                          "date_key": TODAY})
        bob_syms = bob.get("/api/symptoms").get_json()
        assert all(s["name"] != "alice-headache" for s in bob_syms)

    def test_vitals_are_private(self, alice, bob):
        alice.post("/api/vitals", json={"type": "heart_rate", "value1": 61,
                                        "date_key": TODAY, "notes": "alice-hr"})
        bob_vitals = bob.get("/api/vitals").get_json()
        assert all(v.get("notes") != "alice-hr" for v in bob_vitals)

    def test_emergency_info_is_private(self, alice, bob):
        alice.post("/api/emergency", json={"blood_type": "AB-", "allergies": "alice-allergy"})
        bob_info = bob.get("/api/emergency").get_json()
        assert bob_info.get("allergies") != "alice-allergy"


class TestMedicineIsolation:
    def test_medicines_are_private_and_protected(self, alice, bob):
        r = alice.post("/api/medicines", json={"name": "AliceStatin", "dosage": "10"})
        mid = r.get_json()["medicine"]["id"]
        bob_meds = bob.get("/api/medicines").get_json()
        assert all(m["name"] != "AliceStatin" for m in bob_meds)
        # Bob cannot log a dose against Alice's medicine or delete it
        bob.post(f"/api/medicines/{mid}/log", json={"scheduled": "08:00", "taken": True})
        bob.delete(f"/api/medicines/{mid}")
        alice_meds = alice.get("/api/medicines").get_json()
        assert any(m["id"] == mid for m in alice_meds), "Bob deleted Alice's medicine!"
        doses = alice.get("/api/medicines/today").get_json()
        taken = [d for d in doses if d["med_id"] == mid and d["taken"]]
        assert not taken, "Bob logged a dose on Alice's medicine!"


class TestFitnessIsolation:
    def test_activities_are_private_and_protected(self, alice, bob):
        r = alice.post("/api/fitness/activities", json={
            "type": "running", "name": "alice-morning-run", "date": TODAY,
            "duration": 30, "calories": 300})
        aid = r.get_json()["activity"]["id"]
        bob_acts = bob.get("/api/fitness/activities").get_json()
        assert all(a.get("name") != "alice-morning-run" for a in bob_acts)
        bob.delete(f"/api/fitness/activities/{aid}")
        alice_acts = alice.get("/api/fitness/activities").get_json()
        assert any(a["id"] == aid for a in alice_acts), "Bob deleted Alice's activity!"

    def test_fitness_stats_are_scoped(self, alice, bob):
        # Bob's stats must not include Alice's calories
        bob_stats = bob.get("/api/fitness/stats").get_json()
        alice_stats = alice.get("/api/fitness/stats").get_json()
        assert alice_stats["total"] >= 1
        # Bob logged nothing in this class — his total reflects only his own data
        assert bob_stats["total"] == 0 or bob_stats["total"] < alice_stats["total"]


class TestProfileIsolation:
    def test_profiles_are_separate(self, alice, bob):
        alice.post("/api/food/profile", json={"weight_kg": 58, "height_cm": 164,
                                              "age": 29, "gender": "female"})
        bob_profile = bob.get("/api/food/profile").get_json()["profile"]
        assert bob_profile.get("weight_kg") != 58

    def test_reminder_settings_are_separate(self, alice, bob):
        alice.post("/api/reminders/settings", json={"water_goal_ml": 1234})
        bob_settings = bob.get("/api/reminders/settings").get_json()
        assert bob_settings.get("water_goal_ml") != 1234


class TestSearchAndInsightsIsolation:
    def test_global_search_is_scoped(self, alice, bob):
        alice.post("/api/thoughts", json={"content": "xylophone secret alice",
                                          "mood": "calm", "date_key": TODAY})
        res = bob.get("/api/search?q=xylophone").get_json()
        assert res["total"] == 0, "Bob found Alice's thought via search!"

    def test_notifications_are_private(self, alice, bob):
        alice.post("/api/notifications", json={"type": "system",
                                               "title": "alice-only-notif"})
        bob_notifs = bob.get("/api/notifications").get_json()["notifications"]
        assert all(n["title"] != "alice-only-notif" for n in bob_notifs)

    def test_export_is_scoped(self, alice, bob):
        res = bob.get("/api/export?format=json&sections=thoughts").get_json()
        contents = str(res.get("thoughts", []))
        assert "alice" not in contents.lower(), "Bob's export contains Alice's data!"

    def test_export_counts_are_scoped(self, alice, bob):
        alice_counts = alice.get("/api/export/counts").get_json()
        bob_counts = bob.get("/api/export/counts").get_json()
        # Alice logged food earlier in this run; Bob logged none
        assert alice_counts["food_logs"] >= 1
        assert bob_counts["food_logs"] == 0


class TestUserContext:
    def test_background_jobs_scope_queries_per_user(self, alice, app):
        """user_context() drives current_user_id() outside a request —
        this is how the scheduler and OAuth sync stay per-user."""
        from db.core import current_user_id, user_context

        alice_id = alice.get("/auth/me").get_json()["id"]
        assert current_user_id() == "default"          # no request, no override
        with user_context(alice_id):
            assert current_user_id() == alice_id
            with user_context("someone-else"):         # nesting restores properly
                assert current_user_id() == "someone-else"
            assert current_user_id() == alice_id
        assert current_user_id() == "default"

        # Scoped read actually returns that user's rows
        from db import get_food_logs
        import datetime
        today = datetime.date.today().isoformat()
        with user_context(alice_id):
            names = {l["food_name"] for l in get_food_logs(today)}
        assert "Alice Secret Salad" in names

    def test_sync_history_is_per_user(self, alice, bob, app):
        """Fitness sync history must not leak between users."""
        from db.core import user_context
        from db import log_sync, get_sync_history

        alice_id = alice.get("/auth/me").get_json()["id"]
        bob_id = bob.get("/auth/me").get_json()["id"]
        with user_context(alice_id):
            log_sync("strava", "success", 7, "alice-sync-marker")
        with user_context(bob_id):
            bob_hist = get_sync_history()
        assert all(h.get("message") != "alice-sync-marker" for h in bob_hist), \
            "Bob can see Alice's fitness sync history"
        with user_context(alice_id):
            alice_hist = get_sync_history()
        assert any(h.get("message") == "alice-sync-marker" for h in alice_hist)
