"""Idempotent writes — a replayed offline log must not duplicate a health record.

The offline outbox replays queued POSTs when connectivity returns. These tables
are append-only blind INSERTs, so without a key a replay would silently create a
second reading / drink / meal and quietly corrupt totals and averages.
"""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today, clean_idem_key
from db.health import log_vital, log_symptom
from db.wellness import log_hydration, log_body_metric, save_thought
from db.food import log_food

PW = "idem-pw-12345"


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


def _count(table, uid):
    return dict(execute(f"SELECT COUNT(*) c FROM {table} WHERE user_id=?", (uid,), fetchone=True))["c"]


def test_key_validation():
    assert clean_idem_key("abc-123_XY") == "abc-123_XY"
    assert clean_idem_key("") is None
    assert clean_idem_key(None) is None
    assert clean_idem_key("x" * 65) is None            # bounded
    assert clean_idem_key("bad key!") is None          # charset-limited
    assert clean_idem_key("'; DROP TABLE vitals--") is None


def test_vital_replay_does_not_duplicate(app):
    _, uid = _uid(app, "idem1@medeasy.test")
    payload = {"type": "blood_sugar", "value1": 110, "unit": "mg/dL",
               "date_key": user_today(), "idem_key": "k-vital-1"}
    with user_context(uid):
        log_vital(dict(payload))
        log_vital(dict(payload))          # the replay
        log_vital(dict(payload))          # and again
        n = _count("vitals", uid)
    assert n == 1


def test_hydration_replay_does_not_double_count(app):
    _, uid = _uid(app, "idem2@medeasy.test")
    with user_context(uid):
        log_hydration(250, "water", user_today(), idem_key="k-water-1")
        log_hydration(250, "water", user_today(), idem_key="k-water-1")
        total = dict(execute("SELECT SUM(amount_ml) s FROM hydration_logs WHERE user_id=?",
                             (uid,), fetchone=True))["s"]
    assert total == 250                    # not 500


def test_symptom_and_body_and_food_replays(app):
    _, uid = _uid(app, "idem3@medeasy.test")
    with user_context(uid):
        for _ in range(2):
            log_symptom({"name": "Headache", "severity": 4,
                         "date_key": user_today(), "idem_key": "k-sym-1"})
            log_body_metric({"weight_kg": 70, "date_key": user_today(), "idem_key": "k-body-1"})
            log_food({"food_name": "Dal", "calories": 180,
                      "date_key": user_today(), "idem_key": "k-food-1"})
        assert _count("symptoms", uid) == 1
        assert _count("body_metrics", uid) == 1
        assert _count("food_logs", uid) == 1


def test_beverage_hydration_credit_is_not_double_counted(app):
    """log_food auto-credits hydration for a drink — a replay must not credit
    it twice (one replay would otherwise corrupt TWO tables)."""
    _, uid = _uid(app, "idem4@medeasy.test")
    with user_context(uid):
        payload = {"food_id": "water", "food_name": "Water", "quantity_g": 250,
                   "date_key": user_today(), "idem_key": "k-drink-1"}
        log_food(dict(payload))
        before = dict(execute("SELECT COUNT(*) c FROM hydration_logs WHERE user_id=?",
                              (uid,), fetchone=True))["c"]
        log_food(dict(payload))            # replay
        after = dict(execute("SELECT COUNT(*) c FROM hydration_logs WHERE user_id=?",
                             (uid,), fetchone=True))["c"]
    assert after == before                  # no extra hydration credit


def test_distinct_keys_still_create_separate_rows(app):
    """Two genuinely different actions must both be recorded — dedupe must not
    swallow a real second reading."""
    _, uid = _uid(app, "idem5@medeasy.test")
    with user_context(uid):
        log_vital({"type": "heart_rate", "value1": 70, "date_key": user_today(), "idem_key": "a1"})
        log_vital({"type": "heart_rate", "value1": 78, "date_key": user_today(), "idem_key": "a2"})
        assert _count("vitals", uid) == 2


def test_no_key_behaves_exactly_as_before(app):
    """Clients that don't send a key keep the old append-only behaviour."""
    _, uid = _uid(app, "idem6@medeasy.test")
    with user_context(uid):
        log_vital({"type": "heart_rate", "value1": 70, "date_key": user_today()})
        log_vital({"type": "heart_rate", "value1": 70, "date_key": user_today()})
        assert _count("vitals", uid) == 2


