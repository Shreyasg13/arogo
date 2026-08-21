"""Per-user country → currency + financial year (no longer hard-coded to India)."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.locale_config import (country_of, currency_of, country_info, country_list,
                              valid_country, DEFAULT_COUNTRY)
from db.food import update_profile, get_profile

PW = "loc-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _client_uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def test_valid_country_and_default():
    assert valid_country("us") == "US" and valid_country("IN") == "IN"
    assert valid_country("zz") is None
    assert DEFAULT_COUNTRY == "IN"


def test_currency_mapping():
    assert currency_of("US") == {"code": "USD", "symbol": "$", "locale": "en-US"}
    assert currency_of("GB")["symbol"] == "£"
    assert currency_of("DE")["code"] == "EUR"


def test_default_is_india_then_follows_profile(app):
    _, uid = _client_uid(app, "loc1@medeasy.test")
    with user_context(uid):
        assert country_of() == "IN"                 # unchanged for existing users
        assert currency_of()["symbol"] == "₹"
        update_profile({"country": "AU"})
        assert country_of() == "AU"
        assert currency_of()["symbol"] == "$" and currency_of()["code"] == "AUD"
        assert country_info()["fy_start_month"] == 7   # Australia: Jul–Jun
        # garbage country is ignored, keeps the last good one
        update_profile({"country": "zzz"})
        assert country_of() == "AU"


def test_profile_persists_country(app):
    c, _ = _client_uid(app, "loc2@medeasy.test")
    c.post("/api/food/profile", json={"country": "GB"})
    assert c.get("/api/food/profile").get_json()["profile"]["country"] == "GB"


def test_locale_route(app):
    c, _ = _client_uid(app, "loc3@medeasy.test")
    body = c.get("/api/locale").get_json()
    assert body["country"] == "IN" and body["currency"]["symbol"] == "₹"
    codes = {x["code"] for x in body["countries"]}
    assert {"IN", "US", "GB", "OT"} <= codes


def test_locale_requires_auth(app):
    assert app.test_client().get("/api/locale").status_code in (401, 403)


def test_country_list_sorted_with_other_last():
    lst = country_list()
    assert lst[-1]["code"] == "OT"                  # "Other" sinks to the bottom
