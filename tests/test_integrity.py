"""Child rows whose parent is gone, and the numbers that counted them.

The bug this file exists for: 42% of one account's dose logs pointed at
medicines that had been deleted, and the weekly adherence insight counted every
one. "Only 55% of doses taken this week — worth a look at your reminder times"
was partly a verdict on medicines the user no longer had, about doses they could
not have taken, with no way to tell from the screen.

Two rules come out of that, and both are enforced here rather than remembered.

  Deleting is recoverable, so children stay put. Soft-delete lifts a medicine
  into the trash and a restore puts it back with the same id; its dose history
  has to still be there when it lands. Cascading on soft-delete would turn a
  mis-tap into permanent data loss.

  Purging is not recoverable, so children go too. Once the parent can never come
  back, a child pointing at it is a row nothing can ever show, that goes on
  skewing whatever counts it.

The registry is the real deliverable. Every child-to-parent reference in the
live schema must appear in DEPENDENTS with a policy and a reason — the same
shape as the search, trash and export registries, for the same reason.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import (init_db, user_context, execute, new_id, now_iso,
                     user_today, DATA_TABLES, table_columns)
from db import integrity

PW = "integ-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,),
                           fetchone=True))["id"]


def _med(uid, name="Metformin"):
    mid = new_id()
    execute("""INSERT INTO medicines (id, user_id, name, dosage, unit, active, created_at)
               VALUES (?,?,?,?,?,1,?)""",
            (mid, uid, name, "500", "mg", now_iso()), commit=True)
    return mid


def _dose(uid, mid, date_key=None, taken=1):
    lid = new_id()
    execute("""INSERT INTO dose_logs (id, user_id, medicine_id, date_key, time_key,
                                      taken, taken_at)
               VALUES (?,?,?,?,?,?,?)""",
            (lid, uid, mid, date_key or user_today(), "09:00", taken, now_iso()),
            commit=True)
    return lid


def _count(table, uid):
    return execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=?", (uid,),
                   fetchone=True)["n"]


# ── The registry is complete ────────────────────────────────────────────────

def test_every_schema_reference_has_a_declared_policy():
    """A new child table joins the registry or fails the build. The whole class
    of bug here is a reference nobody decided about."""
    init_db()
    known = {(c, fk) for c, fk, _p, _pol, _why in integrity.DEPENDENTS}
    tables = set(DATA_TABLES)

    def parent_for(col):
        base = col[:-3]
        for cand in (base + 's', base, base + 'es', base.rstrip('y') + 'ies'):
            if cand in tables:
                return cand
        return {'plan_id': 'rehab_plans', 'cycle_id': 'menstrual_cycles'}.get(col)

    undeclared = []
    for t in sorted(tables):
        for col in sorted(table_columns(t)):
            if not col.endswith('_id') or col == 'user_id':
                continue
            parent = parent_for(col)
            if parent and parent != t and (t, col) not in known:
                undeclared.append(f'{t}.{col} -> {parent}')
    assert not undeclared, (
        'these reference another table and nothing says what happens to them '
        'when the parent is destroyed — add them to db/integrity.DEPENDENTS '
        'with a policy and a reason: ' + ', '.join(undeclared))


def test_every_policy_is_one_of_the_two_and_explained():
    for child, fk, parent, policy, why in integrity.DEPENDENTS:
        assert policy in ('cascade', 'keep'), f'{child}.{fk}: {policy!r}'
        assert len(why) > 50, (
            f'{child}.{fk} needs a real reason, not "{why}"')


def test_the_registry_points_at_real_tables_and_columns():
    """A stale entry silently stops protecting anything."""
    init_db()
    stale = []
    for child, fk, parent, _pol, _why in integrity.DEPENDENTS:
        if not table_columns(child):
            stale.append(f'{child} (table gone)')
        elif fk not in table_columns(child):
            stale.append(f'{child}.{fk} (column gone)')
        elif not table_columns(parent):
            stale.append(f'{parent} (parent gone)')
    assert not stale, 'stale registry entries: ' + ', '.join(stale)


# ── Deleting keeps history; purging does not ────────────────────────────────

def test_deleting_a_medicine_keeps_its_dose_history(app):
    """A restore has to find the history waiting for it. Cascading here would
    turn a mis-tap into permanent loss."""
    c, uid = _uid(app, "int1@medeasy.test")
    with user_context(uid):
        mid = _med(uid)
        _dose(uid, mid); _dose(uid, mid, taken=0)
        from db.medicines import delete_medicine
        delete_medicine(mid)
        assert _count('dose_logs', uid) == 2, 'the dose history was destroyed'


def test_restoring_a_medicine_reunites_it_with_its_history(app):
    c, uid = _uid(app, "int2@medeasy.test")
    with user_context(uid):
        mid = _med(uid)
        _dose(uid, mid)
        from db.medicines import delete_medicine
        from db.trash import list_trash, restore
        delete_medicine(mid)
        item = [i for i in list_trash() if i['kind'] == 'Medicine'][0]
        assert restore(item['id'])['ok'] is True
        # Same id back, so the logs point at a real row again.
        assert integrity.find_orphans(uid) == []


def test_purging_a_medicine_takes_its_dose_logs(app):
    """The fix. Once the medicine can never come back, its logs are rows nothing
    can show that go on counting toward adherence."""
    c, uid = _uid(app, "int3@medeasy.test")
    with user_context(uid):
        mid = _med(uid)
        _dose(uid, mid); _dose(uid, mid); _dose(uid, mid)
        from db.medicines import delete_medicine
        from db.trash import list_trash, purge
        delete_medicine(mid)
        assert _count('dose_logs', uid) == 3
        item = [i for i in list_trash() if i['kind'] == 'Medicine'][0]
        assert purge(item['id']) is True
        assert _count('dose_logs', uid) == 0, 'the logs outlived the medicine'


def test_expiry_cascades_the_same_way_as_an_explicit_purge(app):
    """Thirty days up is the other route to unrecoverable, and it runs
    unattended — which is exactly how the orphans piled up unnoticed."""
    c, uid = _uid(app, "int4@medeasy.test")
    with user_context(uid):
        mid = _med(uid)
        _dose(uid, mid); _dose(uid, mid)
        from db.medicines import delete_medicine
        from db.trash import purge_expired
        delete_medicine(mid)
        # Age the trashed row past its window.
        execute("UPDATE deleted_items SET expires_at=? WHERE user_id=?",
                ("2000-01-01T00:00:00", uid), commit=True)
        purge_expired()
        assert _count('dose_logs', uid) == 0


def test_emptying_the_trash_cascades_too(app):
    c, uid = _uid(app, "int5@medeasy.test")
    with user_context(uid):
        mid = _med(uid)
        _dose(uid, mid)
        from db.medicines import delete_medicine
        from db.trash import empty_trash
        delete_medicine(mid)
        empty_trash()
        assert _count('dose_logs', uid) == 0


def test_a_kept_relation_is_not_cascaded(app):
    """A question survives the appointment it was pinned to: people write down
    what to ask, the visit moves, and the question still matters."""
    c, uid = _uid(app, "int6@medeasy.test")
    with user_context(uid):
        aid = new_id()
        execute("""INSERT INTO appointments (id, user_id, title, kind, date, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (aid, uid, "Review", "doctor", "2026-08-01", now_iso()), commit=True)
        qid = new_id()
        execute("""INSERT INTO doctor_questions (id, user_id, question, asked,
                                                 appointment_id, created_at)
                   VALUES (?,?,?,0,?,?)""",
                (qid, uid, "Ask about the dose", aid, now_iso()), commit=True)
        assert integrity.purge_children('appointments', aid, uid) == 0
        assert _count('doctor_questions', uid) == 1


