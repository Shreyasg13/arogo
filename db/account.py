"""
db/account.py — full personal-data export and hard account deletion.

Two rights users are entitled to (GDPR Art. 15/17, India DPDP): download
everything we hold about them, and delete their account and all associated
data for good. Both operate strictly on the calling user's own rows.
"""
from __future__ import annotations

from .core import execute, DATA_TABLES, table_columns, transaction, savepoint

# User-owned tables that aren't in DATA_TABLES, with the column that owns them.
_EXTRA_OWNED = [
    ("push_subscriptions", "user_id"),
    ("caregiver_contacts", "user_id"),
    ("family_members", "user_id"),
]

# Never write live secrets into an export file — the user owns their data, not
# their raw OAuth tokens or push keys, and an export could be mishandled.
_SECRET_KEYS = {"sub_json", "access_token", "refresh_token", "password_hash", "token"}


def _redact(row: dict) -> dict:
    for k in list(row):
        if k in _SECRET_KEYS and row[k]:
            row[k] = "[redacted]"
    return row


# User-facing categories for a SCOPED export — pick some, export only those.
# Maps the health-data tables (never account/secret meta) into groups a person
# recognises, so they can hand a doctor just labs, or share everything-but-diary.
EXPORT_CATEGORIES = [
    ('medicines', 'Medicines & doses',
     ['medicines', 'dose_logs', 'dose_snoozes', 'medicine_events', 'med_taper_steps',
      'med_effectiveness', 'injection_logs', 'action_plans']),
    ('vitals', 'Vitals & body',
     ['vitals', 'vital_targets', 'body_metrics']),
    ('labs', 'Lab results', ['lab_results', 'lab_rechecks']),
    ('symptoms', 'Symptoms & photos', ['symptoms', 'symptom_photos']),
    ('records', 'Records & care',
     ['reports', 'appointments', 'immunizations', 'prescriptions', 'allergies',
      'dental_vision_visits', 'vision_prescriptions', 'procedures', 'family_history',
      'doctor_questions', 'care_plan_items', 'providers', 'claims', 'dependents',
      'dependent_records', 'health_reminders', 'home_supplies', 'emergency_info',
      'visit_action_items', 'insurance_policies', 'health_notes']),
    ('lifestyle', 'Food, water, sleep & fitness',
     ['food_logs', 'custom_foods', 'hydration_logs', 'meal_plans', 'fitness_activities',
      'workout_sets', 'habits', 'habit_logs', 'sleep_logs', 'environment_days']),
    ('goals', 'Goals & spending',
     ['health_goals', 'fasting_sessions', 'health_expenses', 'experiments',
      'quit_plans', 'weekly_reviews', 'todos']),
    # Deleted-but-recoverable rows. Someone exporting everything before
    # switching devices would otherwise lose what is still restorable.
    ('trash', 'Trash (deleted, still recoverable)', ['deleted_items']),
    ('situational', 'Trips & illness episodes', ['travel_trips', 'illness_episodes']),
    # Not health data, but still the user's — a full export should include
    # where they were signed in and what changed about access.
    ('account', 'Sign-in & activity log', ['user_sessions', 'security_events']),
    ('private', 'Private — journal, mood, cycle, menopause, pregnancy',
     ['thoughts', 'menstrual_cycles', 'cycle_symptoms', 'menopause_logs', 'pregnancy', 'pregnancy_logs']),
]
_EXPORT_CAT_TABLES = {key: tables for key, _label, tables in EXPORT_CATEGORIES}


def export_selected_data(uid: str, category_keys) -> dict:
    """Export ONLY the tables in the chosen categories (health data only, never
    account/secret meta). Redacts secrets like the full export. Empty when no
    valid category is chosen — so a stray key can never dump everything."""
    chosen = set()
    for k in (category_keys or []):
        chosen.update(_EXPORT_CAT_TABLES.get(k, []))
    out = {'_categories': [k for k in (category_keys or []) if k in _EXPORT_CAT_TABLES]}
    for t in DATA_TABLES:
        if t not in chosen:
            continue
        try:
            rows = execute(f"SELECT * FROM {t} WHERE user_id=?", (uid,), fetchall=True) or []
            out[t] = [_redact(dict(r)) for r in rows]
        except Exception:
            out[t] = []
    return out


