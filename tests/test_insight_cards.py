"""
tests/test_insight_cards.py — Rules-based dashboard insights.

Core contract: rules stay silent until there is enough real data,
so a fresh account gets an empty list rather than hollow cards.

Run:  pytest tests/test_insight_cards.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import datetime
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
import auth as auth_module
from db.core import init_db
from app import create_app

PW = "insight-pw-12345"


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


def _user(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201)
    return c


class TestInsightCards:
    def test_fresh_account_gets_no_cards(self, app):
        c = _user(app, "insight-empty@medeasy.test")
        r = c.get("/api/insights/cards")
        assert r.status_code == 200
        assert r.get_json()["cards"] == []

    def test_dose_adherence_card(self, app):
        c = _user(app, "insight-doses@medeasy.test")
        today = datetime.date.today()
        r = c.post("/api/medicines", json={"name": "InsightPill", "dosage": "5",
                                           "times": ["08:00"]})
        mid = r.get_json()["medicine"]["id"]
        # 6 taken doses across the last 6 days → ≥90% adherence
        for i in range(6):
            d = (today - datetime.timedelta(days=i)).isoformat()
            c.post(f"/api/medicines/{mid}/log",
                   json={"date": d, "time": "08:00", "taken": True})
        cards = c.get("/api/insights/cards").get_json()["cards"]
        assert any("adherence" in x["text"] for x in cards), cards

    def test_water_streak_card(self, app):
        c = _user(app, "insight-water@medeasy.test")
        today = datetime.date.today()
        # 4 consecutive days at 2500ml ≥ default 2450 goal
        for i in range(4):
            d = (today - datetime.timedelta(days=i)).isoformat()
            c.post("/api/hydration", json={"amount_ml": 2500, "date_key": d})
        cards = c.get("/api/insights/cards").get_json()["cards"]
        assert any("water goal" in x["text"] for x in cards), cards

    def test_requires_auth(self, app):
        assert app.test_client().get("/api/insights/cards").status_code == 401