def test_keys_are_scoped_per_user(app):
    """The same key from two users must not collide."""
    _, a = _uid(app, "idem7a@medeasy.test")
    _, b = _uid(app, "idem7b@medeasy.test")
    with user_context(a):
        log_vital({"type": "spo2", "value1": 98, "date_key": user_today(), "idem_key": "shared"})
    with user_context(b):
        log_vital({"type": "spo2", "value1": 96, "date_key": user_today(), "idem_key": "shared"})
        assert _count("vitals", b) == 1
    with user_context(a):
        assert _count("vitals", a) == 1


def test_thought_replay_does_not_duplicate_the_users_words(app):
    """A mood check-in tapped from a notification while offline is queued in the
    service worker and replayed. Without a key the user would find their own
    sentence written twice in the journal."""
    _, uid = _uid(app, "idem9@medeasy.test")
    with user_context(uid):
        a = save_thought("Check-in: feeling good.", "happy", user_today(), idem_key="k-mood-1")
        b = save_thought("Check-in: feeling good.", "happy", user_today(), idem_key="k-mood-1")
        assert _count("thoughts", uid) == 1
        assert a["id"] == b["id"]          # the replay returns the entry already written


def test_thought_distinct_keys_and_no_key(app):
    """Two genuine check-ins must both land; a client with no key keeps the old
    append-only behaviour."""
    _, uid = _uid(app, "idem10@medeasy.test")
    with user_context(uid):
        save_thought("Rough morning.", "sad", user_today(), idem_key="m1")
        save_thought("Better now.", "happy", user_today(), idem_key="m2")
        save_thought("No key here.", "neutral", user_today())
        save_thought("No key here.", "neutral", user_today())
        assert _count("thoughts", uid) == 4


def test_thought_route_passes_key_through(app):
    c, uid = _uid(app, "idem11@medeasy.test")
    body = {"content": "Check-in: feeling okay.", "mood": "neutral", "idem_key": "route-mood"}
    assert c.post("/api/thoughts", json=body).status_code == 200
    assert c.post("/api/thoughts", json=body).status_code == 200      # the replay
    with user_context(uid):
        assert _count("thoughts", uid) == 1


def test_thought_keys_are_scoped_per_user(app):
    _, a = _uid(app, "idem12a@medeasy.test")
    _, b = _uid(app, "idem12b@medeasy.test")
    with user_context(a):
        save_thought("Mine.", "neutral", user_today(), idem_key="shared-mood")
    with user_context(b):
        save_thought("Also mine.", "neutral", user_today(), idem_key="shared-mood")
        assert _count("thoughts", b) == 1
        assert dict(execute("SELECT content FROM thoughts WHERE user_id=?", (b,),
                            fetchone=True))["content"] == "Also mine."


def test_dose_log_is_replay_safe_without_a_key(app):
    """The service worker queues dose taps too. log_dose upserts on
    (medicine, date, time) and guards stock on the state transition, so a replay
    is already safe — this pins that, since the SW relies on it."""
    from db.medicines import insert_medicine, log_dose, update_medicine_stock
    _, uid = _uid(app, "idem13@medeasy.test")
    with user_context(uid):
        m = insert_medicine({"name": "Metformin", "dosage": "500mg",
                             "frequency": "once_daily", "times": ["08:00"]})
        update_medicine_stock(m["id"], 10, pills_per_dose=1)
        for _ in range(3):
            log_dose(m["id"], user_today(), "08:00", taken=True)
        assert _count("dose_logs", uid) == 1
        left = dict(execute("SELECT pill_count p FROM medicines WHERE id=?",
                            (m["id"],), fetchone=True))["p"]
    assert left == 9, "a replayed dose must not consume a second pill"


def test_route_passes_key_through(app):
    c, uid = _uid(app, "idem8@medeasy.test")
    body = {"amount_ml": 300, "drink_type": "water", "idem_key": "route-k1"}
    c.post("/api/hydration", json=body)
    c.post("/api/hydration", json=body)          # replay
    with user_context(uid):
        total = dict(execute("SELECT SUM(amount_ml) s FROM hydration_logs WHERE user_id=?",
                             (uid,), fetchone=True))["s"]
    assert total == 300
