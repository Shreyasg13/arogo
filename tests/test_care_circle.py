"""Care-circle command center — composes caregiver views, consent-gated."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.care_circle import get_care_circle, _summary_line

PW = "circle-pw-12345"


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


def _group(owner):
    gid = new_id()
    execute("INSERT INTO family_groups (id,name,owner_id,created_at) VALUES (?,?,?,?)",
            (gid, "Fam", owner, now_iso()), commit=True)
    return gid


def _member(gid, uid, share_meds=1, share_sleep=0):
    execute("""INSERT INTO family_members (id,group_id,user_id,role,share_medicines,share_sleep,joined_at)
               VALUES (?,?,?,?,?,?,?)""",
            (new_id(), gid, uid, "member", share_meds, share_sleep, now_iso()), commit=True)


# ── the summary sentence (pure) ──────────────────────────────────────────────

def test_summary_line_is_factual_and_reassuring():
    e = {'name': 'Mum',
         'today': {'taken': 2, 'total': 3, 'overdue': [{'med_name': 'X'}], 'low_stock': []},
         'week': {'adherence_pct': 85, 'sleep_avg': 7.2}}
    s = _summary_line(e)
    assert "Mum has taken 2 of 3 doses today." in s
    assert "1 is overdue." in s
    assert "85% of doses taken" in s
    # no medical advice / verdict
    assert not any(w in s.lower() for w in ("should", "must", "dangerous", "worrying", "bad"))


def test_summary_line_all_clear():
    e = {'name': 'Dad', 'today': {'taken': 2, 'total': 2, 'overdue': [], 'low_stock': []},
         'week': {'adherence_pct': 100}}
    s = _summary_line(e)
    assert "Nothing needs attention right now." in s


# ── the board ────────────────────────────────────────────────────────────────

def test_empty_when_not_a_caregiver(app):
    _, uid = _uid(app, "circle1@medeasy.test")
    with user_context(uid):
        d = get_care_circle()
    assert d["members"] == [] and d["count"] == 0 and d["needs_attention"] == 0


def test_lists_members_sharing_medicines(app):
    c, caregiver = _uid(app, "circle2c@medeasy.test")
    _, mem_share = _uid(app, "circle2m@medeasy.test")
    _, mem_noshare = _uid(app, "circle2n@medeasy.test")
    gid = _group(caregiver)
    _member(gid, caregiver, share_meds=0)          # the caregiver themselves
    _member(gid, mem_share, share_meds=1)          # shares meds → appears
    _member(gid, mem_noshare, share_meds=0)        # does NOT share → hidden
    with user_context(caregiver):
        d = get_care_circle()
    names = {m["name"] for m in d["members"]}
    ids = {m["user_id"] for m in d["members"]}
    assert mem_share in ids
    assert mem_noshare not in ids and caregiver not in ids   # consent gate + self excluded
    assert d["members"][0]["summary"]                        # each carries a spoken line


def test_route(app):
    c, _ = _uid(app, "circle3@medeasy.test")
    body = c.get("/api/care-circle").get_json()
    assert "members" in body and "needs_attention" in body


def test_route_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/care-circle").status_code in (401, 403)
