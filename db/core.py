"""
db/core.py — Database connection, schema, and helpers.
"""
import os, sqlite3, json, datetime, uuid, threading

# ── Path ─────────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.environ.get("MEDISCAN_DB", os.path.join(ROOT_DIR, "mediscan.db"))

# ── Connection ────────────────────────────────────────────────────────────────
_conn  = None
_mutex = threading.Lock()


def get_db() -> sqlite3.Connection:
    global _conn
    with _mutex:
        if _conn is None:
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
            _conn = sqlite3.connect(
                DB_PATH,
                check_same_thread=False,
                isolation_level=None,
            )
            _conn.row_factory = sqlite3.Row
        return _conn


# ── Query helper ──────────────────────────────────────────────────────────────
def execute(sql: str, params=(), *, fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    cur  = conn.execute(sql, params)
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
    conn.executemany(sql, param_list)


def commit():
    # No-op in autocommit mode — kept so existing callers don't break.
    pass


# ── Tiny helpers ──────────────────────────────────────────────────────────────
def jdump(v): return json.dumps(v)

def jload(v, default=None):
    try:   return json.loads(v) if v else ([] if default is None else default)
    except Exception: return [] if default is None else default

def now_iso():   return datetime.datetime.now().isoformat()
def today_iso(): return datetime.date.today().isoformat()
def new_id():    return uuid.uuid4().hex


# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE, created_at TEXT NOT NULL
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
    id TEXT PRIMARY KEY, name TEXT DEFAULT '', weight_kg REAL DEFAULT 70,
    height_cm REAL DEFAULT 170, age INTEGER DEFAULT 30, gender TEXT DEFAULT 'male',
    activity_level TEXT DEFAULT 'moderate', goal TEXT DEFAULT 'maintain',
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
"""


def init_db():
    """Create all tables. Safe to call every startup — uses IF NOT EXISTS."""
    conn = get_db()
    for stmt in SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    print(f"[DB] Ready — {DB_PATH}")