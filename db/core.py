"""
db/core.py — Database connection, schema, and helpers.

Backends:
  - SQLite (default): medeasy.db in the repo root, or MEDEASY_DB env override.
  - PostgreSQL: set DATABASE_URL=postgresql://user:pass@host:5432/dbname
    (needs psycopg2-binary). All SQL in this codebase sticks to the portable
    subset both engines accept; execute() rewrites '?' placeholders to '%s'
    for Postgres.
"""
import os, json, datetime, uuid, threading

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
    refill_threshold INTEGER DEFAULT 7
);
CREATE TABLE IF NOT EXISTS dose_logs (
    id TEXT PRIMARY KEY, medicine_id TEXT NOT NULL,
    date_key TEXT NOT NULL, time_key TEXT NOT NULL,
    taken INTEGER DEFAULT 0, taken_at TEXT DEFAULT NULL
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
    id TEXT PRIMARY KEY, service TEXT NOT NULL, status TEXT NOT NULL,
    activities_synced INTEGER DEFAULT 0, error TEXT DEFAULT '', synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_profile (
    id TEXT PRIMARY KEY, name TEXT DEFAULT '',
    weight_kg REAL DEFAULT NULL, height_cm REAL DEFAULT NULL,
    age INTEGER DEFAULT NULL, gender TEXT DEFAULT NULL,
    activity_level TEXT DEFAULT NULL, goal TEXT DEFAULT NULL,
    target_weight_kg REAL DEFAULT NULL,
    timezone TEXT DEFAULT NULL,
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
    fat REAL DEFAULT 0, fiber REAL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thoughts (
    id TEXT PRIMARY KEY, content TEXT NOT NULL, mood TEXT DEFAULT 'neutral',
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
    drink_type TEXT DEFAULT 'water', date_key TEXT NOT NULL, logged_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS vitals (
    id TEXT PRIMARY KEY, date_key TEXT NOT NULL, type TEXT NOT NULL,
    value1 REAL NOT NULL, value2 REAL DEFAULT NULL,
    unit TEXT DEFAULT '', notes TEXT DEFAULT '', logged_at TEXT NOT NULL
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
    updated_at TEXT NOT NULL
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


def migrate_add_token_version():
    """users.token_version — bumped to revoke all of a user's sessions."""
    try:
        execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
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
        'user_profile', 'oauth_tokens',
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
    'user_profile', 'oauth_tokens',
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
    migrate_add_token_version()
    migrate_claim_default_data()
    print(f"[DB] Ready — {'PostgreSQL' if IS_POSTGRES else DB_PATH}")