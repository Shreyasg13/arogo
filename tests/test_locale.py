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


# ── units of measurement ────────────────────────────────────────────────────

def test_units_default_by_country(app):
    from db.locale_config import units_of
    _, uid = _client_uid(app, "loc4@medeasy.test")
    with user_context(uid):
        u = units_of()                               # India default
        assert u == {"weight": "kg", "height": "cm", "temp": "c", "glucose": "mgdl"}
        update_profile({"country": "US"})
        u = units_of()                               # US → imperial + mg/dL
        assert u["weight"] == "lb" and u["height"] == "ft" and u["temp"] == "f"
        assert u["glucose"] == "mgdl"
        update_profile({"country": "GB"})
        u = units_of()                               # UK → stone-free kg, ft, °C, mmol
        assert u["weight"] == "kg" and u["height"] == "ft"
        assert u["temp"] == "c" and u["glucose"] == "mmol"


def test_explicit_unit_overrides_country(app):
    from db.locale_config import units_of
    _, uid = _client_uid(app, "loc5@medeasy.test")
    with user_context(uid):
        update_profile({"country": "US"})            # defaults to lb
        update_profile({"weight_unit": "kg"})        # user overrides
        assert units_of()["weight"] == "kg"
        assert units_of()["temp"] == "f"             # others still follow the country
        update_profile({"weight_unit": "nonsense"})  # garbage ignored
        assert units_of()["weight"] == "kg"


def test_emergency_numbers_by_country(app):
    from db.locale_config import emergency_numbers
    _, uid = _client_uid(app, "loc7@medeasy.test")
    with user_context(uid):
        e = emergency_numbers()                      # India default
        nums = {x["number"] for x in e["numbers"]}
        assert "108" in nums and e["listed"] is True
        update_profile({"country": "US"})
        e = emergency_numbers()
        assert [x["number"] for x in e["numbers"]] == ["911"]
        update_profile({"country": "GB"})
        assert "999" in {x["number"] for x in emergency_numbers()["numbers"]}


def test_every_emergency_entry_is_well_formed():
    """Every listed number must have a specific service label and digits only.
    A number labelled as something it isn't sends someone to the wrong service."""
    from db.locale_config import EMERGENCY_NUMBERS
    for code, rows in EMERGENCY_NUMBERS.items():
        assert rows, f"{code} has an empty list"
        seen_labels = set()
        for label, number in rows:
            assert label and label.strip(), f"{code}: empty label"
            assert number.isdigit(), f"{code}: non-numeric {number!r}"
            assert label not in seen_labels, f"{code}: duplicate label {label!r} is ambiguous on an ICE card"
            seen_labels.add(label)


def test_sri_lanka_119_is_labelled_police():
    """119 in Sri Lanka is the police line, not a general emergency number."""
    from db.locale_config import EMERGENCY_NUMBERS
    lk = dict((n, l) for l, n in EMERGENCY_NUMBERS['LK'])
    assert lk['119'] == 'Police'
    assert lk['1990'].startswith('Ambulance')


def test_emergency_fallback_is_flagged_unlisted():
    from db.locale_config import emergency_numbers
    e = emergency_numbers("OT")                      # "Other" has no listed numbers
    assert e["listed"] is False                      # UI must tell the user to check locally
    assert e["numbers"][0]["number"] == "112"


def test_emergency_numbers_on_health_id(app):
    from db.health_id import get_health_id
    _, uid = _client_uid(app, "loc8@medeasy.test")
    with user_context(uid):
        card = get_health_id()
    assert "emergency_numbers" in card
    assert any(n["number"] == "108" for n in card["emergency_numbers"]["numbers"])


def test_units_in_locale_route(app):
    c, _ = _client_uid(app, "loc6@medeasy.test")
    u = c.get("/api/locale").get_json()["units"]
    assert set(u) == {"weight", "height", "temp", "glucose"}
    assert u["weight"] == "kg"                       # India default
