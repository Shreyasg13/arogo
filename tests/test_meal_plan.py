"""Meal planner + grocery list — plan items to days/meals, roll up into a
shopping list, per-user isolation."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.meal_plan import add_planned, delete_planned, get_plan, get_grocery

PW = "meal-pw-12345"


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


def _ahead(n):
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def test_add_and_grid(app):
    _, uid = _uid(app, "meal1@medeasy.test")
    with user_context(uid):
        add_planned({"date": _ahead(0), "meal_type": "dinner", "item": "Dal", "quantity": 200, "unit": "g"})
        add_planned({"date": _ahead(1), "meal_type": "breakfast", "item": "Poha"})
        plan = get_plan(days=7)
    assert len(plan["days"]) == 7
    day0 = plan["days"][0]
    assert day0["meals"]["dinner"][0]["item"] == "Dal"
    assert plan["days"][1]["meals"]["breakfast"][0]["item"] == "Poha"


def test_item_required(app):
    _, uid = _uid(app, "meal2@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            add_planned({"date": _ahead(0), "item": "  "})


def test_bad_meal_type_defaults_lunch(app):
    _, uid = _uid(app, "meal3@medeasy.test")
    with user_context(uid):
        it = add_planned({"date": _ahead(0), "meal_type": "brunch", "item": "Idli"})
    assert it["meal_type"] == "lunch"


def test_grocery_sums_same_item(app):
    _, uid = _uid(app, "meal4@medeasy.test")
    with user_context(uid):
        add_planned({"date": _ahead(0), "meal_type": "lunch", "item": "Toor dal", "quantity": 100, "unit": "g"})
        add_planned({"date": _ahead(2), "meal_type": "dinner", "item": "toor dal", "quantity": 150, "unit": "g"})
        add_planned({"date": _ahead(1), "meal_type": "breakfast", "item": "Roti", "quantity": 2, "unit": ""})
        g = get_grocery(days=7)
    dal = next(i for i in g["items"] if i["item"].lower() == "toor dal")
    assert dal["quantity"] == 250 and dal["unit"] == "g" and dal["count"] == 2
    roti = next(i for i in g["items"] if i["item"] == "Roti")
    assert roti["quantity"] == 2 and roti["count"] == 1


def test_grocery_unquantified_counts(app):
    _, uid = _uid(app, "meal5@medeasy.test")
    with user_context(uid):
        add_planned({"date": _ahead(0), "meal_type": "snack", "item": "Apple"})
        add_planned({"date": _ahead(3), "meal_type": "snack", "item": "apple"})
        g = get_grocery(days=7)
    apple = next(i for i in g["items"] if i["item"].lower() == "apple")
    assert apple["quantity"] is None and apple["count"] == 2


def test_grocery_mixed_quantified_surfaces_extra(app):
    # "Rice 500g" + a bare "Rice" must not hide the second occurrence.
    _, uid = _uid(app, "meal11@medeasy.test")
    with user_context(uid):
        add_planned({"date": _ahead(0), "meal_type": "lunch", "item": "Rice", "quantity": 500, "unit": "g"})
        add_planned({"date": _ahead(1), "meal_type": "dinner", "item": "rice", "unit": "g"})
        g = get_grocery(days=7)
    rice = next(i for i in g["items"] if i["item"].lower() == "rice")
    assert rice["quantity"] == 500 and rice["count"] == 2 and rice["extra"] == 1


def test_window_excludes_outside(app):
    _, uid = _uid(app, "meal6@medeasy.test")
    with user_context(uid):
        add_planned({"date": _ahead(1), "meal_type": "lunch", "item": "InWindow"})
        add_planned({"date": _ahead(20), "meal_type": "lunch", "item": "OutOfWindow"})
        g = get_grocery(days=7)
    names = [i["item"] for i in g["items"]]
    assert "InWindow" in names and "OutOfWindow" not in names


def test_delete(app):
    _, uid = _uid(app, "meal7@medeasy.test")
    with user_context(uid):
        it = add_planned({"date": _ahead(0), "meal_type": "lunch", "item": "Temp"})
        delete_planned(it["id"])
        assert get_grocery(days=7)["items"] == []


def test_isolation(app):
    _, uid_a = _uid(app, "meal8@medeasy.test")
    _, uid_b = _uid(app, "meal9@medeasy.test")
    with user_context(uid_a):
        add_planned({"date": _ahead(0), "meal_type": "lunch", "item": "SecretMeal"})
    with user_context(uid_b):
        assert get_grocery(days=7)["items"] == []


def test_api_round_trip(app):
    c, uid = _uid(app, "meal10@medeasy.test")
    r = c.post("/api/meal-plan", json={"date": _ahead(0), "meal_type": "dinner", "item": "Khichdi", "quantity": 300, "unit": "g"})
    assert r.status_code == 200
    pid = r.get_json()["item"]["id"]
    assert c.get("/api/meal-plan/grocery").get_json()["items"][0]["item"] == "Khichdi"
    assert c.delete(f"/api/meal-plan/{pid}").get_json()["success"] is True
    assert c.post("/api/meal-plan", json={"item": ""}).status_code == 400
