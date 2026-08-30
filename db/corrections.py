"""
db/corrections.py — fixing a mistake without erasing the entry.

Until now the app could delete a health entry but not correct one. Vitals,
symptoms and body measurements had no update path at all: a weight typed as 95
instead of 59 could only be deleted and re-added. That is not a neutral
workaround. It throws away the original logged_at, breaks any idempotency key
the offline queue wrote, drops a row into the trash that has to be reasoned
about, and — worst — leaves no sign that the number ever said something else.

So corrections are recorded, not silent. A health record whose numbers change
quietly is worse than one you cannot edit: if you showed a reading to a doctor
last week and it reads differently today, that is a fact about the record and
the record should say so. Every correction keeps the previous value.

What is deliberately NOT here:
  - No editing of what the app derived. BMI is recomputed from the corrected
    weight; you cannot hand-edit it into disagreeing with its own inputs.
  - No editing of dose logs. "Did you take it" is answered by taking it or by
    the backfill flow, which records WHEN you said so; letting adherence
    history be rewritten in place would make the adherence number meaningless.
  - No editing of another user's rows. Every statement is scoped by user_id.

EDITABLE is a registry, and tests/test_corrections.py fails the build if a
field is listed without a validator, or if a health table gains a delete route
without either becoming correctable or saying in NOT_EDITABLE why not.
"""
from __future__ import annotations

import json

from .core import (current_user_id, execute, new_id, now_iso, to_num, to_int,
                   valid_date)


def _text(v, limit):
    return str(v if v is not None else '')[:limit]


def _num(lo, hi):
    """A bounded number, or None when the field is being cleared."""
    def check(v):
        if v is None or v == '':
            return None
        return to_num(v, None, lo=lo, hi=hi)
    return check


def _int(lo, hi, default):
    return lambda v: to_int(v, default, lo=lo, hi=hi)


def _date(v):
    """A date the entry can be moved to. Invalid input leaves it alone, which
    is why this returns a sentinel the caller drops rather than None — None is
    a legitimate value for a nullable field."""
    s = str(v or '').strip()
    return s if valid_date(s) else _DROP


_DROP = object()


# ── The registry ────────────────────────────────────────────────────────────
# table -> field -> {check, label, type, …}. A field absent here cannot be
# corrected, which is the point: the list of what a person may rewrite in their
# own health record is a decision, not whatever the form happens to post.
#
# The label and type live here too, beside the validator, so the correction
# form is built from this one declaration. A second list in JS describing the
# same fields is how the two drift — this file already exists to be the single
# answer to "what may be changed".

def _f(check, label, type_='number', **extra):
    return dict(check=check, label=label, type=type_, **extra)


EDITABLE = {
    'vitals': {
        # value1/value2, not value — the column is value1 even though most of
        # the app reads a single "value". Named wrong here first, which would
        # have produced a 500 on every vitals correction; the schema check
        # below exists because of it.
        'value1':   _f(_num(0, 100000), 'Value'),
        'value2':   _f(_num(0, 100000), 'Second value'),
        'date_key': _f(_date, 'Date', 'date'),
        'notes':    _f(lambda v: _text(v, 500), 'Notes', 'text'),
    },
    'symptoms': {
        'name':     _f(lambda v: _text(v, 120).strip() or _DROP, 'Symptom', 'text'),
        'severity': _f(_int(1, 10, 5), 'Severity', 'number', min=1, max=10),
        'date_key': _f(_date, 'Date', 'date'),
        'time_of_day': _f(
            lambda v: (str(v) if str(v) in
                       ('morning', 'afternoon', 'evening', 'night') else _DROP),
            'Time of day', 'choice',
            choices=['morning', 'afternoon', 'evening', 'night']),
        'notes':    _f(lambda v: _text(v, 1000), 'Notes', 'text'),
    },
    'body_metrics': {
        'weight_kg':    _f(_num(0, 1000), 'Weight'),
        'body_fat_pct': _f(_num(0, 100), 'Body fat'),
        'waist_cm':     _f(_num(0, 500), 'Waist'),
        'hip_cm':       _f(_num(0, 500), 'Hip'),
        'chest_cm':     _f(_num(0, 500), 'Chest'),
        'arm_cm':       _f(_num(0, 200), 'Arm'),
        'date_key':     _f(_date, 'Date', 'date'),
        'notes':        _f(lambda v: _text(v, 500), 'Notes', 'text'),
    },
}


def field_spec(table: str) -> list:
    """What the correction form should offer, in order. UI metadata only —
    never the validators, which stay on the server where they are enforced."""
    return [{'name': name, 'label': m['label'], 'type': m['type'],
             **{k: v for k, v in m.items() if k in ('min', 'max', 'choices')}}
            for name, m in (EDITABLE.get(table) or {}).items()]

