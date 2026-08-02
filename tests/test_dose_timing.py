"""Per-dose timing instructions (before food / bedtime / with water …)."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute

PW = "timing-pw-1234"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "timing@medeasy.test", "password": PW})
    return c


def test_timing_is_stored_and_labelled(client):
    m = client.post("/api/medicines", json={
        "name": "Levothyroxine", "frequency": "once_daily", "times": ["07:00"],
        "timing": "empty_stomach"}).get_json()["medicine"]
    assert m["timing"] == "empty_stomach"
    assert m["timing_text"] == "on an empty stomach"
    # today's dose carries the label so the schedule can show it
    dose = next(d for d in client.get("/api/medicines/today").get_json()
                if d["med_id"] == m["id"])
    assert dose["timing_text"] == "on an empty stomach"


def test_with_food_timing_keeps_legacy_flag_in_step(client):
    m = client.post("/api/medicines", json={
        "name": "Ibuprofen", "frequency": "once_daily", "times": ["09:00"],
        "timing": "with_food"}).get_json()["medicine"]
    assert m["timing"] == "with_food" and m["with_food"] is True


def test_bare_with_food_flag_still_sets_timing(client):
    # An older client that sends only with_food (no `timing`) still gets a label.
    m = client.post("/api/medicines", json={
        "name": "Aspirin", "frequency": "once_daily", "times": ["09:00"],
        "with_food": True}).get_json()["medicine"]
    assert m["timing"] == "with_food" and m["timing_text"] == "with food"


def test_unknown_timing_is_rejected_to_blank(client):
    m = client.post("/api/medicines", json={
        "name": "Weird", "frequency": "once_daily", "times": ["09:00"],
        "timing": "at_the_full_moon"}).get_json()["medicine"]
    assert m["timing"] == "" and m["timing_text"] == "" and m["with_food"] is False


def test_card_shows_timing_label(client):
    client.post("/api/medicines", json={
        "name": "Melatonin", "frequency": "once_daily", "times": ["22:00"],
        "timing": "bedtime"})
    card = client.get("/api/medicines/card").get_json()
    mel = next(m for s in card["schedule"] for m in s["meds"] if m["name"] == "Melatonin")
    assert mel["timing_text"] == "at bedtime"


def test_backfill_query_sets_timing_from_with_food_flag(app):
    """The migration's backfill (run once, when the column is first added) maps a
    legacy with_food=1 / blank-timing row to timing='with_food'."""
    c = app.test_client()
    c.post("/auth/register", json={"email": "timing2@medeasy.test", "password": PW})
    m = c.post("/api/medicines", json={
        "name": "Legacy", "frequency": "once_daily", "times": ["09:00"],
        "timing": "with_food"}).get_json()["medicine"]
    # Simulate a pre-migration row: flag set, timing blank.
    execute("UPDATE medicines SET timing='' WHERE id=?", (m["id"],), commit=True)
    # This is exactly the statement migrate_add_dose_timing() runs on column-add.
    execute("UPDATE medicines SET timing='with_food' "
            "WHERE with_food=1 AND (timing IS NULL OR timing='')", commit=True)
    got = c.get("/api/medicines").get_json()
    row = next(x for x in got if x["id"] == m["id"])
    assert row["timing"] == "with_food" and row["timing_text"] == "with food"
