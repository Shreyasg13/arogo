"""
tests/test_corrections.py — fixing an entry instead of erasing it.

The app could delete a health entry but not correct one, so a weight typed as
95 instead of 59 could only be deleted and re-added. Two things have to hold
now that it can be corrected:

  The correction must actually land, on the right row, for the right user, and
  anything derived from the corrected value must move with it.

  And it must be visible. A health record whose numbers change silently is
  worse than one you cannot edit — if a reading was shown to a doctor last week
  and reads differently today, that is a fact about the record.
"""
import uuid

import pytest

import auth as auth_module
from app import create_app
from db.core import execute, init_db, new_id, now_iso, user_context
from db.corrections import (EDITABLE, NOT_EDITABLE, apply_correction,
                            corrections_for)

PW = 'Corrections2026!'


@pytest.fixture(scope='module')
def app():
    a = create_app(); a.config['TESTING'] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _user(app):
    email = f'corrections-{uuid.uuid4().hex[:10]}@x.test'
    c = app.test_client()
    c.post('/auth/register', json={'email': email, 'password': PW})
    uid = dict(execute('SELECT id FROM users WHERE email=?', (email,),
                       fetchone=True))['id']
    return c, uid


def _symptom(uid, name='Headache', severity=5, date_key='2026-08-01'):
    sid = new_id()
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,
                                     region,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sid, name, severity, date_key, 'morning', '', '', now_iso(), uid),
            commit=True)
    return sid


