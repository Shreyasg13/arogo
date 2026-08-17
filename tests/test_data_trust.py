"""Data-trust signals — honest freshness + thin-data caveats.

The layer must (a) only surface trackers the user has actually used, (b) report
recency as neutral fact (no cadence expectations), (c) flag thin samples, and
(d) stay strictly per-user.
"""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db.data_trust import get_data_trust, get_data_freshness, get_confidence_notes

PW = "trust-pw-12345"


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


def _days_ago(n):
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=n)).isoformat()


def _vital(uid, date_key, vtype="blood_pressure", v1=120):
    execute("INSERT INTO vitals (id, date_key, type, value1, logged_at, user_id) "
            "VALUES (?,?,?,?,?,?)", (new_id(), date_key, vtype, v1, now_iso(), uid), commit=True)


def _weight(uid, date_key, kg=70):
    execute("INSERT INTO body_metrics (id, date_key, weight_kg, created_at, user_id) "
            "VALUES (?,?,?,?,?)", (new_id(), date_key, kg, now_iso(), uid), commit=True)


# ── freshness only surfaces used trackers ───────────────────────────────────

def test_empty_when_nothing(app):
    _, uid = _uid(app, "trust1@medeasy.test")
    with user_context(uid):
        d = get_data_trust()
    assert d["freshness"] == []
    assert d["summary"] == {"tracked": 0, "stale": 0, "thin": 0}


def test_only_used_trackers_appear(app):
    _, uid = _uid(app, "trust2@medeasy.test")
    _vital(uid, _days_ago(1))
    with user_context(uid):
        fresh = get_data_freshness()
    keys = {r["key"] for r in fresh}
    assert keys == {"vitals"}          # weight/food/etc never used → absent, not nagged


# ── recency band is neutral fact ────────────────────────────────────────────

def test_recent_entry_is_recent_and_thin(app):
    _, uid = _uid(app, "trust3@medeasy.test")
    _vital(uid, _days_ago(2))
    with user_context(uid):
        r = get_data_freshness()[0]
    assert r["status"] == "recent"
    assert r["days_since"] == 2
    assert r["total"] == 1 and r["thin"] is True       # one point → no trend yet


def test_old_entry_is_stale(app):
    _, uid = _uid(app, "trust4@medeasy.test")
    _vital(uid, _days_ago(40))
    with user_context(uid):
        r = get_data_freshness()[0]
    assert r["status"] == "stale"
    assert r["days_since"] == 40
    assert r["count_30d"] == 0                          # nothing inside the 30-day window


def test_count_30d_and_not_thin(app):
    _, uid = _uid(app, "trust5@medeasy.test")
    for n in (1, 5, 20, 45):                            # 3 inside 30d, 1 outside
        _weight(uid, _days_ago(n))
    with user_context(uid):
        r = next(x for x in get_data_freshness() if x["key"] == "weight")
    assert r["count_30d"] == 3
    assert r["total"] == 4 and r["thin"] is False
    assert r["last_date"] == _days_ago(1)               # newest


# ── ordering: stalest first ─────────────────────────────────────────────────

def test_stalest_first(app):
    _, uid = _uid(app, "trust6@medeasy.test")
    _vital(uid, _days_ago(50))                          # stale
    _weight(uid, _days_ago(1))                          # recent
    with user_context(uid):
        fresh = get_data_freshness()
    assert [r["key"] for r in fresh] == ["vitals", "weight"]
    assert fresh[0]["status"] == "stale" and fresh[1]["status"] == "recent"


# ── strict per-user isolation ───────────────────────────────────────────────

def test_isolation(app):
    _, a = _uid(app, "trust7a@medeasy.test")
    _, b = _uid(app, "trust7b@medeasy.test")
    _vital(a, _days_ago(1))
    _vital(a, _days_ago(2))
    _vital(b, _days_ago(3))
    with user_context(a):
        r = next(x for x in get_data_freshness() if x["key"] == "vitals")
    assert r["total"] == 2                              # only A's two rows, never B's


# ── confidence notes ────────────────────────────────────────────────────────

def test_no_notes_without_meds(app):
    _, uid = _uid(app, "trust8@medeasy.test")
    _vital(uid, _days_ago(1))
    with user_context(uid):
        assert get_confidence_notes() == []            # no scheduled doses → no adherence caveat


def test_endpoint_requires_auth(app):
    c = app.test_client()
    r = c.get("/api/data-trust")
    assert r.status_code in (401, 403)
