"""
db/account.py — full personal-data export and hard account deletion.

Two rights users are entitled to (GDPR Art. 15/17, India DPDP): download
everything we hold about them, and delete their account and all associated
data for good. Both operate strictly on the calling user's own rows.
"""
from __future__ import annotations

from .core import execute, DATA_TABLES, table_columns

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
      'dependent_records', 'health_reminders', 'home_supplies', 'emergency_info']),
    ('lifestyle', 'Food, water, sleep & fitness',
     ['food_logs', 'custom_foods', 'hydration_logs', 'meal_plans', 'fitness_activities',
      'workout_sets', 'habits', 'habit_logs', 'sleep_logs']),
    ('goals', 'Goals & spending', ['health_goals', 'fasting_sessions', 'health_expenses']),
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


def looks_like_backup(data) -> bool:
    """A permissive sanity check so a random JSON file can't be mistaken for one
    of ours: it must be an object carrying at least one known data table."""
    return isinstance(data, dict) and any(
        isinstance(data.get(t), list) for t in DATA_TABLES)


def import_all_data(uid: str, data: dict) -> dict:
    """Restore a backup into THIS user's rows, replacing what's there.

    Safety: only the health-data tables are restored (never another user's
    account, tokens, push keys, or family links); every inserted row's owner is
    forced to `uid` so a snapshot can't write to someone else; columns not in the
    current schema are dropped (version drift) and redacted secrets are skipped.
    Returns {table: rows_restored}. Caller is responsible for confirming intent —
    this overwrites existing data.
    """
    if not looks_like_backup(data):
        raise ValueError("This doesn't look like an Arogo backup file.")
    summary = {}
    for t in DATA_TABLES:
        rows = data.get(t)
        if not isinstance(rows, list):
            continue
        cols = table_columns(t)
        if cols and "user_id" not in cols:
            continue                          # not a user-owned table on this schema
        execute(f"DELETE FROM {t} WHERE user_id=?", (uid,), commit=True)
        n = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            clean = {k: v for k, v in row.items()
                     if (not cols or k in cols) and v != "[redacted]"}
            clean["user_id"] = uid            # never trust the snapshot's owner
            keys = [k for k in clean if not cols or k in cols]
            if not keys:
                continue
            ph = ",".join("?" * len(keys))
            try:
                execute(f"INSERT INTO {t} ({','.join(keys)}) VALUES ({ph})",
                        tuple(clean[k] for k in keys), commit=True)
                n += 1
            except Exception:
                pass                          # skip a malformed row, keep going
        summary[t] = n
    return summary


def delete_account(uid: str) -> None:
    """Hard-delete the account and everything associated with it.

    A group the user OWNS is removed entirely (its other members lose the shared
    group but keep all their own data); the user is also removed from any group
    they merely joined.
    """
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

    execute("DELETE FROM users WHERE id=?", (uid,), commit=True)