def _weight(uid, kg=95, date_key='2026-08-01'):
    bid = new_id()
    execute("""INSERT INTO body_metrics (id,date_key,weight_kg,bmi,notes,created_at,user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (bid, date_key, kg, 33.1, '', now_iso(), uid), commit=True)
    return bid


# ── The registry is a decision, not an accident ─────────────────────────────

def test_every_editable_field_has_a_validator():
    for table, fields in EDITABLE.items():
        assert fields, f'{table} is listed as editable with no fields'
        for field, meta in fields.items():
            assert callable(meta.get('check')), f'{table}.{field} has no validator'
            # The form is built from this declaration, so a field without a
            # label would render as a blank box the user cannot interpret.
            assert meta.get('label'), f'{table}.{field} has no label'
            assert meta.get('type') in ('number', 'text', 'date', 'choice'),                 f'{table}.{field} has an unrenderable type {meta.get("type")!r}'


def test_a_deletable_health_table_is_either_correctable_or_explains_why_not():
    """A table simply missing from EDITABLE is indistinguishable from one
    nobody got round to. Anything a person can delete they should be able to
    fix — or the file should say, in words, why not."""
    accounted = set(EDITABLE) | set(NOT_EDITABLE)
    # The day-to-day health entries a person logs and can delete. Listed here
    # rather than derived, so adding a seventh is a deliberate act: the point
    # is that someone has decided, for each one, whether a typo can be fixed.
    for table in ('vitals', 'symptoms', 'body_metrics', 'dose_logs',
                  'sleep_logs', 'food_logs'):
        assert table in accounted, (
            f'{table} can be deleted but is neither correctable nor listed in '
            f'NOT_EDITABLE with a reason')


def test_every_editable_field_is_a_real_column(app):
    """The registry names columns, and a name that is nearly right fails at the
    UPDATE with a 500 rather than anywhere useful. `vitals.value` was written
    here when the column is `value1`; every vitals correction would have
    errored, and no test touched vitals until this one existed.
    """
    from db.core import table_columns
    for table, fields in EDITABLE.items():
        cols = set(table_columns(table))
        assert cols, f'{table} does not exist'
        unknown = sorted(set(fields) - cols)
        assert not unknown, f'{table} has no column(s) {unknown} — known: {sorted(cols)}'


@pytest.mark.parametrize('table', sorted(EDITABLE))
def test_every_correctable_table_actually_survives_a_correction(table, app):
    """Exercises the real UPDATE for each table, so a mis-named column or a
    validator that returns something SQLite refuses is caught per-table rather
    than only wherever a test happened to look."""
    from db.core import table_columns
    _c, uid = _user(app)
    with user_context(uid):
        cols = table_columns(table)
        stamp = 'logged_at' if 'logged_at' in cols else 'created_at'
        # NOT NULL columns each table needs before it will accept a row at all.
        required = {'symptoms': {'name': 'Headache'},
                    'vitals': {'type': 'blood_pressure', 'value1': 120}}.get(table, {})
        rid = new_id()
        names = ['id', 'date_key', stamp, 'user_id', *required]
        execute(f"INSERT INTO {table} ({','.join(names)}) "
                f"VALUES ({','.join('?' * len(names))})",
                (rid, '2026-08-01', now_iso(), uid, *required.values()), commit=True)
        # Correct the first non-date field the registry offers.
        field = next(f for f in EDITABLE[table] if f != 'date_key')
        spec = EDITABLE[table][field]
        value = 4 if spec['type'] == 'number' else (
            spec['choices'][0] if spec['type'] == 'choice' else 'corrected')
        out = apply_correction(table, rid, {field: value})
        assert out['row']['id'] == rid
        # float(4) for a REAL column, '4' for a TEXT one — compare by value,
        # not by the string SQLite chose to hand back.
        got = out['row'][field]
        assert (float(got) == float(value)) if spec['type'] == 'number'             else str(got) == str(value), out['changed']


def test_purging_an_entry_takes_its_corrections_with_it(app):
    """NOT_TRASHABLE refuses to let a correction be deleted on its own, on the
    grounds that it goes when the entry does. That has to actually happen —
    otherwise the reason is just a sentence and the rows are immortal."""
    from db.integrity import purge_children
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid, severity=9)
        apply_correction('symptoms', sid, {'severity': 4})
        assert corrections_for('symptoms', [sid])
        purge_children('symptoms', sid, uid)
        assert corrections_for('symptoms', [sid]) == {}


def test_purging_one_entry_leaves_another_entrys_corrections(app):
    from db.integrity import purge_children
    _c, uid = _user(app)
    with user_context(uid):
        keep, go = _symptom(uid), _symptom(uid)
        apply_correction('symptoms', keep, {'severity': 2})
        apply_correction('symptoms', go, {'severity': 3})
        purge_children('symptoms', go, uid)
        assert set(corrections_for('symptoms', [keep, go])) == {keep}


def test_a_table_is_not_listed_in_both_places():
    both = set(EDITABLE) & set(NOT_EDITABLE)
    assert not both, f'listed as both correctable and not: {sorted(both)}'


def test_every_not_editable_entry_gives_a_real_reason():
    for table, why in NOT_EDITABLE.items():
        assert len(why) > 60, f'{table} is excluded without a real reason: {why!r}'


def test_derived_and_history_tables_are_never_editable():
    """Editing history is the one thing a history must not allow."""
    for table in ('medicine_events', 'notification_log', 'dose_logs'):
        assert table not in EDITABLE, f'{table} must not be user-editable'


# ── Corrections land ────────────────────────────────────────────────────────

def test_a_symptom_severity_is_corrected_in_place(app):
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid, severity=9)
        out = apply_correction('symptoms', sid, {'severity': 3})
        assert out['row']['severity'] == 3
        assert out['changed']['severity'] == {'from': 9, 'to': 3}
        # Same row, not a new one.
        assert out['row']['id'] == sid


def test_the_entry_keeps_its_original_timestamp(app):
    """The reason delete-and-re-add was not an acceptable workaround."""
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid)
        before = dict(execute('SELECT logged_at FROM symptoms WHERE id=?',
                              (sid,), fetchone=True))['logged_at']
        apply_correction('symptoms', sid, {'severity': 2})
        after = dict(execute('SELECT logged_at FROM symptoms WHERE id=?',
                             (sid,), fetchone=True))['logged_at']
        assert after == before


def test_correcting_a_weight_recomputes_bmi(app):
    """The trend chart reads bmi, not weight. Leaving the old BMI beside a
    corrected weight makes the row contradict itself."""
    _c, uid = _user(app)
    with user_context(uid):
        from db.food import update_profile
        update_profile({'height_cm': 170})
        bid = _weight(uid, kg=95)
        out = apply_correction('body_metrics', bid, {'weight_kg': 59})
        assert out['row']['weight_kg'] == 59
        assert out['row']['bmi'] == pytest.approx(20.4, abs=0.2), out['row']['bmi']


def test_a_field_not_in_the_registry_is_ignored_not_applied(app):
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid)
        out = apply_correction('symptoms', sid, {'user_id': 'someone-else',
                                                 'id': 'hijacked',
                                                 'severity': 4})
        assert out['row']['user_id'] == uid
        assert out['row']['id'] == sid
        assert out['row']['severity'] == 4


def test_an_unchanged_value_records_no_correction(app):
    """Opening the edit form and saving without changing anything must not
    stamp the record as corrected."""
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid, severity=5)
        out = apply_correction('symptoms', sid, {'severity': 5})
        assert out['changed'] == {}
        assert corrections_for('symptoms', [sid]) == {}


def test_an_out_of_range_value_is_clamped_not_stored_raw(app):
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid)
        out = apply_correction('symptoms', sid, {'severity': 99})
        assert 1 <= out['row']['severity'] <= 10


def test_a_bad_date_leaves_the_entry_where_it_was(app):
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid, date_key='2026-08-01')
        apply_correction('symptoms', sid, {'date_key': 'not-a-date'})
        row = dict(execute('SELECT date_key FROM symptoms WHERE id=?',
                           (sid,), fetchone=True))
        assert row['date_key'] == '2026-08-01'


def test_an_uncorrectable_table_is_refused(app):
    _c, uid = _user(app)
    with user_context(uid):
        with pytest.raises(ValueError):
            apply_correction('dose_logs', 'anything', {'taken': 0})


# ── It stays the user's own record ──────────────────────────────────────────

def test_one_user_cannot_correct_another_users_entry(app):
    _c1, uid1 = _user(app)
    _c2, uid2 = _user(app)
    with user_context(uid1):
        sid = _symptom(uid1, severity=7)
    with user_context(uid2):
        with pytest.raises(LookupError):
            apply_correction('symptoms', sid, {'severity': 1})
    with user_context(uid1):
        row = dict(execute('SELECT severity FROM symptoms WHERE id=?',
                           (sid,), fetchone=True))
        assert row['severity'] == 7


def test_corrections_are_only_visible_to_their_owner(app):
    _c1, uid1 = _user(app)
    _c2, uid2 = _user(app)
    with user_context(uid1):
        sid = _symptom(uid1)
        apply_correction('symptoms', sid, {'severity': 2})
        assert corrections_for('symptoms', [sid])
    with user_context(uid2):
        assert corrections_for('symptoms', [sid]) == {}


# ── The record says it was corrected ────────────────────────────────────────

def test_what_it_said_before_is_kept(app):
    _c, uid = _user(app)
    with user_context(uid):
        bid = _weight(uid, kg=95)
        apply_correction('body_metrics', bid, {'weight_kg': 59})
        edits = corrections_for('body_metrics', [bid])
        assert bid in edits, 'the correction left no trace'
        assert edits[bid][0]['before']['weight_kg'] == 95
        assert edits[bid][0]['after']['weight_kg'] == 59


def test_repeated_corrections_are_all_kept_oldest_first(app):
    _c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid, severity=9)
        apply_correction('symptoms', sid, {'severity': 5})
        apply_correction('symptoms', sid, {'severity': 2})
        hist = corrections_for('symptoms', [sid])[sid]
        assert [h['before']['severity'] for h in hist] == [9, 5]


def test_corrections_are_fetched_for_many_rows_at_once(app):
    _c, uid = _user(app)
    with user_context(uid):
        a, b, c = _symptom(uid), _symptom(uid), _symptom(uid)
        apply_correction('symptoms', a, {'severity': 1})
        apply_correction('symptoms', c, {'severity': 2})
        got = corrections_for('symptoms', [a, b, c])
        assert set(got) == {a, c}, 'uncorrected rows must not appear'


# ── The routes ──────────────────────────────────────────────────────────────

def test_correcting_needs_a_session(app):
    anon = app.test_client()
    r = anon.patch('/api/entries/symptoms/whatever', json={'severity': 1})
    assert r.status_code == 401


def test_patch_route_corrects_and_reports_what_changed(app):
    c, uid = _user(app)
    with user_context(uid):
        sid = _symptom(uid, severity=8)
    r = c.patch(f'/api/entries/symptoms/{sid}', json={'severity': 3})
    assert r.status_code == 200
    body = r.get_json()
    assert body['success'] and body['row']['severity'] == 3
    assert body['changed']['severity'] == {'from': 8, 'to': 3}


def test_patch_route_404s_for_someone_elses_row(app):
    c1, uid1 = _user(app)
    c2, _uid2 = _user(app)
    with user_context(uid1):
        sid = _symptom(uid1)
    assert c2.patch(f'/api/entries/symptoms/{sid}',
                    json={'severity': 1}).status_code == 404


def test_patch_route_400s_for_an_uncorrectable_table(app):
    c, _uid = _user(app)
    r = c.patch('/api/entries/dose_logs/anything', json={'taken': 0})
    assert r.status_code == 400
    assert 'not correctable' in r.get_json()['error']


def test_edits_route_returns_only_the_rows_asked_for(app):
    c, uid = _user(app)
    with user_context(uid):
        a, b = _symptom(uid), _symptom(uid)
        apply_correction('symptoms', a, {'severity': 1})
        apply_correction('symptoms', b, {'severity': 2})
    r = c.get(f'/api/entries/symptoms/edits?ids={a}')
    assert r.status_code == 200
    assert set(r.get_json()['edits']) == {a}
