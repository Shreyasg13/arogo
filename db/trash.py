"""Deleting a health record should be recoverable.

Every delete in this app was a hard DELETE — eighty-two of them. Tapping the
wrong row removed a lab result, a vaccination date or a scan of a discharge
summary permanently, and the only "undo" was a four-and-a-half second bar before
the request was even sent. Some of that data cannot be recreated: a lab value
from three years ago exists on a piece of paper you no longer have.

So a delete moves the row here instead, whole, and it can be put back for thirty
days. After that it is genuinely gone — a trash that never empties is just a
second copy of everything the user asked you to destroy, which is its own kind of
broken promise.

What this deliberately is NOT:

  - It is not a version history. Only deletes land here, not edits.
  - It is not a way around account deletion. Erasing an account erases the trash
    with it, and emptying the trash is immediate and real.
  - It is not silent. Restoring says what came back and where it went.
"""
import datetime as dt
import json

from .core import (execute, current_user_id, new_id, now_iso, table_columns,
                   transaction, savepoint)

# Long enough to cover "I did something stupid and noticed a fortnight later",
# short enough that the trash isn't a shadow copy of a deleted medical history.
RETENTION_DAYS = 30


class Trashable:
    """How one table's rows are named once the row itself is gone.

    `label` runs against the row BEFORE it is deleted, because after the delete
    the only thing that could describe it is the payload — and a user scanning
    their trash needs to read "HbA1c — 12 Mar", not "lab_results row a3f9…".
    """
    __slots__ = ('table', 'kind', 'label', 'view', 'private')

    def __init__(self, table, kind, label, view, private=False):
        self.table, self.kind, self.label = table, kind, label
        self.view, self.private = view, private


def _d(row, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ''):
            return str(v)
    return ''


def _dated(text, row, *date_keys):
    d = _d(row, *date_keys)[:10]
    return f"{text} — {d}" if text and d else (text or d or '')


# Tables whose rows are recoverable. Anything not listed still hard-deletes, and
# a test requires that omission to be a stated decision rather than an oversight.
TRASHABLE = [
    Trashable('medicines', 'Medicine', lambda r: _d(r, 'name'), 'medicines'),
    Trashable('prescriptions', 'Prescription',
              lambda r: _dated(_d(r, 'prescriber') or 'Prescription', r, 'date_issued'),
              'prescriptions'),
    Trashable('reports', 'Medical record',
              lambda r: _dated(_d(r, 'original_name', 'filename'), r, 'report_date'),
              'reports'),
    Trashable('lab_results', 'Lab result',
              lambda r: _dated(_d(r, 'name'), r, 'date_key'), 'labs'),
    Trashable('vitals', 'Vital',
              lambda r: _dated(_d(r, 'type').replace('_', ' '), r, 'date_key'), 'body'),
    Trashable('symptoms', 'Symptom',
              lambda r: _dated(_d(r, 'name'), r, 'date_key'), 'body'),
    Trashable('allergies', 'Allergy', lambda r: _d(r, 'allergen'), 'allergies'),
    Trashable('immunizations', 'Vaccine',
              lambda r: _dated(_d(r, 'name'), r, 'date_given'), 'immunizations'),
    Trashable('procedures', 'Procedure',
              lambda r: _dated(_d(r, 'name'), r, 'date_key'), 'procedures'),
    Trashable('appointments', 'Appointment',
              lambda r: _dated(_d(r, 'title', 'kind'), r, 'date'), 'upcoming'),
    Trashable('providers', 'Care team member', lambda r: _d(r, 'name'), 'care-team'),
    Trashable('dental_vision_visits', 'Dental / vision visit',
              lambda r: _dated(_d(r, 'kind'), r, 'visit_date'), 'dentalvision'),
    Trashable('vision_prescriptions', 'Glasses prescription',
              lambda r: _dated(_d(r, 'kind') or 'Prescription', r, 'rx_date'),
              'dentalvision'),
    Trashable('family_history', 'Family history', lambda r: _d(r, 'condition'),
              'familyhistory'),
    Trashable('health_notes', 'Note', lambda r: _d(r, 'body')[:60], 'notes',
              private=True),
    Trashable('insurance_policies', 'Insurance policy', lambda r: _d(r, 'insurer'),
              'insurance'),
    Trashable('claims', 'Claim', lambda r: _dated(_d(r, 'insurer') or 'Claim', r,
                                                  'date_submitted'), 'claims'),
    Trashable('health_expenses', 'Expense',
              lambda r: _dated(_d(r, 'description', 'category'), r, 'date_key'),
              'spending'),
    Trashable('symptom_photos', 'Photo',
              lambda r: _dated(_d(r, 'label') or 'Photo', r, 'taken_date'),
              'symptomphotos'),
    Trashable('home_supplies', 'Supply', lambda r: _d(r, 'name'), 'supplies'),
    Trashable('dependents', 'Person you care for', lambda r: _d(r, 'name'),
              'dependents'),
    Trashable('experiments', 'Experiment', lambda r: _d(r, 'title'), 'experiments'),
    Trashable('health_goals', 'Goal', lambda r: _d(r, 'title'), 'goals'),
    Trashable('blood_donations', 'Blood donation',
              lambda r: _dated(_d(r, 'place') or 'Donation', r, 'donated_on'),
              'donations'),
    Trashable('health_reminders', 'Reminder', lambda r: _d(r, 'title'), 'reminders'),
    Trashable('care_plan_items', 'Care plan item', lambda r: _d(r, 'title'),
              'care-plan'),
    Trashable('body_metrics', 'Body measurement',
              lambda r: _dated('Measurement', r, 'date_key'), 'progress'),
    Trashable('thoughts', 'Journal entry',
              lambda r: _dated(_d(r, 'content')[:60], r, 'date_key'), 'thoughts',
              private=True),
]