# ── The numbers ─────────────────────────────────────────────────────────────

def test_adherence_ignores_doses_of_medicines_that_are_gone(app):
    """The original bug, as a test. Skipped doses of a deleted medicine used to
    drag down this week's adherence, and the user could do nothing about it."""
    c, uid = _uid(app, "int7@medeasy.test")
    with user_context(uid):
        live = _med(uid, "Live")
        for _ in range(5):
            _dose(uid, live, taken=1)
        # A medicine that is gone for good, whose doses were all skipped.
        ghost = new_id()
        for _ in range(5):
            _dose(uid, ghost, taken=0)
        from db.insights import get_insight_cards
        text = ' '.join(str(i) for i in (get_insight_cards(limit=10) or []))
    assert '100%' in text or 'excellent' in text.lower(), (
        f'adherence counted the ghost medicine: {text[:200]}')
    assert '50%' not in text


def test_what_family_sees_matches_the_medicine_list_they_see(app):
    """Otherwise a caregiver reads "3 of 5 doses" beside a list of three."""
    c, uid = _uid(app, "int8@medeasy.test")
    with user_context(uid):
        live = _med(uid, "Live")
        _dose(uid, live, taken=1)
        ghost = new_id()
        _dose(uid, ghost, taken=0)
        row = execute("""SELECT COUNT(*) AS total FROM dose_logs d
                         WHERE d.user_id=? AND d.date_key=?
                           AND EXISTS (SELECT 1 FROM medicines m WHERE m.id=d.medicine_id)""",
                      (uid, user_today()), fetchone=True)
    assert row['total'] == 1, 'the family view counts doses of deleted medicines'


