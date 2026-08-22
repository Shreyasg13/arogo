"""
db/core.py — Database connection, schema, and helpers.

Backends:
  - SQLite (default): medeasy.db in the repo root, or MEDEASY_DB env override.
  - PostgreSQL: set DATABASE_URL=postgresql://user:pass@host:5432/dbname
    (needs psycopg2-binary). All SQL in this codebase sticks to the portable
    subset both engines accept; execute() rewrites '?' placeholders to '%s'
    for Postgres.
"""
import os, json, math, datetime, uuid, threading


# ── Safe numeric coercion ─────────────────────────────────────────────────────
# Routes historically fed request JSON straight into int()/float(), so a
# non-numeric, NaN, Infinity, or wrong-type value 500'd the endpoint or stored
# poison that corrupted every downstream view. Use these at every boundary.

def to_num(v, default=0.0, lo=None, hi=None):
    """Coerce to a finite float. Non-numeric / NaN / Infinity → default.
    Optionally clamp to [lo, hi]."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None if default is None else float(default)
    if not math.isfinite(n):
        return None if default is None else float(default)
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def to_int(v, default=0, lo=None, hi=None):
    """Safe int via to_num (handles '3', 3.0, None, 'abc', NaN, inf). When
    default is None, an unparseable/missing value returns None (not a crash and
    not a fabricated 0) — callers that want a real optional integer pass None."""
    n = to_num(v, default, lo, hi)
    return None if n is None else int(n)


def valid_date(v):
    """True if `v` is a real ISO (YYYY-MM-DD) calendar date. Used to reject
    garbage date_keys before they orphan a log on a non-navigable day."""
    if not isinstance(v, str):
        return False
    try:
        datetime.date.fromisoformat(v)
        return True
    except ValueError:
        return False

# ── Backend selection ─────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.environ.get("MEDEASY_DB", os.path.join(ROOT_DIR, "medeasy.db"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_POSTGRES  = DATABASE_URL.startswith(("postgres://", "postgresql://"))

# ── Connection ────────────────────────────────────────────────────────────────
_conn  = None
_mutex = threading.Lock()


def _connect_sqlite():
    import sqlite3
    # Remove stale WAL/SHM files left by a crashed session.
    # On Windows NTFS (/mnt/d/...) these cause "locking protocol" errors.
    for ext in ("-wal", "-shm"):
        stale = DB_PATH + ext
        if os.path.exists(stale):
            try:
                os.remove(stale)
            except OSError:
                pass

    # isolation_level=None → autocommit mode.
    # SQLite never opens an implicit write transaction that stays open
    # between calls, which is what causes locking errors on NTFS mounts.
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _connect_postgres():
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(DATABASE_URL,
                            cursor_factory=psycopg2.extras.RealDictCursor)
    # Autocommit matches the SQLite setup above, and keeps a failed ALTER in
    # the idempotent migrations from aborting the whole connection.
    conn.autocommit = True
    return conn


def get_db():
    global _conn
    with _mutex:
        if _conn is None:
            _conn = _connect_postgres() if IS_POSTGRES else _connect_sqlite()
        return _conn


# ── Query helper ──────────────────────────────────────────────────────────────
def _adapt(sql: str) -> str:
    # No SQL in this codebase contains a literal '?', so plain replace is safe.
    return sql.replace("?", "%s") if IS_POSTGRES else sql


def execute(sql: str, params=(), *, fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    if IS_POSTGRES:
        cur = conn.cursor()
        # psycopg2 %-formats the SQL only when params is not None
        cur.execute(_adapt(sql), tuple(params) if params else None)
    else:
        cur = conn.execute(sql, params)
    # commit kwarg kept for API compatibility; in autocommit mode every
    # statement commits itself, so this is a no-op but harmless.
    if fetchone:
        row = cur.fetchone()
        return dict(row) if row else None
    if fetchall:
        return [dict(r) for r in cur.fetchall()]
    return cur


def executemany(sql: str, param_list):
    conn = get_db()
    if IS_POSTGRES:
        conn.cursor().executemany(_adapt(sql), [tuple(p) for p in param_list])
    else:
        conn.executemany(sql, param_list)


def commit():
    # No-op in autocommit mode — kept so existing callers don't break.
    pass


# ── Tiny helpers ──────────────────────────────────────────────────────────────
def jdump(v): return json.dumps(v)

def jload(v, default=None):
    try:   return json.loads(v) if v else ([] if default is None else default)
    except Exception: return [] if default is None else default

_user_override = threading.local()


def user_context(uid: str):
    """Context manager: run scoped DB calls as `uid` outside a request.

    Used by background jobs (scheduler, OAuth sync) to iterate users:

        with user_context(row['user_id']):
            get_today_doses()   # scoped to that user
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        prev = getattr(_user_override, 'uid', None)
        _user_override.uid = uid
        try:
            yield
        finally:
            _user_override.uid = prev
    return _ctx()


def current_user_id() -> str:
    """
    Return the user id for the current scoped operation.

    Priority: explicit user_context() override (background jobs) →
    flask.g.user_id (set by @require_auth) → 'default' (legacy CLI use).
    """
    uid = getattr(_user_override, 'uid', None)
    if uid:
        return uid
    try:
        from flask import g, has_request_context
        if has_request_context():
            uid = getattr(g, 'user_id', None)
            if uid:
                return uid
    except Exception:
        pass
    return 'default'


def table_columns(t: str) -> set:
    """Column names for a table — the one place PRAGMA lives. Uses SQLite's
    PRAGMA, falling back to information_schema on PostgreSQL; empty set if
    unknown (callers treat that as 'don't filter')."""
    try:
        rows = execute(f"PRAGMA table_info({t})", fetchall=True) or []
        if rows:
            return {r["name"] for r in rows}
    except Exception:
        pass
    try:
        rows = execute("SELECT column_name FROM information_schema.columns WHERE table_name=?",
                       (t,), fetchall=True) or []
        return {r["column_name"] for r in rows}
    except Exception:
        return set()


def now_iso():   return datetime.datetime.now().isoformat()
def today_iso(tz: str = None) -> str:
    """Return today's date in YYYY-MM-DD format, respecting timezone."""
    try:
        if tz:
            import zoneinfo
            zone = zoneinfo.ZoneInfo(tz)
            return datetime.datetime.now(zone).date().isoformat()
    except Exception:
        pass
    return datetime.date.today().isoformat()


def user_today() -> str:
    """Today in the USER's timezone — the only "today" that should ever decide
    whether a dose is due, late, or missed.

    The browser and the service worker both key writes off the device's local
    day (`localToday()` / `toLocaleDateString('en-CA')`). Anything server-side
    that reads those rows back has to agree, or the two silently disagree at
    the edges of the day: a user in IST taps "✓ Taken" at 00:30, the row is
    written under tomorrow's date, and a server on UTC still sees the dose as
    unlogged — then escalates it to their family as missed.

    Falls back to the server's date when no timezone is known, which is the
    old behaviour and correct for a user who never set one.
    """
    try:
        from .food import get_user_timezone
        return today_iso(get_user_timezone())
    except Exception:
        return today_iso()