# Deletes that stay immediate, each for a reason. A row here is a decision, not
# an omission — the test below will not accept a table that appears in neither
# list, and "we forgot" is exactly how a recycle bin ends up half-working.
NOT_TRASHABLE = {
    'dose_logs': 'un-ticking a dose is a correction, not a deletion; the tick '
                 'is re-appliable in one tap',
    'habit_logs': 'same — a tick per day, re-appliable in one tap',
    'hydration_logs': 'a glass of water, re-logged in one tap',
    'food_logs': 'a meal entry, re-logged in one tap',
    'dose_snoozes': 'transient reminder state',
    'lab_rechecks': 'a flag on a lab, not a record',
    'notification_log': 'app-generated alerts, not the user\'s records',
    'sync_log': 'integration diagnostics',
    'oauth_tokens': 'disconnecting an integration must actually disconnect it — '
                    'a recoverable token is a security problem, not a convenience',
    'push_subscriptions': 'turning notifications off must take effect at once',
    'share_snapshots': 'revoking a share link must revoke it immediately; a '
                       'restorable link would still be live in the meantime',
    'deleted_items': 'the trash itself — an undo for the undo is a loop, not a '
                     'safety net',
    'questionnaire_runs': 'a completed questionnaire is deleted deliberately; '
                          'keeping a record of mood answers after someone asked '
                          'for it to go is the wrong default',
    'user_sessions': 'signing a device out must take effect immediately; a '
                     'restorable revocation is a security hole',
    'security_events': 'a security log the account holder can delete from is '
                       'not a security log',
    'travel_trips': 'a trip is two dates and a time zone, re-entered in seconds',
    'illness_episodes': 'deleting one removes only the grouping — every '
                        'symptom and reading it covered stays exactly where it is',
    'todos': 'a task, re-typed in seconds',
    'meal_plans': 'a planned meal, re-added in seconds',
    'custom_foods': 'a food definition, re-added in seconds',
    'habits': 'archiving keeps the history; deleting is the deliberate choice',
    'fitness_activities': 'synced from a device and re-syncable',
    'workout_sets': 'a set in a workout, re-entered in seconds',
    'sleep_logs': 're-logged from the same night\'s memory',
    'fasting_sessions': 'a timer, restartable',
    'quit_plans': 'a single plan the user manages directly',
    'menstrual_cycles': 'edited in place on the cycle page rather than deleted',
    'cycle_symptoms': 'edited in place on the cycle page rather than deleted',
    'menopause_logs': 'edited in place rather than deleted',
    'pregnancy': 'edited in place rather than deleted',
    'pregnancy_logs': 'edited in place rather than deleted',
    'med_taper_steps': 'part of a taper plan, edited as a whole',
    'med_effectiveness': 'a rating, re-entered in one tap',
    'injection_logs': 'a site note, re-entered in one tap',
    'medicine_events': 'an automatic audit trail; it is not user-deletable',
    'action_plans': 'a plan the user edits in place',
    'doctor_questions': 'a question, re-typed in seconds',
    'visit_action_items': 'a follow-up line, re-typed in seconds',
    'weekly_reviews': 'edited in place each week',
    'dependent_records': 'removed together with the dependent, which IS trashable',
    'environment_days': 'imported data, re-importable from the same file',
    'measurement_reminders': 'a schedule, re-set in seconds',
    'reminder_settings': 'preferences, not records',
    'user_profile': 'settings, not records',
    'emergency_info': 'a single card that is edited, never deleted',
    'vital_targets': 'a target, re-set in seconds',
}

