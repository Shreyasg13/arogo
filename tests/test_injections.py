"""J1 — injection-site rotation tracker. Log injections at fixed body sites; the
app suggests the least-recently-used site next. From the user's own log; the
suggestion is a plain LRU pick, no clinical claim."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.injections import log_injection, get_injection_state, INJECTION_SITES

PW = "inj-pw-123456"


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


def test_empty_suggests_a_valid_site(app):
    _, uid = _uid(app, "inj1@medeasy.test")
    with user_context(uid):
        d = get_injection_state()
    assert d["has_data"] is False
    assert d["suggested_next"] in INJECTION_SITES     # some site, even with no history


def test_invalid_site_rejected(app):
    _, uid = _uid(app, "inj2@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            log_injection({"site": "left-eyebrow"})


def test_suggestion_avoids_the_most_recently_used(app):
    _, uid = _uid(app, "inj3@medeasy.test")
    today = dt.date.today().isoformat()
    with user_context(uid):
        # Use every site except thigh_left; thigh_left (never used) should be next.
        for s in INJECTION_SITES:
            if s != "thigh_left":
                log_injection({"site": s, "date_key": today})
        d = get_injection_state()
    assert d["suggested_next"] == "thigh_left"        # the one never used
    assert d["has_data"] is True
    assert d["total"] == len(INJECTION_SITES) - 1


def test_never_used_beats_a_used_site(app):
    _, uid = _uid(app, "inj4@medeasy.test")
    old = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    with user_context(uid):
        log_injection({"site": "arm_left", "date_key": old})   # only one site used
        d = get_injection_state()
    # A never-used site is fresher than arm_left → suggestion isn't arm_left.
    assert d["suggested_next"] != "arm_left"


def test_all_used_picks_the_oldest(app):
    _, uid = _uid(app, "inj5@medeasy.test")
    with user_context(uid):
        # Every site used exactly once, spread across days — INJECTION_SITES[0]
        # gets the oldest date, so it's the least-recently-used pick.
        for i, s in enumerate(INJECTION_SITES):
            day = (dt.date.today() - dt.timedelta(days=len(INJECTION_SITES) - i)).isoformat()
            log_injection({"site": s, "date_key": day})
        d = get_injection_state()
    assert d["suggested_next"] == INJECTION_SITES[0]   # oldest last-use


def test_api_roundtrip(app):
    c, uid = _uid(app, "inj6@medeasy.test")
    r = c.post("/api/injections", json={"site": "thigh_right"})
    assert r.get_json()["success"] is True
    state = c.get("/api/injections").get_json()
    assert state["has_data"] is True
    iid = state["recent"][0]["id"]
    assert c.delete("/api/injections/" + iid).status_code == 200
    assert c.get("/api/injections").get_json()["has_data"] is False