def new_id():    return uuid.uuid4().hex


# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    name        TEXT DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    verified    INTEGER DEFAULT 0,
    verify_token TEXT DEFAULT NULL,
    token_version INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    last_login  TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL, original_name TEXT DEFAULT '',
    patient_name TEXT DEFAULT '', report_type TEXT DEFAULT '',
    report_date TEXT DEFAULT '', upload_date TEXT NOT NULL,
    tags TEXT DEFAULT '[]', analysis_notes TEXT DEFAULT '',
    severity TEXT DEFAULT 'normal', doctor TEXT DEFAULT '', file_ext TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS medicines (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, dosage TEXT DEFAULT '',
    unit TEXT DEFAULT 'mg', frequency TEXT DEFAULT 'once_daily',
    times TEXT DEFAULT '["09:00"]', with_food INTEGER DEFAULT 0,
    notes TEXT DEFAULT '', color TEXT DEFAULT 'teal', icon TEXT DEFAULT '💊',
    start_date TEXT DEFAULT '', end_date TEXT DEFAULT '',
    active INTEGER DEFAULT 1, created_at TEXT NOT NULL,
    pill_count INTEGER DEFAULT NULL, pills_per_dose INTEGER DEFAULT 1,
    refill_threshold INTEGER DEFAULT 7,
    refill_status TEXT DEFAULT NULL, refill_ordered_at TEXT DEFAULT NULL,
    pharmacy_note TEXT DEFAULT '',
    purpose TEXT DEFAULT '',
    timing TEXT DEFAULT '',
    reminder_lead_min INTEGER DEFAULT 0,
    cost REAL DEFAULT NULL,
    schedule_days TEXT DEFAULT NULL,
    interval_days INTEGER DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS dose_logs (
    id TEXT PRIMARY KEY, medicine_id TEXT NOT NULL,
    date_key TEXT NOT NULL, time_key TEXT NOT NULL,
    taken INTEGER DEFAULT 0, taken_at TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS medicine_events (
    id TEXT PRIMARY KEY, medicine_id TEXT NOT NULL, med_name TEXT DEFAULT '',
    kind TEXT NOT NULL, detail TEXT DEFAULT '', at TEXT NOT NULL,
    user_id TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS menstrual_cycles (
    id TEXT PRIMARY KEY, start_date TEXT NOT NULL, end_date TEXT DEFAULT NULL,
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cycle_symptoms (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL, symptoms TEXT DEFAULT NULL,
    flow TEXT DEFAULT NULL, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fitness_activities (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT DEFAULT '',
    date TEXT NOT NULL, duration INTEGER DEFAULT 0, distance REAL DEFAULT 0,
    calories INTEGER DEFAULT 0, heart_rate_avg INTEGER DEFAULT 0,
    heart_rate_max INTEGER DEFAULT 0, steps INTEGER DEFAULT 0,
    elevation REAL DEFAULT 0, notes TEXT DEFAULT '',
    source TEXT DEFAULT 'manual', external_id TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id TEXT PRIMARY KEY, service TEXT NOT NULL, access_token TEXT NOT NULL,
    refresh_token TEXT DEFAULT '', token_type TEXT DEFAULT 'Bearer',
    expires_at TEXT DEFAULT '', scope TEXT DEFAULT '',
    athlete_id TEXT DEFAULT '', athlete_name TEXT DEFAULT '',
    connected_at TEXT NOT NULL, last_sync TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sync_log (
    id TEXT PRIMARY KEY, service TEXT NOT NULL, synced_at TEXT NOT NULL,
    status TEXT NOT NULL, count INTEGER DEFAULT 0, message TEXT DEFAULT '',
    user_id TEXT NOT NULL DEFAULT 'default'
);
CREATE TABLE IF NOT EXISTS user_profile (
    id TEXT PRIMARY KEY, name TEXT DEFAULT '',
    weight_kg REAL DEFAULT NULL, height_cm REAL DEFAULT NULL,
    age INTEGER DEFAULT NULL, gender TEXT DEFAULT NULL,
    activity_level TEXT DEFAULT NULL, goal TEXT DEFAULT NULL,
    target_weight_kg REAL DEFAULT NULL,
    timezone TEXT DEFAULT NULL,
    diet_pref TEXT DEFAULT NULL,
    ui_mode TEXT DEFAULT NULL,
    language TEXT DEFAULT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_logs (
    id TEXT PRIMARY KEY, food_id TEXT DEFAULT '', food_name TEXT NOT NULL,
    meal_type TEXT DEFAULT 'lunch', date_key TEXT NOT NULL,
    quantity_g REAL DEFAULT 100, calories REAL DEFAULT 0,
    protein REAL DEFAULT 0, carbs REAL DEFAULT 0, fat REAL DEFAULT 0,
    fiber REAL DEFAULT 0, sugar REAL DEFAULT 0, sodium REAL DEFAULT 0,
    nutrients TEXT DEFAULT '{}', logged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_foods (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT DEFAULT 'Custom',
    emoji TEXT DEFAULT '🍽️', serving_g REAL DEFAULT 100,
    calories REAL DEFAULT 0, protein REAL DEFAULT 0, carbs REAL DEFAULT 0,
    fat REAL DEFAULT 0, fiber REAL DEFAULT 0,
    sugar REAL DEFAULT 0, sodium REAL DEFAULT 0, barcode TEXT DEFAULT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thoughts (
    id TEXT PRIMARY KEY, content TEXT NOT NULL, mood TEXT DEFAULT 'neutral',
    triggers TEXT DEFAULT NULL,
    date_key TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT DEFAULT '',
    priority TEXT DEFAULT 'medium', status TEXT DEFAULT 'pending',
    due_date TEXT DEFAULT NULL, reminder_at TEXT DEFAULT NULL,
    reminder_sent INTEGER DEFAULT 0, tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL, completed_at TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS hydration_logs (
    id TEXT PRIMARY KEY, amount_ml INTEGER NOT NULL,
    drink_type TEXT DEFAULT 'water', date_key TEXT NOT NULL, logged_at TEXT NOT NULL,
    source_id TEXT
);
CREATE TABLE IF NOT EXISTS sleep_logs (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL, bedtime TEXT NOT NULL,
    wake_time TEXT NOT NULL, duration_h REAL NOT NULL,
    quality INTEGER DEFAULT 3, notes TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS body_metrics (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL,
    weight_kg REAL DEFAULT NULL, body_fat_pct REAL DEFAULT NULL,
    waist_cm REAL DEFAULT NULL, bmi REAL DEFAULT NULL,
    notes TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS habits (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, emoji TEXT DEFAULT '⭐',
    category TEXT DEFAULT 'general', target_days TEXT DEFAULT '[]',
    color TEXT DEFAULT '#0E8F7E', active INTEGER DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS habit_logs (
    id TEXT PRIMARY KEY, habit_id TEXT NOT NULL,
    date_key TEXT NOT NULL, done INTEGER DEFAULT 1, logged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS symptoms (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, severity INTEGER DEFAULT 5,
    date_key TEXT NOT NULL, time_of_day TEXT DEFAULT 'evening',
    notes TEXT DEFAULT '', logged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT DEFAULT 'doctor',      -- doctor | lab | vaccine | other
    date TEXT NOT NULL,              -- YYYY-MM-DD
    time TEXT DEFAULT '',            -- HH:MM or ''
    location TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    remind INTEGER DEFAULT 1,
    reminder_days INTEGER DEFAULT 1,
    provider_id TEXT DEFAULT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS doctor_questions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    asked INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dose_snoozes (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
    med_id TEXT NOT NULL, date_key TEXT NOT NULL, time_key TEXT NOT NULL,
    snooze_until TEXT NOT NULL,      -- server-time ISO (a snooze is a relative delay)
    notified INTEGER DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS measurement_reminders (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
    kind TEXT NOT NULL,             -- blood_pressure | blood_sugar | weight | spo2 | temperature | heart_rate
    time TEXT NOT NULL,             -- HH:MM
    enabled INTEGER DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vitals (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL, type TEXT NOT NULL,
    value1 REAL NOT NULL, value2 REAL DEFAULT NULL,
    unit TEXT DEFAULT '', notes TEXT DEFAULT '', logged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_results (
    id TEXT PRIMARY KEY, lab_key TEXT NOT NULL, name TEXT NOT NULL,
    value REAL NOT NULL, unit TEXT DEFAULT '', date_key TEXT NOT NULL,
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_expenses (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL, category TEXT NOT NULL,
    description TEXT DEFAULT '', amount REAL NOT NULL, covered REAL DEFAULT 0,
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS immunizations (
    id TEXT PRIMARY KEY, vaccine_key TEXT NOT NULL, name TEXT NOT NULL,
    dose_label TEXT DEFAULT '', date_given TEXT NOT NULL, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dental_vision_visits (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, visit_date TEXT NOT NULL,
    provider TEXT DEFAULT '', summary TEXT DEFAULT '', next_due TEXT DEFAULT NULL,
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS family_history (
    id TEXT PRIMARY KEY, relation TEXT DEFAULT 'other', condition TEXT NOT NULL,
    age_at_onset INTEGER DEFAULT NULL, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_reminders (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, due_date TEXT NOT NULL,
    repeat_days INTEGER DEFAULT NULL, notes TEXT DEFAULT '', done INTEGER DEFAULT 0,
    last_done TEXT DEFAULT NULL, created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS procedures (
    id TEXT PRIMARY KEY, kind TEXT DEFAULT 'procedure', name TEXT NOT NULL,
    date_key TEXT NOT NULL, end_date TEXT DEFAULT NULL, provider TEXT DEFAULT '',
    location TEXT DEFAULT '', notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quit_plans (
    id TEXT PRIMARY KEY, kind TEXT DEFAULT 'other', label TEXT DEFAULT '',
    quit_date TEXT NOT NULL, baseline_per_day REAL DEFAULT NULL,
    unit_cost REAL DEFAULT NULL, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menopause_logs (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL, hot_flashes INTEGER DEFAULT 0,
    night_sweats INTEGER DEFAULT 0, sleep INTEGER DEFAULT 0, mood INTEGER DEFAULT 0,
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pregnancy (
    id TEXT PRIMARY KEY, lmp_date TEXT DEFAULT NULL, due_date TEXT DEFAULT NULL,
    active INTEGER DEFAULT 1, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pregnancy_logs (
    id TEXT PRIMARY KEY, pregnancy_id TEXT NOT NULL, date_key TEXT NOT NULL,
    weight_kg REAL DEFAULT NULL, kicks INTEGER DEFAULT NULL, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS symptom_photos (
    id TEXT PRIMARY KEY, label TEXT DEFAULT '', filename TEXT NOT NULL,
    taken_date TEXT NOT NULL, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS home_supplies (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT DEFAULT 'other',
    quantity INTEGER DEFAULT 0, unit TEXT DEFAULT '', expiry_date TEXT DEFAULT NULL,
    low_at INTEGER DEFAULT 0, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vision_prescriptions (
    id TEXT PRIMARY KEY, rx_date TEXT NOT NULL, kind TEXT DEFAULT 'glasses',
    right_sph TEXT DEFAULT '', right_cyl TEXT DEFAULT '', right_axis TEXT DEFAULT '', right_add TEXT DEFAULT '',
    left_sph TEXT DEFAULT '', left_cyl TEXT DEFAULT '', left_axis TEXT DEFAULT '', left_add TEXT DEFAULT '',
    pd TEXT DEFAULT '', notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_goals (
    id TEXT PRIMARY KEY, title TEXT DEFAULT '', metric TEXT NOT NULL,
    target_value REAL NOT NULL, direction TEXT DEFAULT 'below',
    start_value REAL DEFAULT NULL, deadline TEXT DEFAULT NULL,
    status TEXT DEFAULT 'active', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fasting_sessions (
    id TEXT PRIMARY KEY, start_at TEXT NOT NULL, end_at TEXT DEFAULT NULL,
    target_hours REAL DEFAULT 16, status TEXT DEFAULT 'active',
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS care_plan_items (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, detail TEXT DEFAULT '',
    category TEXT DEFAULT 'other', owner TEXT DEFAULT 'me',
    status TEXT DEFAULT 'active', review_date TEXT DEFAULT NULL,
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, specialty TEXT DEFAULT '',
    phone TEXT DEFAULT '', clinic TEXT DEFAULT '', address TEXT DEFAULT '',
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visit_action_items (
    id TEXT PRIMARY KEY, appointment_id TEXT NOT NULL, text TEXT NOT NULL,
    done INTEGER DEFAULT 0, created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_reviews (
    id TEXT PRIMARY KEY, week_start TEXT NOT NULL, wins TEXT DEFAULT '',
    focus TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, metric TEXT NOT NULL,
    start_date TEXT NOT NULL, baseline_days INTEGER DEFAULT 14,
    status TEXT DEFAULT 'active', end_date TEXT DEFAULT NULL,
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insurance_policies (
    id TEXT PRIMARY KEY, insurer TEXT NOT NULL, policy_no TEXT DEFAULT '',
    kind TEXT DEFAULT 'health', cover_amount REAL DEFAULT NULL,
    premium REAL DEFAULT NULL, premium_period TEXT DEFAULT 'year',
    start_date TEXT DEFAULT NULL, renewal_date TEXT DEFAULT NULL,
    members TEXT DEFAULT '', notes TEXT DEFAULT '', active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS environment_days (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL, aqi REAL DEFAULT NULL,
    temp_c REAL DEFAULT NULL, humidity REAL DEFAULT NULL,
    source TEXT DEFAULT 'import', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_rechecks (
    id TEXT PRIMARY KEY, lab_key TEXT NOT NULL, interval_days INTEGER DEFAULT 180,
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prescriptions (
    id TEXT PRIMARY KEY, prescriber TEXT DEFAULT '', date_issued TEXT NOT NULL,
    valid_until TEXT DEFAULT NULL, refills_left INTEGER DEFAULT NULL,
    medicine_ids TEXT DEFAULT '[]', notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY, insurer TEXT NOT NULL, amount REAL NOT NULL,
    date_submitted TEXT NOT NULL, status TEXT DEFAULT 'submitted',
    reimbursed REAL DEFAULT 0, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS allergies (
    id TEXT PRIMARY KEY, allergen TEXT NOT NULL, reaction TEXT DEFAULT '',
    severity TEXT DEFAULT 'moderate', date_noted TEXT DEFAULT NULL,
    notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meal_plans (
    id TEXT PRIMARY KEY, date TEXT NOT NULL, meal_type TEXT DEFAULT 'lunch',
    item TEXT NOT NULL, quantity REAL DEFAULT NULL, unit TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS med_taper_steps (
    id TEXT PRIMARY KEY, medicine_id TEXT NOT NULL, dosage TEXT NOT NULL,
    start_date TEXT NOT NULL, note TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vital_targets (
    id TEXT PRIMARY KEY, vtype TEXT NOT NULL,
    target_min REAL DEFAULT NULL, target_max REAL DEFAULT NULL,
    updated_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dependents (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, relationship TEXT DEFAULT 'other',
    birthdate TEXT DEFAULT NULL, notes TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dependent_records (
    id TEXT PRIMARY KEY, dependent_id TEXT NOT NULL, kind TEXT NOT NULL,
    label TEXT NOT NULL, detail TEXT DEFAULT '', date_key TEXT DEFAULT '',
    created_at TEXT NOT NULL, user_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emergency_info (
    id TEXT PRIMARY KEY, blood_type TEXT DEFAULT '', allergies TEXT DEFAULT '',
    conditions TEXT DEFAULT '', medications TEXT DEFAULT '',
    contact1_name TEXT DEFAULT '', contact1_phone TEXT DEFAULT '',
    contact2_name TEXT DEFAULT '', contact2_phone TEXT DEFAULT '',
    insurance_provider TEXT DEFAULT '', insurance_number TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_log (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL,
    body TEXT DEFAULT '', source_id TEXT DEFAULT NULL,
    read INTEGER DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id TEXT PRIMARY KEY,
    endpoint TEXT UNIQUE NOT NULL,
    sub_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'default'
);
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_attempts (
    ip TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_attempts_ip ON auth_attempts(ip);
CREATE TABLE IF NOT EXISTS family_groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT 'My Family',
    owner_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS family_members (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT DEFAULT 'member',
    share_sleep INTEGER DEFAULT 0,
    share_vitals INTEGER DEFAULT 0,
    share_medicines INTEGER DEFAULT 0,
    share_food INTEGER DEFAULT 0,
    share_symptoms INTEGER DEFAULT 0,
    share_emergency INTEGER DEFAULT 0,
    alert_missed_doses INTEGER NOT NULL DEFAULT 0,
    receive_care_alerts INTEGER NOT NULL DEFAULT 1,
    allow_family_display INTEGER NOT NULL DEFAULT 0,
    allow_manage INTEGER NOT NULL DEFAULT 0,
    joined_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS family_invites (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    email TEXT NOT NULL,
    invited_by TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS care_acks (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    caregiver_user_id TEXT NOT NULL,
    caregiver_name TEXT,
    date_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS encouragements (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    to_user_id TEXT NOT NULL,
    from_user_id TEXT NOT NULL,
    from_name TEXT,
    emoji TEXT,
    message TEXT,
    kind TEXT DEFAULT 'kudos',
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminder_settings (
    id TEXT PRIMARY KEY,
    water_enabled INTEGER DEFAULT 1,
    water_interval_h REAL DEFAULT 2.0,
    water_start TEXT DEFAULT '08:00',
    water_end TEXT DEFAULT '21:00',
    water_goal_ml INTEGER DEFAULT 2450,
    habit_reminder_enabled INTEGER DEFAULT 1,
    habit_reminder_time TEXT DEFAULT '20:00',
    sleep_reminder_enabled INTEGER DEFAULT 1,
    sleep_reminder_time TEXT DEFAULT '22:00',
    mood_reminder_enabled INTEGER DEFAULT 1,
    mood_reminder_time TEXT DEFAULT '18:00',
    weekly_digest_enabled INTEGER NOT NULL DEFAULT 1,
    caregiver_digest_enabled INTEGER NOT NULL DEFAULT 1,
    quiet_enabled INTEGER DEFAULT 0,
    quiet_start TEXT DEFAULT '22:00',
    quiet_end TEXT DEFAULT '07:00',
    low_key INTEGER DEFAULT 0,
    default_snooze_min INTEGER DEFAULT 10,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS caregiver_contacts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'sms',
    alerts_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""




def migrate_fix_profile_defaults():
    """
    Drop the old user_profile table with hardcoded defaults and recreate with NULL defaults.
    Safe to run multiple times — checks if migration is needed first.
    """
    if IS_POSTGRES:
        return  # PRAGMA-based fix for legacy SQLite files; PG schemas start correct
    conn = get_db()
    # Check if weight_kg still has old default of 70
    cols = conn.execute('PRAGMA table_info(user_profile)').fetchall()
    col_map = {c[1]: c[4] for c in cols}  # name -> dflt_value
    if col_map.get('weight_kg') != 'NULL' and col_map.get('weight_kg') != None:
        # Back up existing rows
        rows = conn.execute('SELECT * FROM user_profile').fetchall()
        # Drop and recreate
        conn.execute('DROP TABLE IF EXISTS user_profile_old')
        conn.execute('ALTER TABLE user_profile RENAME TO user_profile_old')
        conn.execute("""
            CREATE TABLE user_profile (
                id TEXT PRIMARY KEY, name TEXT DEFAULT '',
                weight_kg REAL DEFAULT NULL, height_cm REAL DEFAULT NULL,
                age INTEGER DEFAULT NULL, gender TEXT DEFAULT NULL,
                activity_level TEXT DEFAULT NULL, goal TEXT DEFAULT NULL,
                target_weight_kg REAL DEFAULT NULL,
                user_id TEXT DEFAULT 'default',
                updated_at TEXT NOT NULL
            )""")
        # Restore rows — only keep non-default rows (skip the auto-created garbage)
        for row in rows:
            try:
                conn.execute(
                    """INSERT INTO user_profile
                       (id,name,weight_kg,height_cm,age,gender,
                        activity_level,goal,target_weight_kg,user_id,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (row[0], row[1],
                     None if row[2] == 70.0 else row[2],
                     None if row[3] == 170.0 else row[3],
                     None if row[4] == 30 else row[4],
                     None if row[5] == 'male' else row[5],
                     None if row[6] == 'moderate' else row[6],
                     None if row[7] == 'maintain' else row[7],
                     row[8] if len(row) > 8 else None,
                     row[9] if len(row) > 9 else 'default',
                     row[-1])
                )
            except Exception:
                pass
        conn.execute('DROP TABLE IF EXISTS user_profile_old')

def migrate_add_timezone():
    """Add timezone column to user_profile if missing."""
    try:
        execute("ALTER TABLE user_profile ADD COLUMN timezone TEXT DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_diet_pref():
    """Add diet_pref column to user_profile if missing (veg/vegan/egg/jain/nonveg)."""
    try:
        execute("ALTER TABLE user_profile ADD COLUMN diet_pref TEXT DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_ui_mode():
    """Add ui_mode column to user_profile if missing (simple = senior/large UI)."""
    try:
        execute("ALTER TABLE user_profile ADD COLUMN ui_mode TEXT DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_language():
    """Add language column to user_profile if missing. Stores the user's chosen
    UI language ('hi'/'en'/NULL) so the headless mailer and scheduler — which have
    no browser or localStorage — can localize emails and push notifications."""
    try:
        execute("ALTER TABLE user_profile ADD COLUMN language TEXT DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_country():
    """Add country column to user_profile. Drives currency, number formatting and
    the medical-spend financial year (see db/locale_config). NULL → India default,
    so existing accounts are unchanged until they choose a country."""
    try:
        execute("ALTER TABLE user_profile ADD COLUMN country TEXT DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_unit_prefs():
    """Add display-unit preferences to user_profile. Data stays canonical (kg/cm/
    mg-dL); these only choose how it's shown/entered. NULL → the country default."""
    for col in ('weight_unit', 'height_unit', 'temp_unit', 'glucose_unit'):
        try:
            execute(f"ALTER TABLE user_profile ADD COLUMN {col} TEXT DEFAULT NULL")
        except Exception:
            pass  # already exists


def migrate_add_symptom_region():
    """Add an optional body-region tag to symptoms (I7 body-map). '' = unset /
    non-localized. Validated against a fixed enum at the write path."""
    try:
        execute("ALTER TABLE symptoms ADD COLUMN region TEXT DEFAULT ''")
    except Exception:
        pass  # already exists


def migrate_add_medicine_expiry():
    """Add an optional expiry date to medicines (K1) — when the physical
    bottle/strip expires, distinct from running out of stock. '' = not set."""
    try:
        execute("ALTER TABLE medicines ADD COLUMN expiry_date TEXT DEFAULT ''")
    except Exception:
        pass


def migrate_add_medicine_photo():
    """Add an optional identification photo to medicines (I8). Stores the
    uploaded file's name (served through the authenticated /uploads route with an
    ownership check). '' = no photo."""
    try:
        execute("ALTER TABLE medicines ADD COLUMN photo_path TEXT DEFAULT ''")
    except Exception:
        pass  # already exists


def migrate_add_schedule_days():
    """Add schedule_days to medicines if missing. JSON list of weekday ints
    (Mon=0 … Sun=6, matching date.weekday()); NULL/empty means every day. Lets a
    medicine be due only on specific days (weekly-on-a-day, Mon/Thu, etc.) instead
    of the old behaviour where every timed med showed as due — and reminded —
    seven days a week."""
    try:
        execute("ALTER TABLE medicines ADD COLUMN schedule_days TEXT DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_interval_days():
    """Add interval_days to medicines if missing. When set (>=2), the med is due
    every N days counting from start_date (alternate-day = 2, every-3-days = 3).
    NULL means not interval-based. Mutually exclusive with schedule_days — a med
    repeats either on fixed weekdays or on an N-day cycle, never both."""
    try:
        execute("ALTER TABLE medicines ADD COLUMN interval_days INTEGER DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_family_display():
    """Add allow_family_display to family_members if missing — lets a member
    opt in to a caregiver adjusting their Simple View."""
    try:
        execute("ALTER TABLE family_members ADD COLUMN allow_family_display INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists


def migrate_add_allow_manage():
    """Add allow_manage to family_members if missing — a member's explicit opt-in
    to let fellow group members act on their behalf (log doses, add meds, etc.)
    from their own device. Off by default; the strongest family grant, so it is
    always the member's own choice."""
    try:
        execute("ALTER TABLE family_members ADD COLUMN allow_manage INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists


def migrate_add_thought_triggers():
    """Add triggers to thoughts if missing — an optional JSON list of what was
    driving a mood (exam, work, sleep…), so a young user can see their patterns."""
    try:
        execute("ALTER TABLE thoughts ADD COLUMN triggers TEXT DEFAULT NULL")
    except Exception:
        pass  # already exists


def migrate_add_low_key():
    """Add low_key to reminder_settings — a one-tap 'keep it low-key' mode that
    mutes non-essential nudges (water/habit/sleep/mood/measurements) while still
    sending safety-critical medication reminders."""
    try:
        execute("ALTER TABLE reminder_settings ADD COLUMN low_key INTEGER DEFAULT 0")
    except Exception:
        pass  # already exists


def migrate_add_refill_fields():
    """Add refill-tracking + purpose columns to medicines if missing."""
    for col, ddl in (
        ('refill_status',     "ALTER TABLE medicines ADD COLUMN refill_status TEXT DEFAULT NULL"),
        ('refill_ordered_at', "ALTER TABLE medicines ADD COLUMN refill_ordered_at TEXT DEFAULT NULL"),
        ('pharmacy_note',     "ALTER TABLE medicines ADD COLUMN pharmacy_note TEXT DEFAULT ''"),
        ('purpose',           "ALTER TABLE medicines ADD COLUMN purpose TEXT DEFAULT ''"),
    ):
        try:
            execute(ddl)
        except Exception:
            pass  # already exists


def migrate_add_quiet_hours():
    """Add do-not-disturb columns to reminder_settings."""
    for ddl in (
        "ALTER TABLE reminder_settings ADD COLUMN quiet_enabled INTEGER DEFAULT 0",
        "ALTER TABLE reminder_settings ADD COLUMN quiet_start TEXT DEFAULT '22:00'",
        "ALTER TABLE reminder_settings ADD COLUMN quiet_end TEXT DEFAULT '07:00'",
    ):
        try:
            execute(ddl)
        except Exception:
            pass


def migrate_add_advance_care():
    """M1 — advance-care / medical-wishes columns on the emergency card. These
    hold ONLY the user's own stated wishes (organ-donor status, directives, and
    where the paperwork is kept); nothing is interpreted or acted on."""
    for ddl in (
        "ALTER TABLE emergency_info ADD COLUMN organ_donor TEXT DEFAULT ''",
        "ALTER TABLE emergency_info ADD COLUMN directive_wishes TEXT DEFAULT ''",
        "ALTER TABLE emergency_info ADD COLUMN directive_location TEXT DEFAULT ''",
    ):
        try:
            execute(ddl)
        except Exception:
            pass


def migrate_add_reminder_lead():
    """Add the per-medicine reminder lead-time column."""
    try:
        execute("ALTER TABLE medicines ADD COLUMN reminder_lead_min INTEGER DEFAULT 0")
    except Exception:
        pass


def migrate_add_default_snooze():
    """Add the account-wide default snooze length to reminder_settings."""
    try:
        execute("ALTER TABLE reminder_settings ADD COLUMN default_snooze_min INTEGER DEFAULT 10")
    except Exception:
        pass


def migrate_add_care_team():
    """Create the providers directory and link appointments to a provider."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, specialty TEXT DEFAULT '',
            phone TEXT DEFAULT '', clinic TEXT DEFAULT '', address TEXT DEFAULT '',
            notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass
    try:
        execute("ALTER TABLE appointments ADD COLUMN provider_id TEXT DEFAULT NULL")
    except Exception:
        pass


def migrate_add_lab_rechecks():
    """Create the lab recheck-interval table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS lab_rechecks (
            id TEXT PRIMARY KEY, lab_key TEXT NOT NULL, interval_days INTEGER DEFAULT 180,
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_prescriptions():
    """Create the prescription library table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS prescriptions (
            id TEXT PRIMARY KEY, prescriber TEXT DEFAULT '', date_issued TEXT NOT NULL,
            valid_until TEXT DEFAULT NULL, refills_left INTEGER DEFAULT NULL,
            medicine_ids TEXT DEFAULT '[]', notes TEXT DEFAULT '',
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_appt_reminder_days():
    """Add the configurable appointment reminder lead-time column."""
    try:
        execute("ALTER TABLE appointments ADD COLUMN reminder_days INTEGER DEFAULT 1")
    except Exception:
        pass


def migrate_add_allergies():
    """Create the structured allergies table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS allergies (
            id TEXT PRIMARY KEY, allergen TEXT NOT NULL, reaction TEXT DEFAULT '',
            severity TEXT DEFAULT 'moderate', date_noted TEXT DEFAULT NULL,
            notes TEXT DEFAULT '', created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_meal_plans():
    """Create the meal-planner table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS meal_plans (
            id TEXT PRIMARY KEY, date TEXT NOT NULL, meal_type TEXT DEFAULT 'lunch',
            item TEXT NOT NULL, quantity REAL DEFAULT NULL, unit TEXT DEFAULT '',
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_med_tapers():
    """Create the medication-taper-steps table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS med_taper_steps (
            id TEXT PRIMARY KEY, medicine_id TEXT NOT NULL, dosage TEXT NOT NULL,
            start_date TEXT NOT NULL, note TEXT DEFAULT '',
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_vital_targets():
    """Create the user-defined vital-target-range table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS vital_targets (
            id TEXT PRIMARY KEY, vtype TEXT NOT NULL,
            target_min REAL DEFAULT NULL, target_max REAL DEFAULT NULL,
            updated_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_vital_context():
    """Add a meal-context tag to vitals (fasting/pre/post-meal) for the glucose logbook."""
    try:
        execute("ALTER TABLE vitals ADD COLUMN context TEXT DEFAULT ''")
    except Exception:
        pass


def migrate_add_sleep_goal():
    """Add the nightly sleep-hours target (for sleep-debt math) to reminder_settings."""
    try:
        execute("ALTER TABLE reminder_settings ADD COLUMN sleep_goal_h REAL DEFAULT NULL")
    except Exception:
        pass


def migrate_add_adherence_goal():
    """Add the monthly adherence-% target to reminder_settings (for the forecast)."""
    try:
        execute("ALTER TABLE reminder_settings ADD COLUMN adherence_goal_pct INTEGER DEFAULT NULL")
    except Exception:
        pass


def migrate_add_visit_notes():
    """Add post-visit capture to appointments (J6): what the doctor said and any
    follow-ups. Complements the pre-visit prep pack. Both are the user's own free
    text; '' until filled in."""
    for col in ('visit_summary', 'follow_up'):
        try:
            execute(f"ALTER TABLE appointments ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass


def migrate_link_questions_to_visit():
    """Let a doctor question belong to a SPECIFIC appointment (the visit-flow).
    NULL = a general 'ask at my next visit' question (the existing global list),
    so this is backward-compatible."""
    try:
        execute("ALTER TABLE doctor_questions ADD COLUMN appointment_id TEXT DEFAULT NULL")
    except Exception:
        pass


def migrate_add_med_effectiveness():
    """Create the medication effectiveness log (J5): a periodic subjective 1-5
    rating of how well a medicine seems to be working, in the patient's own view.
    A record of self-report over time — never a clinical measure."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS med_effectiveness (
            id TEXT PRIMARY KEY, medicine_id TEXT NOT NULL, rating INTEGER NOT NULL,
            date_key TEXT NOT NULL, notes TEXT DEFAULT '',
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_action_plans():
    """Create emergency action plans (J3): a titled, ordered list of steps the
    user writes down from their own doctor (anaphylaxis, asthma attack,
    hypo/hyperglycemia, etc.). Steps are stored as a JSON list. Arogo never
    supplies the medical steps — only the user (or their clinician) does."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS action_plans (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, steps TEXT DEFAULT '[]',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_injection_logs():
    """Create the injection-site log (J1). Each row is one injection at a body
    site, so the app can suggest the least-recently-used site next and help the
    user rotate. medicine_id is optional (freeform injections allowed)."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS injection_logs (
            id TEXT PRIMARY KEY, medicine_id TEXT DEFAULT NULL, site TEXT NOT NULL,
            date_key TEXT NOT NULL, notes TEXT DEFAULT '',
            logged_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_workout_sets():
    """Create the strength-training set log (exercise/reps/weight per set)."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS workout_sets (
            id TEXT PRIMARY KEY, exercise TEXT NOT NULL, exercise_key TEXT NOT NULL,
            date_key TEXT NOT NULL, reps INTEGER NOT NULL, weight REAL DEFAULT 0,
            unit TEXT DEFAULT 'kg', notes TEXT DEFAULT '',
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_body_measurements():
    """Add hip/chest/arm girths to body_metrics (waist already exists) for the
    measurement-trends view."""
    for col in ('hip_cm', 'chest_cm', 'arm_cm'):
        try:
            execute(f"ALTER TABLE body_metrics ADD COLUMN {col} REAL DEFAULT NULL")
        except Exception:
            pass


def migrate_add_pharmacy():
    """Add a default pharmacy (name + phone) to the profile for one-tap refills."""
    for stmt in ("ALTER TABLE user_profile ADD COLUMN pharmacy_name TEXT DEFAULT ''",
                 "ALTER TABLE user_profile ADD COLUMN pharmacy_phone TEXT DEFAULT ''"):
        try:
            execute(stmt)
        except Exception:
            pass


def migrate_add_condition_focus():
    """Add the condition the daily check-in is tailored for (diabetes/hypertension)."""
    try:
        execute("ALTER TABLE user_profile ADD COLUMN condition_focus TEXT DEFAULT ''")
    except Exception:
        pass


def migrate_add_dose_skip_reason():
    """Add an optional reason tag to a skipped dose (forgot / away / side-effect / out)."""
    try:
        execute("ALTER TABLE dose_logs ADD COLUMN skip_reason TEXT DEFAULT NULL")
    except Exception:
        pass


def migrate_add_share_snapshots():
    """Create the time-limited shareable health-snapshot table. A snapshot is a
    read-only, expiring, revocable public link to a SAFE subset of the user's
    data (never journal/cycle/mood)."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS share_snapshots (
            id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE, scope TEXT DEFAULT 'summary',
            label TEXT DEFAULT '', created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            revoked INTEGER DEFAULT 0, views INTEGER DEFAULT 0, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_claims():
    """Create the insurance-claims table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY, insurer TEXT NOT NULL, amount REAL NOT NULL,
            date_submitted TEXT NOT NULL, status TEXT DEFAULT 'submitted',
            reimbursed REAL DEFAULT 0, notes TEXT DEFAULT '',
            created_at TEXT NOT NULL, user_id TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_med_cost():
    """Add the per-medicine monthly-cost column."""
    try:
        execute("ALTER TABLE medicines ADD COLUMN cost REAL DEFAULT NULL")
    except Exception:
        pass


def migrate_add_doctor_questions():
    """Create the doctor-visit questions table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS doctor_questions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, question TEXT NOT NULL,
            asked INTEGER DEFAULT 0, created_at TEXT NOT NULL)""")
    except Exception:
        pass


def migrate_add_medicine_events():
    """Create the medicine-events (history) table on existing databases."""
    try:
        execute("""CREATE TABLE IF NOT EXISTS medicine_events (
            id TEXT PRIMARY KEY, medicine_id TEXT NOT NULL, med_name TEXT DEFAULT '',
            kind TEXT NOT NULL, detail TEXT DEFAULT '', at TEXT NOT NULL,
            user_id TEXT DEFAULT NULL)""")
    except Exception:
        pass


def migrate_add_dose_timing():
    """Add the per-dose timing instruction column, and seed it from the older
    with_food flag so existing 'with food' meds keep their instruction."""
    try:
        execute("ALTER TABLE medicines ADD COLUMN timing TEXT DEFAULT ''")
    except Exception:
        return  # column already exists — nothing to backfill
    try:
        execute("UPDATE medicines SET timing='with_food' "
                "WHERE with_food=1 AND (timing IS NULL OR timing='')")
    except Exception:
        pass


def migrate_add_token_version():
    """users.token_version — bumped to revoke all of a user's sessions."""
    try:
        execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists


def migrate_add_weekly_digest_flag():
    """reminder_settings.weekly_digest_enabled — Sunday email opt-out."""
    try:
        execute("ALTER TABLE reminder_settings ADD COLUMN weekly_digest_enabled INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass  # already exists


def migrate_add_caregiver_digest_flag():
    """reminder_settings.caregiver_digest_enabled — caregiver digest opt-out."""
    try:
        execute("ALTER TABLE reminder_settings ADD COLUMN caregiver_digest_enabled INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass  # already exists


def migrate_add_hydration_source():
    """hydration_logs.source_id — links a credit back to the food log that
    produced it (a logged latte), so deleting that food log removes the credit
    instead of silently inflating the day's total."""
    try:
        execute("ALTER TABLE hydration_logs ADD COLUMN source_id TEXT")
    except Exception:
        pass  # already exists


def migrate_add_dose_stock_ledger():
    """dose_logs.pills_applied — how many pills a "taken" actually removed.

    Stock used to be adjusted by ±pills_per_dose and floored at 0, which made
    the operation non-reversible at the floor: taking a dose with 0 left
    swallowed the -1, but un-taking it still added +1, inventing a pill. Round
    trips inflated too (1 pill, two doses taken then both un-taken → 2). An
    inflated count silently suppresses the low-stock refill nudge.

    Recording what we actually took means we can restore exactly that and no
    more. Existing 'taken' rows are backfilled with their medicine's
    pills_per_dose — the count those doses were charged under the old rule.
    """
    try:
        execute("ALTER TABLE dose_logs ADD COLUMN pills_applied INTEGER DEFAULT 0")
    except Exception:
        return  # column exists: already migrated, don't re-backfill
    try:
        execute("""
            UPDATE dose_logs SET pills_applied = COALESCE((
                SELECT COALESCE(m.pills_per_dose, 1) FROM medicines m
                WHERE m.id = dose_logs.medicine_id
                  AND m.user_id = dose_logs.user_id
                  AND m.pill_count IS NOT NULL
            ), 0) WHERE taken = 1
        """, commit=True)
    except Exception:
        pass


def migrate_dedupe_sleep_logs():
    """One night = one entry. Older builds inserted a fresh row every time you
    logged sleep for a date, so a night could accumulate duplicates (log_sleep
    now upserts on (user, date_key)). Collapse each existing group to its most
    recent entry; deterministic tie-break by id so it's stable if re-run."""
    try:
        rows = execute("SELECT id, user_id, date_key, created_at FROM sleep_logs",
                       fetchall=True)
    except Exception:
        return   # no sleep_logs table yet
    best = {}    # (user_id, date_key) -> (created_at, id) of the row to keep
    for r in rows:
        key  = (r['user_id'], r['date_key'])
        cand = (r['created_at'] or '', r['id'])
        if key not in best or cand > best[key]:
            best[key] = cand
    keep = {v[1] for v in best.values()}
    for r in rows:
        if r['id'] not in keep:
            try:
                execute("DELETE FROM sleep_logs WHERE id=?", (r['id'],), commit=True)
            except Exception:
                pass


def migrate_unify_spo2_type():
    """Oxygen saturation was stored under two type keys: the vitals form wrote
    'oxygen_sat' while the body-vitals chip, trend chart, family view and lab
    import all used 'spo2'. Rows under the odd key matched no config, so they
    rendered a hardcoded "Normal" badge (an 85% reading showed green) and never
    appeared in the trend chart or the caregiver's view. One key from here on."""
    try:
        execute("UPDATE vitals SET type='spo2' WHERE type='oxygen_sat'", commit=True)
    except Exception:
        pass  # fresh database: no vitals table yet


def migrate_add_caregiver_extras():
    """Later caregiving columns: emergency sharing, viewer/primary alert role,
    and an encouragement 'kind' (kudos vs thinking-of-you ping)."""
    for ddl in (
        "ALTER TABLE family_members ADD COLUMN share_emergency INTEGER DEFAULT 0",
        "ALTER TABLE family_members ADD COLUMN receive_care_alerts INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE encouragements ADD COLUMN kind TEXT DEFAULT 'kudos'",
    ):
        try:
            execute(ddl)
        except Exception:
            pass  # already exists


def migrate_add_caregiver_alerts():
    """family_members.alert_missed_doses — caregiver alert opt-in."""
    try:
        execute("ALTER TABLE family_members ADD COLUMN alert_missed_doses INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists


def migrate_add_custom_food_barcode():
    """custom_foods: barcode (scanned foods) + sugar/sodium from labels."""
    for col, ddl in [('sugar', 'REAL DEFAULT 0'), ('sodium', 'REAL DEFAULT 0'),
                     ('barcode', 'TEXT DEFAULT NULL')]:
        try:
            execute(f"ALTER TABLE custom_foods ADD COLUMN {col} {ddl}")
        except Exception:
            pass  # already exists

def migrate_add_user_id():
    """Add user_id column to all data tables. Safe to run multiple times."""
    tables = [
        'food_logs', 'custom_foods', 'thoughts', 'todos',
        'hydration_logs', 'sleep_logs', 'body_metrics',
        'habits', 'habit_logs', 'symptoms', 'vitals',
        'emergency_info', 'notification_log', 'reminder_settings',
        'fitness_activities', 'medicines', 'dose_logs', 'reports',
        'user_profile', 'oauth_tokens', 'sync_log',
    ]
    for table in tables:
        try:
            execute(
                f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
            )
        except Exception:
            pass  # Column already exists
    # Index for fast per-user queries on the most-queried tables
    for table in ['food_logs','sleep_logs','hydration_logs','habits','symptoms','vitals']:
        try:
            execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)"
            )
        except Exception:
            pass

DATA_TABLES = [
    'food_logs', 'custom_foods', 'thoughts', 'todos',
    'hydration_logs', 'sleep_logs', 'body_metrics',
    'habits', 'habit_logs', 'symptoms', 'vitals',
    'emergency_info', 'notification_log', 'reminder_settings',
    'fitness_activities', 'medicines', 'dose_logs', 'reports',
    'user_profile', 'oauth_tokens', 'sync_log', 'appointments', 'dose_snoozes',
    'measurement_reminders', 'medicine_events', 'doctor_questions',
    'menstrual_cycles',
    'cycle_symptoms',
    'lab_results',
    'health_expenses',
    'immunizations',
    'health_goals',
    'fasting_sessions',
    'care_plan_items',
    'providers',
    'lab_rechecks',
    'prescriptions',
    'claims',
    'allergies',
    'meal_plans',
    'med_taper_steps',
    'vital_targets',
    'dependents',
    'dependent_records',
    'workout_sets',
    'share_snapshots',
    'injection_logs',
    'action_plans',
    'med_effectiveness',
    'dental_vision_visits',
    'vision_prescriptions',
    'home_supplies',
    'symptom_photos',
    'family_history',
    'procedures',
    'quit_plans',
    'menopause_logs',
    'pregnancy',
    'pregnancy_logs',
    'health_reminders',
    'visit_action_items',
    'weekly_reviews',
    'experiments',
    'environment_days',
    'insurance_policies',
]


def migrate_claim_default_data():
    """
    One-time upgrade for single-user installs: if exactly one real user
    exists, assign all legacy rows (user_id='default') to that user so
    their data survives the switch to per-user isolation.
    With zero or 2+ users we can't know who owns 'default' rows, so we
    leave them untouched.
    """
    users = execute("SELECT id FROM users", fetchall=True)
    if len(users) != 1:
        return
    uid = users[0]['id']
    for table in DATA_TABLES:
        try:
            execute(
                f"UPDATE {table} SET user_id=? WHERE user_id='default'", (uid,)
            )
        except Exception:
            pass


def init_db():
    """Create all tables. Safe to call every startup — uses IF NOT EXISTS."""
    for stmt in SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            execute(stmt)
    migrate_add_user_id()
    migrate_fix_profile_defaults()
    migrate_add_timezone()
    migrate_add_diet_pref()
    migrate_add_ui_mode()
    migrate_add_language()
    migrate_add_country()
    migrate_add_unit_prefs()
    migrate_add_schedule_days()
    migrate_add_interval_days()
    migrate_add_family_display()
    migrate_add_allow_manage()
    migrate_add_thought_triggers()
    migrate_add_low_key()
    migrate_add_refill_fields()
    migrate_add_dose_timing()
    migrate_add_quiet_hours()
    migrate_add_reminder_lead()
    migrate_add_advance_care()
    migrate_add_default_snooze()
    migrate_add_care_team()
    migrate_add_lab_rechecks()
    migrate_add_symptom_region()
    migrate_add_medicine_photo()
    migrate_add_medicine_expiry()
    migrate_add_prescriptions()
    migrate_add_claims()
    migrate_add_appt_reminder_days()
    migrate_add_allergies()
    migrate_add_meal_plans()
    migrate_add_med_tapers()
    migrate_add_vital_targets()
    migrate_add_vital_context()
    migrate_add_sleep_goal()
    migrate_add_adherence_goal()
    migrate_add_workout_sets()
    migrate_add_injection_logs()
    migrate_add_action_plans()
    migrate_add_med_effectiveness()
    migrate_add_visit_notes()
    migrate_link_questions_to_visit()
    migrate_add_body_measurements()
    migrate_add_pharmacy()
    migrate_add_condition_focus()
    migrate_add_dose_skip_reason()
    migrate_add_share_snapshots()
    migrate_add_med_cost()
    migrate_add_doctor_questions()
    migrate_add_medicine_events()
    migrate_add_token_version()
    migrate_add_weekly_digest_flag()
    migrate_add_caregiver_digest_flag()
    migrate_add_caregiver_alerts()
    migrate_add_caregiver_extras()
    migrate_add_hydration_source()
    migrate_unify_spo2_type()
    migrate_add_dose_stock_ledger()
    migrate_dedupe_sleep_logs()
    migrate_add_custom_food_barcode()
    migrate_claim_default_data()
    print(f"[DB] Ready — {'PostgreSQL' if IS_POSTGRES else DB_PATH}")