_BY_TABLE = {t.table: t for t in TRASHABLE}


def _expiry(now=None):
    base = dt.datetime.fromisoformat(now) if now else dt.datetime.now()
    return (base + dt.timedelta(days=RETENTION_DAYS)).isoformat()


def soft_delete(table: str, rid: str) -> bool:
    """Move one row to the trash. Returns False if it wasn't there to begin with.

    Not registered as trashable → an ordinary delete, so a caller can't
    accidentally make something recoverable that shouldn't be.
    """
    uid = current_user_id()
    spec = _BY_TABLE.get(table)
    if spec is None:
        execute(f"DELETE FROM {table} WHERE id=? AND user_id=?", (rid, uid), commit=True)
        return True
    row = execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?", (rid, uid),
                  fetchone=True)
    if not row:
        return False
    row = dict(row)
    try:
        label = str(spec.label(row) or '').strip()[:120]
    except Exception:
        label = ''
    # Both statements or neither: a copy that isn't followed by the delete leaves
    # the row visible twice, and a delete without the copy is the bug being fixed.
    with transaction():
        execute("""INSERT INTO deleted_items
                     (id, table_name, row_id, payload, kind, label,
                      deleted_at, expires_at, user_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (new_id(), table, rid, json.dumps(row, default=str),
                 spec.kind, label, now_iso(), _expiry(), uid))
        execute(f"DELETE FROM {table} WHERE id=? AND user_id=?", (rid, uid))
    return True


def list_trash(q: str = '', include_private: bool = True, limit: int = 200) -> list:
    """What's recoverable, newest first, with how long is left."""
    uid = current_user_id()
    sql = "SELECT * FROM deleted_items WHERE user_id=?"
    params = [uid]
    if q and q.strip():
        sql += " AND (LOWER(COALESCE(label,'')) LIKE ? OR LOWER(COALESCE(kind,'')) LIKE ?)"
        pat = f"%{q.strip().lower()}%"
        params += [pat, pat]
    sql += f" ORDER BY deleted_at DESC LIMIT {int(limit)}"
    rows = execute(sql, params, fetchall=True) or []
    now = dt.datetime.now()
    out = []
    for r in rows:
        spec = _BY_TABLE.get(r['table_name'])
        if spec and spec.private and not include_private:
            continue
        try:
            left = (dt.datetime.fromisoformat(r['expires_at']) - now).days
        except Exception:
            left = None
        out.append({
            'id': r['id'],
            'kind': r['kind'] or (spec.kind if spec else r['table_name']),
            'label': r['label'] or '(no name)',
            'deleted_at': r['deleted_at'],
            'days_left': max(0, left) if left is not None else None,
            'view': spec.view if spec else None,
            'restorable': spec is not None,
        })
    return out


def trash_count(q: str = '') -> int:
    return len(list_trash(q))


def restore(item_id: str) -> dict:
    """Put one row back.

    Columns the current schema no longer has are dropped, exactly as a backup
    restore does — a record from before a migration should still come back, minus
    a field that no longer exists, rather than not at all.
    """
    uid = current_user_id()
    item = execute("SELECT * FROM deleted_items WHERE id=? AND user_id=?",
                   (item_id, uid), fetchone=True)
    if not item:
        return {'ok': False, 'error': 'That item is no longer in your trash.'}
    table = item['table_name']
    spec = _BY_TABLE.get(table)
    if spec is None:
        return {'ok': False, 'error': 'That kind of item can no longer be restored.'}
    try:
        row = json.loads(item['payload'])
    except Exception:
        return {'ok': False, 'error': "That item's saved copy could not be read."}

    cols = table_columns(table)
    keys = [k for k in row if (not cols or k in cols) and k != 'user_id']
    if not keys:
        return {'ok': False, 'error': 'Nothing in that item matches the current app.'}
    exists = execute(f"SELECT 1 FROM {table} WHERE id=? AND user_id=?",
                     (item['row_id'], uid), fetchone=True)
    if exists:
        # Something already occupies that id — restoring would overwrite whatever
        # is there now, which is a second silent deletion.
        return {'ok': False,
                'error': 'A record with that id already exists, so this was not '
                         'restored. Delete or rename the current one first.'}
    placeholders = ','.join('?' * (len(keys) + 1))
    with transaction():
        with savepoint() as sp:
            execute(f"INSERT INTO {table} ({','.join(keys + ['user_id'])}) "
                    f"VALUES ({placeholders})",
                    tuple([row[k] for k in keys] + [uid]))
        if not sp.ok:
            return {'ok': False, 'error': 'That item could not be put back.'}
        execute("DELETE FROM deleted_items WHERE id=? AND user_id=?", (item_id, uid))
    return {'ok': True, 'kind': item['kind'], 'label': item['label'],
            'view': spec.view}


def purge(item_id: str) -> bool:
    """Delete one trashed item for good, now."""
    uid = current_user_id()
    item = execute("SELECT * FROM deleted_items WHERE id=? AND user_id=?",
                   (item_id, uid), fetchone=True)
    if not item:
        return False
    _delete_payload_files([item])
    execute("DELETE FROM deleted_items WHERE id=? AND user_id=?", (item_id, uid),
            commit=True)
    return True


def empty_trash() -> int:
    """Everything, now. The user asked; do it properly, files included."""
    uid = current_user_id()
    items = execute("SELECT * FROM deleted_items WHERE user_id=?", (uid,),
                    fetchall=True) or []
    _delete_payload_files(items)
    execute("DELETE FROM deleted_items WHERE user_id=?", (uid,), commit=True)
    return len(items)


def purge_expired(now_iso_str: str = None) -> int:
    """Remove everything past its thirty days. Runs from the scheduler.

    Deliberately global rather than per-user: it is housekeeping for the whole
    install, and a user who never opens the app again should still have their
    deleted records actually deleted.
    """
    cutoff = now_iso_str or dt.datetime.now().isoformat()
    items = execute("SELECT * FROM deleted_items WHERE expires_at <= ?",
                    (cutoff,), fetchall=True) or []
    if not items:
        return 0
    _delete_payload_files(items)
    execute("DELETE FROM deleted_items WHERE expires_at <= ?", (cutoff,), commit=True)
    return len(items)


def payload_filenames(items) -> set:
    """Filenames referenced by trashed rows.

    A deleted record's file has to stay on disk for as long as the record can be
    restored, and the orphan sweep must not treat it as abandoned. This is what
    tells db/storage the difference.
    """
    from .storage import FILE_COLUMNS, _safe_name
    by_table = {}
    for table, col in FILE_COLUMNS:
        by_table.setdefault(table, []).append(col)
    names = set()
    for it in items:
        cols = by_table.get(it['table_name'])
        if not cols:
            continue
        try:
            row = json.loads(it['payload'])
        except Exception:
            continue
        for col in cols:
            name = _safe_name(row.get(col))
            if name:
                names.add(name)
    return names


def trashed_files(uid=None) -> set:
    """Filenames held by this user's trash (or everyone's, if uid is None)."""
    if uid:
        items = execute("SELECT * FROM deleted_items WHERE user_id=?", (uid,),
                        fetchall=True) or []
    else:
        items = execute("SELECT * FROM deleted_items", fetchall=True) or []
    return payload_filenames(items)


def _delete_payload_files(items):
    """Remove files held only by these items — never one another row still uses."""
    from .storage import live_referenced_files, delete_files
    doomed = payload_filenames(items)
    if not doomed:
        return
    # Deliberately live_referenced_files(), not all_referenced_files(): the
    # latter counts the trash, so an item could never release its own file.
    ids = {it['id'] for it in items}
    others = execute("SELECT * FROM deleted_items", fetchall=True) or []
    still_held = payload_filenames([o for o in others if o['id'] not in ids])
    delete_files(doomed - still_held - live_referenced_files())
