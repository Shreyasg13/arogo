"""
tests/test_barcode.py — Food barcode scanning + saved-scan quick reference.

Open Food Facts is never hit for real: food_barcode.lookup_barcode is
monkeypatched. Covers the saved-first lookup, the OFF path, manual
save, re-scan dedupe, and per-user isolation of scanned foods.

Run:  pytest tests/test_barcode.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
import auth as auth_module
import food_barcode
from db.core import init_db
from app import create_app

PW = "barcode-pw-12345"
BARCODE = "8901058000108"

OFF_PRODUCT = {
    "barcode": BARCODE, "name": "Maggi Noodles", "serving_g": 100,
    "calories": 402, "protein": 9.2, "carbs": 60.5, "fat": 14.4,
    "fiber": 2.1, "sugar": 3.0, "sodium": 850.0, "source": "openfoodfacts",
}


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
    """No real network — return a fixed product for our test barcode."""
    monkeypatch.setattr(food_barcode, "lookup_barcode",
                        lambda code: dict(OFF_PRODUCT) if code == BARCODE else None)


def _user(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201)
    return c


class TestBarcodeValidation:
    def test_valid_barcode_shapes(self):
        assert food_barcode.valid_barcode("8901058000108")
        assert food_barcode.valid_barcode("01234567")
        assert not food_barcode.valid_barcode("123")
        assert not food_barcode.valid_barcode("abcd12345678")
        assert not food_barcode.valid_barcode("")


class TestBarcodeLookup:
    def test_invalid_barcode_rejected(self, app):
        c = _user(app, "bc-a@medeasy.test")
        assert c.get("/api/food/barcode/123").status_code == 400

    def test_unknown_barcode_404(self, app):
        c = _user(app, "bc-a@medeasy.test")
        r = c.get("/api/food/barcode/00000000")
        assert r.status_code == 404 and r.get_json()["found"] is False

    def test_off_lookup_then_save_then_instant_rescan(self, app):
        c = _user(app, "bc-scan@medeasy.test")

        # 1. First scan → comes from Open Food Facts
        r = c.get(f"/api/food/barcode/{BARCODE}")
        assert r.status_code == 200
        d = r.get_json()
        assert d["found"] and d["food"]["source"] == "openfoodfacts"
        assert d["food"]["name"] == "Maggi Noodles"

        # 2. User saves it (barcode carried through)
        food = d["food"]
        r = c.post("/api/food/custom", json={**food, "category": "Scanned"})
        assert r.status_code == 200 and r.get_json()["success"]

        # 3. Re-scan → now served instantly from the user's saved foods
        r = c.get(f"/api/food/barcode/{BARCODE}")
        d = r.get_json()
        assert d["found"] and d["food"]["source"] == "saved"
        assert d["food"]["sodium"] == 850.0     # label data preserved

    def test_rescan_save_dedupes(self, app):
        c = _user(app, "bc-dedupe@medeasy.test")
        base = {"name": "ColaX", "barcode": "1112223334445", "calories": 42,
                "sugar": 10.6, "category": "Scanned"}
        c.post("/api/food/custom", json=base)
        c.post("/api/food/custom", json={**base, "name": "ColaX Zero", "sugar": 0})
        # Same barcode → one row, updated in place
        foods = [f for f in c.get("/api/food/db").get_json()["custom"]
                 if f.get("barcode") == "1112223334445"]
        assert len(foods) == 1
        assert foods[0]["name"] == "ColaX Zero" and foods[0]["sugar"] == 0


class TestBarcodeIsolation:
    def test_scanned_food_is_private(self, app):
        alice = _user(app, "bc-alice@medeasy.test")
        bob = _user(app, "bc-bob@medeasy.test")
        alice.post("/api/food/custom", json={
            "name": "Alice Secret Bar", "barcode": BARCODE, "calories": 200,
            "category": "Scanned"})
        # Bob scanning the same barcode must NOT get Alice's saved entry;
        # he falls through to Open Food Facts instead
        r = bob.get(f"/api/food/barcode/{BARCODE}")
        assert r.get_json()["food"]["source"] == "openfoodfacts"
        assert all(f["name"] != "Alice Secret Bar"
                   for f in bob.get("/api/food/db").get_json()["custom"])

    def test_requires_auth(self, app):
        assert app.test_client().get(f"/api/food/barcode/{BARCODE}").status_code == 401