# ── Finding and repairing existing drift ────────────────────────────────────

def test_orphans_are_found_and_counted(app):
    c, uid = _uid(app, "int9@medeasy.test")
    with user_context(uid):
        _dose(uid, new_id())
        _dose(uid, new_id())
        found = integrity.find_orphans(uid)
    assert found and found[0]['child'] == 'dose_logs'
    assert found[0]['count'] == 2


def test_a_repair_leaves_recoverable_rows_alone(app):
    """The one thing a repair must never do: destroy the history of a medicine
    the user is about to restore."""
    c, uid = _uid(app, "int10@medeasy.test")
    with user_context(uid):
        mid = _med(uid)
        _dose(uid, mid); _dose(uid, mid)
        from db.medicines import delete_medicine
        delete_medicine(mid)                 # now in the trash, logs orphaned
        res = integrity.repair_orphans(uid, dry_run=False)
        assert res['removed'] == 0, 'a repair destroyed recoverable history'
        assert _count('dose_logs', uid) == 2


def test_a_repair_removes_rows_whose_parent_is_gone_for_good(app):
    c, uid = _uid(app, "int11@medeasy.test")
    with user_context(uid):
        _dose(uid, new_id()); _dose(uid, new_id())
        plan = integrity.repair_orphans(uid, dry_run=True)
        assert plan['removed'] == 2 and plan['dry_run'] is True
        assert _count('dose_logs', uid) == 2, 'a dry run deleted something'
        done = integrity.repair_orphans(uid, dry_run=False)
        assert done['removed'] == 2
        assert _count('dose_logs', uid) == 0


def test_the_repair_is_scoped_to_one_user(app):
    ca, ua = _uid(app, "int12a@medeasy.test")
    cb, ub = _uid(app, "int12b@medeasy.test")
    with user_context(ua):
        _dose(ua, new_id())
    with user_context(ub):
        integrity.repair_orphans(ub, dry_run=False)
    assert _count('dose_logs', ua) == 1, "another user's rows were removed"


def test_the_routes_report_and_repair(app):
    c, uid = _uid(app, "int13@medeasy.test")
    with user_context(uid):
        _dose(uid, new_id())
    r = c.get("/api/storage/integrity").get_json()
    assert r['total'] == 1
    assert 'no longer have' in r['note']
    assert c.post("/api/storage/integrity").get_json()['removed'] == 1
    assert c.get("/api/storage/integrity").get_json()['total'] == 0


def test_the_routes_need_a_signed_in_user(app):
    anon = app.test_client()
    assert anon.get("/api/storage/integrity").status_code == 401
    assert anon.post("/api/storage/integrity").status_code == 401