def export_all_data(uid: str) -> dict:
    """Every row this user owns, across every table, plus account basics."""
    out = {}
    for t in DATA_TABLES:
        try:
            rows = execute(f"SELECT * FROM {t} WHERE user_id=?", (uid,), fetchall=True) or []
            out[t] = [_redact(dict(r)) for r in rows]
        except Exception:
            out[t] = []
    for t, col in _EXTRA_OWNED:
        try:
            rows = execute(f"SELECT * FROM {t} WHERE {col}=?", (uid,), fetchall=True) or []
            out[t] = [_redact(dict(r)) for r in rows]
        except Exception:
            out[t] = []
    u = execute(
        "SELECT id, email, name, created_at, verified FROM users WHERE id=?",
        (uid,), fetchone=True)
    out["account"] = dict(u) if u else {}
    return out


# A human name for every restorable table. The restore confirmation is built
# from this, so a table without a label would be silently replaced without ever
# appearing on the screen where the user agrees to it — which is exactly what
# used to happen to 44 of them. A test asserts the coverage.
TABLE_LABELS = {
    'medicines': 'Medicines', 'dose_logs': 'Dose history',
    'dose_snoozes': 'Snoozed reminders', 'medicine_events': 'Medicine history',
    'med_taper_steps': 'Dose tapers', 'med_effectiveness': 'How medicines felt',
    'injection_logs': 'Injections', 'action_plans': 'Action plans',
    'prescriptions': 'Prescriptions',
    'vitals': 'Vitals', 'vital_targets': 'Vital targets',
    'body_metrics': 'Body measurements',
    'lab_results': 'Lab results', 'lab_rechecks': 'Lab recheck reminders',
    'symptoms': 'Symptoms', 'symptom_photos': 'Symptom photos',
    'reports': 'Medical records', 'appointments': 'Appointments',
    'immunizations': 'Vaccines', 'allergies': 'Allergies',
    'dental_vision_visits': 'Dental & vision visits',
    'vision_prescriptions': 'Glasses & lenses',
    'procedures': 'Procedures', 'family_history': 'Family history',
    'doctor_questions': 'Questions for the doctor',
    'visit_action_items': 'Visit follow-ups',
    'care_plan_items': 'Care plan', 'providers': 'Care team',
    'claims': 'Insurance claims', 'insurance_policies': 'Insurance policies',
    'dependents': 'People you care for', 'dependent_records': 'Dependent records',
    'health_reminders': 'Health reminders', 'home_supplies': 'Home supplies',
    'emergency_info': 'Emergency card', 'health_notes': 'Notes',
    'food_logs': 'Food logs', 'custom_foods': 'Your own foods',
    'hydration_logs': 'Water', 'meal_plans': 'Meal plans',
    'fitness_activities': 'Workouts', 'workout_sets': 'Strength log',
    'habits': 'Habits', 'habit_logs': 'Habit history', 'sleep_logs': 'Sleep',
    'environment_days': 'Air & weather',
    'health_goals': 'Goals', 'fasting_sessions': 'Fasting',
    'health_expenses': 'Health spending', 'experiments': 'Experiments',
    'quit_plans': 'Quit tracker', 'weekly_reviews': 'Weekly reviews',
    'todos': 'Tasks',
    'thoughts': 'Journal', 'menstrual_cycles': 'Cycle',
    'cycle_symptoms': 'Cycle symptoms', 'menopause_logs': 'Menopause',
    'pregnancy': 'Pregnancy', 'pregnancy_logs': 'Pregnancy log',
    'user_profile': 'Profile & preferences',
    'reminder_settings': 'Reminder settings',
    'measurement_reminders': 'Measurement reminders',
    'deleted_items': 'Trash',
    'travel_trips': 'Trips',
    'illness_episodes': 'Illness episodes',
    'user_sessions': 'Signed-in devices',
    'security_events': 'Account activity log',
    # Not restorable, but still named — the preview tells the user what it is
    # skipping and why, and "oauth tokens" is not a thing anyone recognises.
    'oauth_tokens': 'Connected apps', 'share_snapshots': 'Share links',
    'sync_log': 'Sync history', 'notification_log': 'Notification history',
}

# Tables a restore deliberately leaves alone, with the reason. The export
# redacts secrets, so writing these back would produce rows that look live and
# aren't — an integration that reports "connected" with no usable token, or a
# share link that resolves to nothing. Better to not restore them and say so.
NOT_RESTORED = {
    'oauth_tokens': 'the access token is redacted in a backup, so a restored row '
                    'would show a connected service that cannot actually sync — '
                    'reconnect it instead',
    'share_snapshots': 'share links carry a token that is redacted in a backup; '
                       'a restored link would never open',
    'sync_log': 'diagnostics from a previous run, not your records',
    'notification_log': 'reminders the app already sent; restoring them would '
                        'refill your notification history with old alerts',
}