# Health tables that can be deleted but deliberately cannot be corrected, and
# why. Without this a table simply missing from EDITABLE is indistinguishable
# from one nobody got round to.
NOT_EDITABLE = {
    'dose_logs':
        'Whether a dose was taken is answered by taking it, or by the backfill '
        'flow which records when you said so. Rewriting that in place would '
        'make every adherence figure in the app unfalsifiable.',
    'sleep_logs':
        'Already correctable by its own route: re-logging the same night '
        'REPLACES it, because you sleep once a night. See log_sleep().',
    'food_logs':
        'Correctable through update_food_log, which re-scales the nutrition '
        'from the quantity rather than letting the two disagree.',
    'medicine_events':
        'An append-only history of what changed and when. Editing history is '
        'the one thing a history must not allow.',
    'notification_log':
        'A record of what the server sent. The user did not write it and '
        'cannot make it untrue by editing it.',
}


def editable_fields(table: str) -> set:
    return set(EDITABLE.get(table) or ())


def _row(table, row_id, uid):
    return execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?",
                   (row_id, uid), fetchone=True)


def apply_correction(table: str, row_id: str, changes: dict) -> dict:
    """Correct an entry in place, keeping what it said before.

    Returns {'row', 'changed'} where `changed` maps field -> {'from', 'to'}.
    Raises ValueError for an unknown table, LookupError when the row is not
    this user's. A field the registry does not list is ignored rather than
    rejected: a form posting an extra key should not fail the correction.
    """
    if table not in EDITABLE:
        raise ValueError(f'{table} is not correctable')
    uid = current_user_id()
    row = _row(table, row_id, uid)
    if not row:
        raise LookupError('no such entry')
    row = dict(row)

    validators = EDITABLE[table]
    clean = {}
    for field, raw in (changes or {}).items():
        if field not in validators:
            continue
        val = validators[field]['check'](raw)
        if val is _DROP:
            continue
        # Comparing str() because SQLite hands back 59 for a 59.0 REAL, and a
        # no-op correction should record nothing at all.
        if str(val) != str(row.get(field)) and not (val is None and row.get(field) is None):
            clean[field] = val
    if not clean:
        return {'row': row, 'changed': {}}

    before = {f: row.get(f) for f in clean}
    sets = ', '.join(f'{f}=?' for f in clean)
    execute(f"UPDATE {table} SET {sets} WHERE id=? AND user_id=?",
            (*clean.values(), row_id, uid), commit=True)

    _recompute(table, row_id, uid)
    _record(table, row_id, uid, before, clean)

    return {'row': dict(_row(table, row_id, uid)),
            'changed': {f: {'from': before[f], 'to': clean[f]} for f in clean}}


def _recompute(table, row_id, uid):
    """Derived columns follow their inputs.

    BMI is stored on body_metrics and is a function of weight and height.
    Correcting the weight and leaving the old BMI would leave the row
    internally contradictory — and the trend chart reads bmi, not weight.
    """
    if table != 'body_metrics':
        return
    row = _row(table, row_id, uid)
    if not row:
        return
    w = row['weight_kg']
    h = row['height_cm'] if 'height_cm' in row.keys() else None
    if not h:
        try:
            from .food import get_profile
            h = (get_profile() or {}).get('height_cm')
        except Exception:
            h = None
    try:
        bmi = round(float(w) / ((float(h) / 100) ** 2), 1) if w and h else None
    except (TypeError, ValueError, ZeroDivisionError):
        bmi = None
    execute("UPDATE body_metrics SET bmi=? WHERE id=? AND user_id=?",
            (bmi, row_id, uid), commit=True)


def _record(table, row_id, uid, before, after):
    """Keep the previous values. Best-effort: a correction the user asked for
    must not fail because the audit write did."""
    try:
        execute("""INSERT INTO entry_edits
                     (id, user_id, table_name, row_id, before_json, after_json, edited_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (new_id(), uid, table, row_id,
                 json.dumps(before, default=str),
                 json.dumps(after, default=str), now_iso()), commit=True)
    except Exception:
        pass


def corrections_for(table: str, row_ids) -> dict:
    """row_id -> [{'at', 'before', 'after'}], oldest first.

    Batched by design: the symptom list renders 20 rows and asking per row
    would be 20 queries for a marker most rows do not have.
    """
    ids = [str(i) for i in (row_ids or []) if i]
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    rows = execute(f"""SELECT row_id, before_json, after_json, edited_at
                       FROM entry_edits
                       WHERE user_id=? AND table_name=? AND row_id IN ({marks})
                       ORDER BY edited_at""",
                   (current_user_id(), table, *ids), fetchall=True) or []
    out = {}
    for r in rows:
        try:
            before = json.loads(r['before_json'])
            after = json.loads(r['after_json'])
        except (ValueError, TypeError):
            continue
        out.setdefault(r['row_id'], []).append(
            {'at': r['edited_at'], 'before': before, 'after': after})
    return out