def looks_like_backup(data) -> bool:
    """A permissive sanity check so a random JSON file can't be mistaken for one
    of ours: it must be an object carrying at least one known data table."""
    return isinstance(data, dict) and any(
        isinstance(data.get(t), list) for t in DATA_TABLES)


def _restorable_tables():
    return [t for t in DATA_TABLES if t not in NOT_RESTORED]


def _row_columns(row, cols):
    """The columns of `row` this schema can actually accept. Redacted secrets are
    dropped rather than written back as the literal string."""
    if not isinstance(row, dict):
        return None
    keys = [k for k, v in row.items()
            if (not cols or k in cols) and v != '[redacted]' and k != 'user_id']
    return keys or None


def preview_import(uid: str, data) -> dict:
    """Exactly what a restore would do, without doing any of it.

    The confirmation screen used to be built client-side from a list of 22 table
    names, so a restore silently replaced labs, allergies, procedures, insurance,
    notes and the cycle diary without ever naming them — and a table present but
    EMPTY in the file was hidden entirely while still deleting everything in it.
    This is the authoritative answer: every table the file touches, how many rows
    it brings, and how many of yours it would remove.
    """
    if not looks_like_backup(data):
        return {'ok': False,
                'error': "This doesn't look like an Arogo backup file."}

    meta = data.get('_backup') if isinstance(data.get('_backup'), dict) else {}
    tables, emptying, untouched, unreadable_total = [], [], [], 0
    incoming_total = deleting_total = 0

    for t in _restorable_tables():
        rows = data.get(t)
        cols = table_columns(t)
        if cols and 'user_id' not in cols:
            continue                       # not user-owned on this schema
        try:
            current = execute(f"SELECT COUNT(*) AS n FROM {t} WHERE user_id=?",
                              (uid,), fetchone=True)['n']
        except Exception:
            continue                       # table not in this schema
        if not isinstance(rows, list):
            if current:
                untouched.append({'table': t, 'label': label_for(t), 'current': current})
            continue
        usable = sum(1 for r in rows if _row_columns(r, cols))
        unreadable = len(rows) - usable
        unreadable_total += unreadable
        incoming_total += usable
        deleting_total += current
        entry = {'table': t, 'label': label_for(t), 'incoming': usable,
                 'current': current, 'unreadable': unreadable}
        tables.append(entry)
        # The quiet data-loss case: the file lists the table with nothing in it,
        # so the restore removes what you have and puts nothing back.
        if usable == 0 and current > 0:
            emptying.append(entry)

    known = set(DATA_TABLES) | {'_backup', '_categories', 'account'} | set(_EXTRA_OWNED_NAMES)
    unknown = sorted(k for k in data if k not in known)

    return {
        'ok': True,
        'error': None,
        'backup': {'app': meta.get('app'), 'version': meta.get('version')} if meta else None,
        'tables': sorted(tables, key=lambda e: -(e['incoming'] + e['current'])),
        'emptying': emptying,
        'untouched': sorted(untouched, key=lambda e: -e['current']),
        'not_restored': [{'table': t, 'label': label_for(t), 'reason': why}
                         for t, why in NOT_RESTORED.items() if isinstance(data.get(t), list)],
        'unknown_keys': unknown,
        'totals': {'incoming': incoming_total, 'deleting': deleting_total,
                   'unreadable': unreadable_total},
    }


def label_for(table: str) -> str:
    return TABLE_LABELS.get(table) or table.replace('_', ' ')


_EXTRA_OWNED_NAMES = [t for t, _ in _EXTRA_OWNED]


def import_all_data(uid: str, data: dict) -> dict:
    """Restore a backup into THIS user's rows, replacing what's there.

    Atomic. The old code deleted a table's rows and then inserted the backup's
    one autocommitted statement at a time, so a failure partway through left the
    user with neither their old data nor all of the new — the worst outcome a
    restore can produce. Everything now happens in one transaction: it either all
    lands or nothing changes.

    Safety: only health-data tables are restored (never another user's account,
    tokens, push keys or family links); every inserted row's owner is forced to
    `uid` so a snapshot can't write to someone else; columns absent from the
    current schema are dropped (version drift) and redacted secrets are skipped.

    Returns {'restored': {table: n}, 'skipped': {table: n}, 'deleted': {table: n}}
    — skipped rows are reported rather than swallowed, because "✓ Restored 3,100
    records" while 900 silently failed tells the user their history is back when
    it isn't.
    """
    if not looks_like_backup(data):
        raise ValueError("This doesn't look like an Arogo backup file.")

    # Read the schema BEFORE opening the transaction. table_columns() tries a
    # PRAGMA first and lets it fail on PostgreSQL — harmless normally, but a
    # failed statement inside a PG transaction aborts the whole thing, so doing
    # this here would have killed the restore on its very first table.
    plan = []
    for t in _restorable_tables():
        rows = data.get(t)
        if not isinstance(rows, list):
            continue
        cols = table_columns(t)
        if cols and 'user_id' not in cols:
            continue                          # not a user-owned table on this schema
        plan.append((t, rows, cols))

    # Which files this user's rows point at right now. A restore replaces those
    # rows, and the backup's rows usually name the SAME files — so the set that
    # is genuinely orphaned is only what disappears, computed after the commit.
    # Deleting all of them up front would break every record the restore brings
    # back; deleting none leaves the SD card filling with files nothing can find.
    from .storage import files_owned_by, delete_files
    files_before = files_owned_by(uid)

    restored, skipped, deleted = {}, {}, {}
    with transaction():
        for t, rows, cols in plan:
            with savepoint() as sp:
                gone = execute(f"DELETE FROM {t} WHERE user_id=?", (uid,)).rowcount
            if not sp.ok:
                continue                      # table not in this schema
            deleted[t] = gone if gone and gone > 0 else 0
            n = bad = 0
            for row in rows:
                keys = _row_columns(row, cols)
                if not keys:
                    bad += 1
                    continue
                keys = keys + ['user_id']
                vals = [row[k] for k in keys[:-1]] + [uid]   # never trust the file's owner
                ph = ','.join('?' * len(keys))
                # Each row gets its own savepoint so one malformed row is skipped
                # instead of poisoning the batch. A bare try/except would work on
                # SQLite and silently lose every remaining row on PostgreSQL.
                with savepoint() as rsp:
                    execute(f"INSERT INTO {t} ({','.join(keys)}) VALUES ({ph})", tuple(vals))
                if rsp.ok:
                    n += 1
                else:
                    bad += 1
            restored[t] = n
            if bad:
                skipped[t] = bad

    # Only after the transaction commits — a rollback must not take files with
    # it, because the rows that reference them are still there.
    orphaned = files_before - files_owned_by(uid)
    files_removed = delete_files(orphaned) if orphaned else 0

    return {'restored': restored, 'skipped': skipped, 'deleted': deleted,
            'files_removed': files_removed}


def delete_account(uid: str) -> None:
    """Hard-delete the account and everything associated with it.

    A group the user OWNS is removed entirely (its other members lose the shared
    group but keep all their own data); the user is also removed from any group
    they merely joined.

    Uploaded files go too. This used to delete rows only, so someone exercising
    their deletion right left every scan of a lab report, prescription photo and
    picture of a rash sitting in uploads/ — with the row that identified them
    gone, so nothing could ever find them again. Files are collected BEFORE the
    rows are deleted, because the rows are the only record of which files are
    theirs.
    """
    from .storage import files_owned_by, delete_files
    doomed_files = files_owned_by(uid)

    owned = execute("SELECT id FROM family_groups WHERE owner_id=?", (uid,), fetchall=True) or []
    for grp in owned:
        gid = grp["id"]
        for stmt in (
            "DELETE FROM family_members WHERE group_id=?",
            "DELETE FROM family_invites WHERE group_id=?",
            "DELETE FROM care_acks WHERE group_id=?",
            "DELETE FROM encouragements WHERE group_id=?",
            "DELETE FROM family_groups WHERE id=?",
        ):
            try:
                execute(stmt, (gid,), commit=True)
            except Exception:
                pass

    # References to this user in tables keyed by other columns
    for stmt, params in (
        ("DELETE FROM family_members WHERE user_id=?", (uid,)),
        ("DELETE FROM family_invites WHERE invited_by=?", (uid,)),
        ("DELETE FROM care_acks WHERE caregiver_user_id=? OR target_user_id=?", (uid, uid)),
        ("DELETE FROM encouragements WHERE to_user_id=? OR from_user_id=?", (uid, uid)),
        ("DELETE FROM push_subscriptions WHERE user_id=?", (uid,)),
        ("DELETE FROM caregiver_contacts WHERE user_id=?", (uid,)),
    ):
        try:
            execute(stmt, params, commit=True)
        except Exception:
            pass

    for t in DATA_TABLES:
        try:
            execute(f"DELETE FROM {t} WHERE user_id=?", (uid,), commit=True)
        except Exception:
            pass

    # Last, so a failure while deleting rows doesn't destroy files that are
    # still referenced by rows which survived.
    delete_files(doomed_files)

    execute("DELETE FROM users WHERE id=?", (uid,), commit=True)
