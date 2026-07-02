"""
database.py — Unified DB layer
  - Uses PostgreSQL when DATABASE_URL is set (psycopg2 driver)
  - Falls back to SQLite for local dev (identical schema, identical SQL)
  
Switch to Postgres:
  export DATABASE_URL="postgresql://user:pass@host:5432/mediscan"
  pip install psycopg2-binary   # on your machine
"""
from __future__ import annotations


import os, sqlite3, json, datetime, uuid, threading

# ── Connection ──────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_USE_POSTGRES = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")
_sqlite_path = os.path.join(os.path.dirname(__file__), "mediscan.db")
_lock = threading.local()   # per-thread SQLite connection


def _get_conn():
    """Return a live connection (thread-safe)."""
    if _USE_POSTGRES:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        if not hasattr(_lock, "conn") or _lock.conn is None:
            _lock.conn = sqlite3.connect(_sqlite_path, check_same_thread=False)
            _lock.conn.row_factory = sqlite3.Row
            _lock.conn.execute("PRAGMA journal_mode=WAL")
            _lock.conn.execute("PRAGMA foreign_keys=ON")
        return _lock.conn


def _ph():
    """Return the correct paramstyle placeholder."""
    return "%s" if _USE_POSTGRES else "?"


def execute(sql, params=(), fetchone=False, fetchall=False, commit=False):
    """Run a SQL statement, return rows or rowcount."""
    ph = _ph()
    # Translate ? → %s for postgres
    if _USE_POSTGRES:
        sql = sql.replace("?", "%s")
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    result = None
    if fetchone:
        row = cur.fetchone()
        result = dict(row) if row else None
    elif fetchall:
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
    if commit:
        conn.commit()
    return result


def executemany(sql, param_list):
    if _USE_POSTGRES:
        sql = sql.replace("?", "%s")
    conn = _get_conn()
    cur = conn.cursor()
    cur.executemany(sql, param_list)
    conn.commit()


def commit():
    _get_conn().commit()


# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    patient_name    TEXT NOT NULL DEFAULT 'Anonymous',
    report_type     TEXT NOT NULL DEFAULT 'General',
    report_date     TEXT NOT NULL,
    upload_date     TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    analysis_notes  TEXT DEFAULT '',
    severity        TEXT NOT NULL DEFAULT 'normal',
    doctor          TEXT DEFAULT '',
    file_ext        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS medicines (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    dosage      TEXT NOT NULL,
    unit        TEXT NOT NULL DEFAULT 'mg',
    frequency   TEXT NOT NULL DEFAULT 'once_daily',
    times       TEXT NOT NULL DEFAULT '["08:00"]',
    with_food   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT DEFAULT '',
    color       TEXT DEFAULT 'teal',
    icon        TEXT DEFAULT '💊',
    start_date  TEXT NOT NULL,
    end_date    TEXT DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dose_logs (
    id          TEXT PRIMARY KEY,
    medicine_id TEXT NOT NULL,
    date_key    TEXT NOT NULL,
    time_key    TEXT NOT NULL,
    taken       INTEGER NOT NULL DEFAULT 1,
    taken_at    TEXT NOT NULL,
    FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE,
    UNIQUE (medicine_id, date_key, time_key)
);

CREATE TABLE IF NOT EXISTS fitness_activities (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL DEFAULT 'running',
    name            TEXT DEFAULT '',
    date            TEXT NOT NULL,
    duration        INTEGER DEFAULT 0,
    distance        REAL DEFAULT 0,
    calories        INTEGER DEFAULT 0,
    heart_rate_avg  INTEGER DEFAULT 0,
    heart_rate_max  INTEGER DEFAULT 0,
    steps           INTEGER DEFAULT 0,
    elevation       REAL DEFAULT 0,
    notes           TEXT DEFAULT '',
    source          TEXT DEFAULT 'manual',
    external_id     TEXT DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id              TEXT PRIMARY KEY,
    service         TEXT NOT NULL UNIQUE,
    access_token    TEXT NOT NULL,
    refresh_token   TEXT DEFAULT '',
    token_type      TEXT DEFAULT 'Bearer',
    expires_at      TEXT DEFAULT '',
    scope           TEXT DEFAULT '',
    athlete_id      TEXT DEFAULT '',
    athlete_name    TEXT DEFAULT '',
    connected_at    TEXT NOT NULL,
    last_sync       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_log (
    id          TEXT PRIMARY KEY,
    service     TEXT NOT NULL,
    synced_at   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'success',
    count       INTEGER DEFAULT 0,
    message     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS user_profile (
    id              TEXT PRIMARY KEY,
    name            TEXT DEFAULT 'User',
    weight_kg       REAL DEFAULT 70,
    height_cm       REAL DEFAULT 170,
    age             INTEGER DEFAULT 25,
    gender          TEXT DEFAULT 'male',
    activity_level  TEXT DEFAULT 'moderate',
    goal            TEXT DEFAULT 'maintain',
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS food_logs (
    id          TEXT PRIMARY KEY,
    food_id     TEXT NOT NULL,
    food_name   TEXT NOT NULL,
    meal_type   TEXT NOT NULL DEFAULT 'lunch',
    date_key    TEXT NOT NULL,
    quantity_g  REAL NOT NULL DEFAULT 100,
    calories    REAL NOT NULL DEFAULT 0,
    protein     REAL DEFAULT 0,
    carbs       REAL DEFAULT 0,
    fat         REAL DEFAULT 0,
    fiber       REAL DEFAULT 0,
    sugar       REAL DEFAULT 0,
    sodium      REAL DEFAULT 0,
    nutrients   TEXT DEFAULT '{}',
    logged_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_foods (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT DEFAULT 'Custom',
    emoji       TEXT DEFAULT '🍽️',
    serving_g   REAL DEFAULT 100,
    calories    REAL NOT NULL,
    protein     REAL DEFAULT 0,
    carbs       REAL DEFAULT 0,
    fat         REAL DEFAULT 0,
    fiber       REAL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thoughts (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    mood        TEXT DEFAULT 'neutral',
    date_key    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS todos (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    notes        TEXT DEFAULT '',
    priority     TEXT DEFAULT 'medium',
    status       TEXT DEFAULT 'pending',
    due_date     TEXT DEFAULT NULL,
    reminder_at  TEXT DEFAULT NULL,
    reminder_sent INTEGER DEFAULT 0,
    tags         TEXT DEFAULT '[]',
    created_at   TEXT NOT NULL,
    completed_at TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS hydration_logs (
    id         TEXT PRIMARY KEY,
    amount_ml  INTEGER NOT NULL,
    drink_type TEXT DEFAULT 'water',
    date_key   TEXT NOT NULL,
    logged_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sleep_logs (
    id           TEXT PRIMARY KEY,
    date_key     TEXT NOT NULL,
    bedtime      TEXT NOT NULL,
    wake_time    TEXT NOT NULL,
    duration_h   REAL NOT NULL,
    quality      INTEGER DEFAULT 3,
    notes        TEXT DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS body_metrics (
    id          TEXT PRIMARY KEY,
    date_key    TEXT NOT NULL,
    weight_kg   REAL DEFAULT NULL,
    body_fat_pct REAL DEFAULT NULL,
    waist_cm    REAL DEFAULT NULL,
    bmi         REAL DEFAULT NULL,
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS habits (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    emoji       TEXT DEFAULT '⭐',
    category    TEXT DEFAULT 'general',
    target_days TEXT DEFAULT '[]',
    color       TEXT DEFAULT '#0E8F7E',
    active      INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS habit_logs (
    id         TEXT PRIMARY KEY,
    habit_id   TEXT NOT NULL,
    date_key   TEXT NOT NULL,
    done       INTEGER DEFAULT 1,
    logged_at  TEXT NOT NULL,
    UNIQUE(habit_id, date_key)
);

CREATE TABLE IF NOT EXISTS symptoms (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    severity   INTEGER DEFAULT 5,
    date_key   TEXT NOT NULL,
    time_of_day TEXT DEFAULT 'morning',
    notes      TEXT DEFAULT '',
    logged_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vitals (
    id         TEXT PRIMARY KEY,
    date_key   TEXT NOT NULL,
    type       TEXT NOT NULL,
    value1     REAL NOT NULL,
    value2     REAL DEFAULT NULL,
    unit       TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    logged_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emergency_info (
    id          TEXT PRIMARY KEY,
    blood_type  TEXT DEFAULT '',
    allergies   TEXT DEFAULT '',
    conditions  TEXT DEFAULT '',
    medications TEXT DEFAULT '',
    contact1_name  TEXT DEFAULT '',
    contact1_phone TEXT DEFAULT '',
    contact2_name  TEXT DEFAULT '',
    contact2_phone TEXT DEFAULT '',
    insurance_provider TEXT DEFAULT '',
    insurance_number   TEXT DEFAULT '',
    updated_at  TEXT NOT NULL
);
"""

def init_db():
    """Create all tables (idempotent)."""
    conn = _get_conn()
    # SQLite needs statements split; Postgres can handle the block
    for stmt in SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt) if not _USE_POSTGRES else conn.cursor().execute(stmt + ";")
    conn.commit()
    print(f"[DB] Initialized ({'PostgreSQL' if _USE_POSTGRES else 'SQLite @ ' + _sqlite_path})")


# ── Helper: JSON columns ─────────────────────────────────────────────────────

def jdump(v): return json.dumps(v)
def jload(v, default=None):
    try: return json.loads(v) if v else (default if default is not None else [])
    except: return default if default is not None else []

def now_iso(): return datetime.datetime.now().isoformat()
def today_iso(): return datetime.date.today().isoformat()
def new_id(): return uuid.uuid4().hex


# ── Reports ──────────────────────────────────────────────────────────────────

def insert_report(data: dict) -> dict:
    rid = new_id()
    execute("""
        INSERT INTO reports
          (id,filename,original_name,patient_name,report_type,report_date,
           upload_date,tags,analysis_notes,severity,doctor,file_ext)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (rid, data['filename'], data['original_name'], data['patient_name'],
          data['report_type'], data['report_date'], now_iso(),
          jdump(data.get('tags', [])), data.get('analysis_notes',''),
          data.get('severity','normal'), data.get('doctor',''), data.get('file_ext','')),
        commit=True)
    return get_report(rid)


def get_report(rid):
    r = execute("SELECT * FROM reports WHERE id=?", (rid,), fetchone=True)
    return _fmt_report(r) if r else None


def list_reports(search='', tag='', severity=''):
    rows = execute("SELECT * FROM reports ORDER BY upload_date DESC", fetchall=True)
    result = [_fmt_report(r) for r in rows]
    if tag:
        result = [r for r in result if tag in r.get('tags', [])]
    if severity:
        result = [r for r in result if r.get('severity') == severity]
    if search:
        s = search.lower()
        result = [r for r in result if
                  s in r.get('patient_name','').lower() or
                  s in r.get('report_type','').lower() or
                  s in ' '.join(r.get('tags',[])).lower() or
                  s in r.get('analysis_notes','').lower()]
    return result


def delete_report(rid):
    execute("DELETE FROM reports WHERE id=?", (rid,), commit=True)


def _fmt_report(r):
    d = dict(r)
    d['tags'] = jload(d.get('tags', '[]'), [])
    return d


def report_stats():
    rows = execute("SELECT * FROM reports", fetchall=True)
    sev, types, tags = {}, {}, {}
    for r in rows:
        s = r.get('severity', 'normal'); sev[s] = sev.get(s, 0) + 1
        t = r.get('report_type', 'General'); types[t] = types.get(t, 0) + 1
        for tg in jload(r.get('tags', '[]'), []): tags[tg] = tags.get(tg, 0) + 1
    top = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:6]
    return {'total': len(rows), 'severity': sev, 'types': types, 'top_tags': top}


# ── Medicines ─────────────────────────────────────────────────────────────────

def insert_medicine(data: dict) -> dict:
    mid = new_id()
    execute("""
        INSERT INTO medicines
          (id,name,dosage,unit,frequency,times,with_food,notes,color,icon,start_date,end_date,active,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)
    """, (mid, data['name'], data['dosage'], data.get('unit','mg'),
          data.get('frequency','once_daily'), jdump(data.get('times',['08:00'])),
          1 if data.get('with_food') else 0, data.get('notes',''),
          data.get('color','teal'), data.get('icon','💊'),
          data.get('start_date', today_iso()), data.get('end_date',''), now_iso()),
        commit=True)
    return get_medicine(mid)


def get_medicine(mid):
    r = execute("SELECT * FROM medicines WHERE id=?", (mid,), fetchone=True)
    return _fmt_med(r) if r else None


def list_medicines():
    rows = execute("SELECT * FROM medicines ORDER BY created_at DESC", fetchall=True)
    return [_fmt_med(r) for r in rows]


def toggle_medicine(mid):
    execute("UPDATE medicines SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?",
            (mid,), commit=True)


def delete_medicine(mid):
    execute("DELETE FROM medicines WHERE id=?", (mid,), commit=True)


def _fmt_med(r):
    d = dict(r)
    d['times'] = jload(d.get('times', '["08:00"]'), ['08:00'])
    d['with_food'] = bool(d.get('with_food', 0))
    d['active'] = bool(d.get('active', 1))
    return d


# ── Dose Logs ────────────────────────────────────────────────────────────────

def log_dose(medicine_id, date_key, time_key, taken=True):
    lid = new_id()
    # Upsert
    existing = execute(
        "SELECT id FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=?",
        (medicine_id, date_key, time_key), fetchone=True)
    if existing:
        execute("UPDATE dose_logs SET taken=?, taken_at=? WHERE id=?",
                (1 if taken else 0, now_iso(), existing['id']), commit=True)
    else:
        execute("""
            INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at)
            VALUES (?,?,?,?,?,?)
        """, (lid, medicine_id, date_key, time_key, 1 if taken else 0, now_iso()), commit=True)


def get_today_doses():
    today = today_iso()
    meds = [m for m in list_medicines() if m['active']]
    doses = []
    for m in meds:
        for t in m.get('times', []):
            log = execute(
                "SELECT * FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=?",
                (m['id'], today, t), fetchone=True)
            doses.append({
                'med_id': m['id'], 'med_name': m['name'], 'dosage': m['dosage'],
                'unit': m['unit'], 'time': t, 'icon': m.get('icon', '💊'),
                'color': m.get('color', 'teal'), 'with_food': m.get('with_food', False),
                'taken': bool(log and log.get('taken')),
                'taken_at': log['taken_at'] if log else ''
            })
    doses.sort(key=lambda x: x['time'])
    return doses


def get_adherence_stats(days=30):
    """Compute adherence % over the past N days."""
    from datetime import date, timedelta
    total, taken = 0, 0
    meds = list_medicines()
    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        for m in meds:
            if not m['active']: continue
            for t in m.get('times', []):
                total += 1
                log = execute(
                    "SELECT taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=?",
                    (m['id'], d, t), fetchone=True)
                if log and log.get('taken'): taken += 1
    return {'total': total, 'taken': taken, 'pct': round(taken/total*100, 1) if total else 0}


# ── Fitness Activities ────────────────────────────────────────────────────────

def insert_activity(data: dict, check_duplicate=True) -> dict | None:
    """Insert activity; skip if external_id already exists."""
    if check_duplicate and data.get('external_id'):
        exists = execute("SELECT id FROM fitness_activities WHERE external_id=?",
                         (data['external_id'],), fetchone=True)
        if exists: return None   # already imported

    aid = new_id()
    execute("""
        INSERT INTO fitness_activities
          (id,type,name,date,duration,distance,calories,heart_rate_avg,
           heart_rate_max,steps,elevation,notes,source,external_id,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (aid, data.get('type','running'), data.get('name',''),
          data.get('date', today_iso()), int(data.get('duration',0)),
          float(data.get('distance',0)), int(data.get('calories',0)),
          int(data.get('heart_rate_avg',0)), int(data.get('heart_rate_max',0)),
          int(data.get('steps',0)), float(data.get('elevation',0)),
          data.get('notes',''), data.get('source','manual'),
          data.get('external_id',''), now_iso()), commit=True)
    return get_activity(aid)


def get_activity(aid):
    r = execute("SELECT * FROM fitness_activities WHERE id=?", (aid,), fetchone=True)
    return dict(r) if r else None


def list_activities():
    rows = execute("SELECT * FROM fitness_activities ORDER BY date DESC, created_at DESC",
                   fetchall=True)
    return [dict(r) for r in rows]


def delete_activity(aid):
    execute("DELETE FROM fitness_activities WHERE id=?", (aid,), commit=True)


def fitness_stats():
    import datetime as dt
    today = dt.date.today()
    week_start = (today - dt.timedelta(days=today.weekday())).isoformat()
    month_str = today.strftime('%Y-%m')

    all_acts = list_activities()
    week_acts = [a for a in all_acts if a.get('date','') >= week_start]
    month_acts = [a for a in all_acts if a.get('date','')[:7] == month_str]

    def sf(lst, f): return sum(a.get(f,0) for a in lst)

    # Per-day breakdown Mon–Sun
    days = {}
    for i in range(7):
        d = (today - dt.timedelta(days=today.weekday()-i)).isoformat()
        da = [a for a in all_acts if a.get('date') == d]
        days[d] = {'calories': sf(da,'calories'), 'duration': sf(da,'duration'), 'count': len(da)}

    # Type breakdown
    type_bd = {}
    for a in all_acts[:100]:
        t = a.get('type','other'); type_bd[t] = type_bd.get(t,0) + 1

    # AI suggestions
    suggestions = []
    week_dur = sf(week_acts,'duration')
    week_cal = sf(week_acts,'calories')
    if len(week_acts) == 0:
        suggestions.append({'type':'critical','icon':'⚠️','text':'No workouts logged this week. Start with a 20-minute walk!','priority':0})
    if week_dur < 150:
        suggestions.append({'type':'warning','icon':'🏃','text':f'You\'ve done {week_dur} of the recommended 150 min/week. A 30-min jog today gets you closer!','priority':1})
    if week_cal < 1500:
        suggestions.append({'type':'info','icon':'🔥','text':f'Only {week_cal} kcal burned this week. A HIIT or cycling session adds 400–600 kcal.','priority':2})
    if not any(a.get('type') in ['yoga','stretching','flexibility'] for a in week_acts):
        suggestions.append({'type':'info','icon':'🧘','text':'No flexibility or recovery work this week. 10 min of stretching aids muscle repair.','priority':3})
    if any(a.get('heart_rate_avg',0) > 170 for a in week_acts):
        suggestions.append({'type':'warning','icon':'❤️','text':'High avg heart rate detected this week. Consider a low-intensity recovery session.','priority':3})
    if week_dur > 300:
        suggestions.append({'type':'success','icon':'🌟','text':f'Excellent week! {week_dur} active minutes. Ensure at least one full rest day.','priority':4})
    if sf(week_acts,'distance') > 20:
        suggestions.append({'type':'success','icon':'🏅','text':f'Over {round(sf(week_acts,"distance"),1)} km covered this week — great endurance work!','priority':4})
    suggestions.sort(key=lambda x: x['priority'])

    today_iso = today.isoformat()
    today_acts = [a for a in all_acts if a.get('date') == today_iso]

    return {
        'week': {'activities': len(week_acts), 'calories': sf(week_acts,'calories'),
                 'duration': sf(week_acts,'duration'), 'distance': round(sf(week_acts,'distance'),1)},
        'month': {'activities': len(month_acts), 'calories': sf(month_acts,'calories'),
                  'duration': sf(month_acts,'duration')},
        'today': {'activities': len(today_acts), 'calories': sf(today_acts,'calories'),
                  'duration': sf(today_acts,'duration'), 'distance': round(sf(today_acts,'distance'),1)},
        'total': len(all_acts),
        'weekly_days': days,
        'type_breakdown': type_bd,
        'suggestions': suggestions[:5]
    }


# ── OAuth Tokens ──────────────────────────────────────────────────────────────

def save_token(service, token_data: dict):
    existing = execute("SELECT id FROM oauth_tokens WHERE service=?", (service,), fetchone=True)
    if existing:
        execute("""
            UPDATE oauth_tokens SET
              access_token=?, refresh_token=?, token_type=?, expires_at=?,
              scope=?, athlete_id=?, athlete_name=?, last_sync=?
            WHERE service=?
        """, (token_data.get('access_token',''), token_data.get('refresh_token',''),
              token_data.get('token_type','Bearer'), token_data.get('expires_at',''),
              token_data.get('scope',''), token_data.get('athlete_id',''),
              token_data.get('athlete_name',''), '', service), commit=True)
    else:
        execute("""
            INSERT INTO oauth_tokens
              (id,service,access_token,refresh_token,token_type,expires_at,
               scope,athlete_id,athlete_name,connected_at,last_sync)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (new_id(), service, token_data.get('access_token',''),
              token_data.get('refresh_token',''), token_data.get('token_type','Bearer'),
              token_data.get('expires_at',''), token_data.get('scope',''),
              token_data.get('athlete_id',''), token_data.get('athlete_name',''),
              now_iso(), ''), commit=True)


def get_token(service) -> dict | None:
    r = execute("SELECT * FROM oauth_tokens WHERE service=?", (service,), fetchone=True)
    return dict(r) if r else None


def list_tokens():
    rows = execute("SELECT service,athlete_name,connected_at,last_sync FROM oauth_tokens",
                   fetchall=True)
    return [dict(r) for r in rows]


def update_last_sync(service):
    execute("UPDATE oauth_tokens SET last_sync=? WHERE service=?",
            (now_iso(), service), commit=True)


def delete_token(service):
    execute("DELETE FROM oauth_tokens WHERE service=?", (service,), commit=True)


# ── Sync Log ──────────────────────────────────────────────────────────────────

def log_sync(service, status='success', count=0, message=''):
    execute("""
        INSERT INTO sync_log (id,service,synced_at,status,count,message)
        VALUES (?,?,?,?,?,?)
    """, (new_id(), service, now_iso(), status, count, message), commit=True)


def get_sync_history(service=None, limit=20):
    if service:
        rows = execute(
            "SELECT * FROM sync_log WHERE service=? ORDER BY synced_at DESC LIMIT ?",
            (service, limit), fetchall=True)
    else:
        rows = execute("SELECT * FROM sync_log ORDER BY synced_at DESC LIMIT ?",
                       (limit,), fetchall=True)
    return [dict(r) for r in rows]


# ── User Profile ──────────────────────────────────────────────────────────────

def get_profile() -> dict:
    r = execute("SELECT * FROM user_profile LIMIT 1", fetchone=True)
    if r: return dict(r)
    # Auto-create default profile
    pid = new_id()
    execute("""INSERT INTO user_profile
        (id,name,weight_kg,height_cm,age,gender,activity_level,goal,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (pid,'User',70,170,25,'male','moderate','maintain',now_iso()), commit=True)
    return get_profile()

def update_profile(data: dict) -> dict:
    p = get_profile()
    execute("""UPDATE user_profile SET
        name=?,weight_kg=?,height_cm=?,age=?,gender=?,
        activity_level=?,goal=?,updated_at=?
        WHERE id=?""",
        (data.get('name',p['name']),
         float(data.get('weight_kg',p['weight_kg'])),
         float(data.get('height_cm',p['height_cm'])),
         int(data.get('age',p['age'])),
         data.get('gender',p['gender']),
         data.get('activity_level',p['activity_level']),
         data.get('goal',p['goal']),
         now_iso(), p['id']), commit=True)
    return get_profile()

def calc_tdee(profile: dict) -> dict:
    """Harris-Benedict BMR → TDEE with goal adjustment."""
    w = float(profile.get('weight_kg', 70))
    h = float(profile.get('height_cm', 170))
    a = int(profile.get('age', 25))
    g = profile.get('gender', 'male')
    act = profile.get('activity_level', 'moderate')
    goal = profile.get('goal', 'maintain')

    # BMR
    if g == 'male':
        bmr = 88.362 + (13.397 * w) + (4.799 * h) - (5.677 * a)
    else:
        bmr = 447.593 + (9.247 * w) + (3.098 * h) - (4.330 * a)

    act_mult = {'sedentary':1.2,'light':1.375,'moderate':1.55,'active':1.725,'very_active':1.9}
    tdee = bmr * act_mult.get(act, 1.55)

    goal_adj = {'lose_fast':-500,'lose':-250,'maintain':0,'gain':250,'gain_fast':500}
    target_cal = tdee + goal_adj.get(goal, 0)

    # Macro targets (g)
    protein_g  = round(w * (1.6 if goal in ('gain','gain_fast') else 1.2))
    fat_g      = round(target_cal * 0.28 / 9)
    carbs_g    = round((target_cal - protein_g*4 - fat_g*9) / 4)

    return {
        'bmr': round(bmr),
        'tdee': round(tdee),
        'target_calories': round(target_cal),
        'protein_g': protein_g,
        'carbs_g': max(carbs_g, 50),
        'fat_g': fat_g,
        'fiber_g': 30,
        'water_ml': round(w * 35)
    }

# ── Food Logs ─────────────────────────────────────────────────────────────────

def log_food(data: dict) -> dict:
    fid = new_id()
    execute("""INSERT INTO food_logs
        (id,food_id,food_name,meal_type,date_key,quantity_g,
         calories,protein,carbs,fat,fiber,sugar,sodium,nutrients,logged_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, data.get('food_id','custom'), data.get('food_name',''),
         data.get('meal_type','lunch'), data.get('date_key', today_iso()),
         float(data.get('quantity_g',100)),
         float(data.get('calories',0)), float(data.get('protein',0)),
         float(data.get('carbs',0)), float(data.get('fat',0)),
         float(data.get('fiber',0)), float(data.get('sugar',0)),
         float(data.get('sodium',0)), jdump(data.get('nutrients',{})),
         now_iso()), commit=True)
    r = execute("SELECT * FROM food_logs WHERE id=?", (fid,), fetchone=True)
    return _fmt_food_log(r)

def get_food_logs(date_key: str) -> list:
    rows = execute(
        "SELECT * FROM food_logs WHERE date_key=? ORDER BY logged_at",
        (date_key,), fetchall=True)
    return [_fmt_food_log(r) for r in rows]

def delete_food_log(lid: str):
    execute("DELETE FROM food_logs WHERE id=?", (lid,), commit=True)

def _fmt_food_log(r) -> dict:
    d = dict(r)
    d['nutrients'] = jload(d.get('nutrients','{}'), {})
    return d

def get_nutrition_summary(date_key: str) -> dict:
    logs = get_food_logs(date_key)
    totals = {'calories':0,'protein':0,'carbs':0,'fat':0,'fiber':0,'sugar':0,'sodium':0,
              'vit_a':0,'vit_c':0,'vit_d':0,'vit_b12':0,'iron':0,'calcium':0,'magnesium':0}
    by_meal = {}
    for log in logs:
        for k in totals:
            totals[k] += log.get(k, 0) or log.get('nutrients',{}).get(k, 0)
        mt = log.get('meal_type','other')
        if mt not in by_meal:
            by_meal[mt] = {'calories':0,'protein':0,'carbs':0,'fat':0,'items':[]}
        by_meal[mt]['calories'] += log.get('calories',0)
        by_meal[mt]['protein']  += log.get('protein',0)
        by_meal[mt]['carbs']    += log.get('carbs',0)
        by_meal[mt]['fat']      += log.get('fat',0)
        by_meal[mt]['items'].append(log)
    return {'totals': {k: round(v, 1) for k,v in totals.items()},
            'by_meal': by_meal, 'log_count': len(logs)}

def get_weekly_nutrition(days: int = 7) -> list:
    import datetime as dt
    result = []
    for i in range(days - 1, -1, -1):
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        summary = get_nutrition_summary(d)
        result.append({'date': d, **summary['totals']})
    return result

def save_custom_food(data: dict) -> dict:
    fid = new_id()
    execute("""INSERT INTO custom_foods
        (id,name,category,emoji,serving_g,calories,protein,carbs,fat,fiber,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, data['name'], data.get('category','Custom'), data.get('emoji','🍽️'),
         float(data.get('serving_g',100)), float(data['calories']),
         float(data.get('protein',0)), float(data.get('carbs',0)),
         float(data.get('fat',0)), float(data.get('fiber',0)), now_iso()), commit=True)
    r = execute("SELECT * FROM custom_foods WHERE id=?", (fid,), fetchone=True)
    return dict(r)

def list_custom_foods() -> list:
    rows = execute("SELECT * FROM custom_foods ORDER BY name", fetchall=True)
    return [dict(r) for r in rows]


# ── Thoughts / Daily Journal ───────────────────────────────────────────────────

MAX_THOUGHTS_PER_DAY = 10

def get_thoughts(date_key: str) -> list:
    rows = execute(
        "SELECT * FROM thoughts WHERE date_key=? ORDER BY created_at DESC",
        (date_key,), fetchall=True)
    return [dict(r) for r in rows]

def count_thoughts_today(date_key: str) -> int:
    r = execute("SELECT COUNT(*) as n FROM thoughts WHERE date_key=?", (date_key,), fetchone=True)
    return r['n'] if r else 0

def save_thought(content: str, mood: str, date_key: str) -> dict:
    if count_thoughts_today(date_key) >= MAX_THOUGHTS_PER_DAY:
        raise ValueError(f"Max {MAX_THOUGHTS_PER_DAY} thoughts per day reached")
    tid = new_id()
    now = now_iso()
    execute("""INSERT INTO thoughts (id,content,mood,date_key,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (tid, content.strip(), mood, date_key, now, now), commit=True)
    return dict(execute("SELECT * FROM thoughts WHERE id=?", (tid,), fetchone=True))

def update_thought(tid: str, content: str, mood: str) -> dict:
    execute("UPDATE thoughts SET content=?,mood=?,updated_at=? WHERE id=?",
            (content.strip(), mood, now_iso(), tid), commit=True)
    r = execute("SELECT * FROM thoughts WHERE id=?", (tid,), fetchone=True)
    return dict(r) if r else {}

def delete_thought(tid: str):
    execute("DELETE FROM thoughts WHERE id=?", (tid,), commit=True)

def get_thoughts_range(days: int = 7) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute(
        "SELECT * FROM thoughts WHERE date_key >= ? ORDER BY created_at DESC",
        (start,), fetchall=True)
    return [dict(r) for r in rows]

# ── Todos ─────────────────────────────────────────────────────────────────────

def list_todos(status: str = None) -> list:
    if status:
        rows = execute(
            "SELECT * FROM todos WHERE status=? ORDER BY priority DESC, due_date ASC, created_at DESC",
            (status,), fetchall=True)
    else:
        rows = execute(
            "SELECT * FROM todos ORDER BY status ASC, priority DESC, due_date ASC, created_at DESC",
            fetchall=True)
    result = []
    for r in rows:
        d = dict(r)
        d['tags'] = jload(d.get('tags', '[]'), [])
        result.append(d)
    return result

def create_todo(data: dict) -> dict:
    tid = new_id()
    now = now_iso()
    execute("""INSERT INTO todos
               (id,title,notes,priority,status,due_date,reminder_at,tags,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (tid, data.get('title','').strip(), data.get('notes',''),
             data.get('priority','medium'), 'pending',
             data.get('due_date') or None, data.get('reminder_at') or None,
             jdump(data.get('tags',[])), now), commit=True)
    r = execute("SELECT * FROM todos WHERE id=?", (tid,), fetchone=True)
    d = dict(r)
    d['tags'] = jload(d.get('tags','[]'), [])
    return d

def update_todo(tid: str, data: dict) -> dict:
    execute("""UPDATE todos SET title=?,notes=?,priority=?,due_date=?,
               reminder_at=?,tags=? WHERE id=?""",
            (data.get('title','').strip(), data.get('notes',''),
             data.get('priority','medium'), data.get('due_date') or None,
             data.get('reminder_at') or None,
             jdump(data.get('tags',[])), tid), commit=True)
    r = execute("SELECT * FROM todos WHERE id=?", (tid,), fetchone=True)
    d = dict(r)
    d['tags'] = jload(d.get('tags','[]'), [])
    return d

def toggle_todo(tid: str) -> dict:
    r = execute("SELECT status FROM todos WHERE id=?", (tid,), fetchone=True)
    if not r: return {}
    new_status = 'done' if r['status'] == 'pending' else 'pending'
    completed = now_iso() if new_status == 'done' else None
    execute("UPDATE todos SET status=?,completed_at=? WHERE id=?",
            (new_status, completed, tid), commit=True)
    r2 = execute("SELECT * FROM todos WHERE id=?", (tid,), fetchone=True)
    d = dict(r2)
    d['tags'] = jload(d.get('tags','[]'), [])
    return d

def delete_todo(tid: str):
    execute("DELETE FROM todos WHERE id=?", (tid,), commit=True)

def get_due_reminders() -> list:
    """Return todos with reminder_at <= now that haven't been sent."""
    now = now_iso()[:16]  # YYYY-MM-DDTHH:MM
    rows = execute(
        "SELECT * FROM todos WHERE reminder_at IS NOT NULL AND reminder_at <= ? AND reminder_sent=0 AND status='pending'",
        (now,), fetchall=True)
    return [dict(r) for r in rows]

def mark_reminder_sent(tid: str):
    execute("UPDATE todos SET reminder_sent=1 WHERE id=?", (tid,), commit=True)


# ── Hydration ─────────────────────────────────────────────────────────────────

def log_hydration(amount_ml: int, drink_type: str, date_key: str) -> dict:
    hid = new_id()
    execute("""INSERT INTO hydration_logs (id,amount_ml,drink_type,date_key,logged_at)
               VALUES (?,?,?,?,?)""", (hid, amount_ml, drink_type, date_key, now_iso()), commit=True)
    return dict(execute("SELECT * FROM hydration_logs WHERE id=?", (hid,), fetchone=True))

def get_hydration_day(date_key: str) -> dict:
    rows = execute("SELECT * FROM hydration_logs WHERE date_key=? ORDER BY logged_at", (date_key,), fetchall=True)
    logs = [dict(r) for r in rows]
    total = sum(r['amount_ml'] for r in logs)
    return {'logs': logs, 'total_ml': total, 'date': date_key}

def delete_hydration_log(lid: str):
    execute("DELETE FROM hydration_logs WHERE id=?", (lid,), commit=True)

def get_hydration_week(days: int = 7) -> list:
    import datetime as dt
    result = []
    for i in range(days-1, -1, -1):
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        rows = execute("SELECT SUM(amount_ml) as total FROM hydration_logs WHERE date_key=?", (d,), fetchone=True)
        result.append({'date': d, 'total_ml': rows['total'] or 0})
    return result

# ── Sleep ─────────────────────────────────────────────────────────────────────

def log_sleep(data: dict) -> dict:
    sid = new_id()
    execute("""INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,quality,notes,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, data['date_key'], data['bedtime'], data['wake_time'],
             float(data['duration_h']), int(data.get('quality',3)),
             data.get('notes',''), now_iso()), commit=True)
    return dict(execute("SELECT * FROM sleep_logs WHERE id=?", (sid,), fetchone=True))

def get_sleep_logs(days: int = 14) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM sleep_logs WHERE date_key >= ? ORDER BY date_key DESC", (start,), fetchall=True)
    return [dict(r) for r in rows]

def delete_sleep_log(lid: str):
    execute("DELETE FROM sleep_logs WHERE id=?", (lid,), commit=True)

# ── Body Metrics ──────────────────────────────────────────────────────────────

def log_body_metric(data: dict) -> dict:
    bid = new_id()
    w = data.get('weight_kg')
    h_cm = data.get('height_cm')
    bmi = round(w / ((h_cm/100)**2), 1) if w and h_cm else None
    execute("""INSERT INTO body_metrics (id,date_key,weight_kg,body_fat_pct,waist_cm,bmi,notes,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (bid, data['date_key'], w, data.get('body_fat_pct'),
             data.get('waist_cm'), bmi, data.get('notes',''), now_iso()), commit=True)
    return dict(execute("SELECT * FROM body_metrics WHERE id=?", (bid,), fetchone=True))

def get_body_metrics(days: int = 30) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM body_metrics WHERE date_key >= ? ORDER BY date_key", (start,), fetchall=True)
    return [dict(r) for r in rows]

# ── Habits ────────────────────────────────────────────────────────────────────

def list_habits() -> list:
    rows = execute("SELECT * FROM habits WHERE active=1 ORDER BY created_at", fetchall=True)
    result = []
    for r in rows:
        d = dict(r)
        d['target_days'] = jload(d.get('target_days','[]'), [])
        result.append(d)
    return result

def create_habit(data: dict) -> dict:
    hid = new_id()
    execute("""INSERT INTO habits (id,name,emoji,category,target_days,color,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (hid, data['name'], data.get('emoji','⭐'), data.get('category','general'),
             jdump(data.get('target_days',[])), data.get('color','#0E8F7E'), now_iso()), commit=True)
    r = execute("SELECT * FROM habits WHERE id=?", (hid,), fetchone=True)
    d = dict(r); d['target_days'] = jload(d.get('target_days','[]'), []); return d

def delete_habit(hid: str):
    execute("UPDATE habits SET active=0 WHERE id=?", (hid,), commit=True)
    execute("DELETE FROM habit_logs WHERE habit_id=?", (hid,), commit=True)

def toggle_habit_log(habit_id: str, date_key: str) -> dict:
    r = execute("SELECT * FROM habit_logs WHERE habit_id=? AND date_key=?", (habit_id, date_key), fetchone=True)
    if r:
        execute("DELETE FROM habit_logs WHERE habit_id=? AND date_key=?", (habit_id, date_key), commit=True)
        return {'done': False}
    else:
        execute("INSERT OR REPLACE INTO habit_logs (id,habit_id,date_key,done,logged_at) VALUES (?,?,?,1,?)",
                (new_id(), habit_id, date_key, now_iso()), commit=True)
        return {'done': True}

def get_habit_stats(days: int = 30) -> dict:
    import datetime as dt
    habits = list_habits()
    today = dt.date.today().isoformat()
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    result = []
    for h in habits:
        logs = execute("SELECT date_key FROM habit_logs WHERE habit_id=? AND date_key >= ? AND done=1",
                       (h['id'], start), fetchall=True)
        done_dates = {r['date_key'] for r in logs}
        # Calculate streak
        streak = 0
        d = dt.date.today()
        while True:
            if d.isoformat() in done_dates:
                streak += 1; d -= dt.timedelta(days=1)
            else: break
        result.append({**h, 'done_dates': list(done_dates),
                       'done_today': today in done_dates,
                       'streak': streak, 'completions': len(done_dates)})
    return {'habits': result, 'date': today}

# ── Symptoms ──────────────────────────────────────────────────────────────────

def log_symptom(data: dict) -> dict:
    sid = new_id()
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,logged_at)
               VALUES (?,?,?,?,?,?,?)""",
            (sid, data['name'], int(data.get('severity',5)), data.get('date_key', today_iso()),
             data.get('time_of_day','morning'), data.get('notes',''), now_iso()), commit=True)
    return dict(execute("SELECT * FROM symptoms WHERE id=?", (sid,), fetchone=True))

def get_symptoms(days: int = 14) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM symptoms WHERE date_key >= ? ORDER BY logged_at DESC", (start,), fetchall=True)
    return [dict(r) for r in rows]

def delete_symptom(sid: str):
    execute("DELETE FROM symptoms WHERE id=?", (sid,), commit=True)

# ── Vitals (BP, Blood Sugar) ──────────────────────────────────────────────────

def log_vital(data: dict) -> dict:
    vid = new_id()
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,notes,logged_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (vid, data.get('date_key', today_iso()), data['type'],
             float(data['value1']), float(data.get('value2') or 0) or None,
             data.get('unit',''), data.get('notes',''), now_iso()), commit=True)
    return dict(execute("SELECT * FROM vitals WHERE id=?", (vid,), fetchone=True))

def get_vitals(vtype: str = None, days: int = 30) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    if vtype:
        rows = execute("SELECT * FROM vitals WHERE type=? AND date_key >= ? ORDER BY logged_at DESC",
                       (vtype, start), fetchall=True)
    else:
        rows = execute("SELECT * FROM vitals WHERE date_key >= ? ORDER BY logged_at DESC",
                       (start,), fetchall=True)
    return [dict(r) for r in rows]

def delete_vital(vid: str):
    execute("DELETE FROM vitals WHERE id=?", (vid,), commit=True)

# ── Emergency Info ────────────────────────────────────────────────────────────

def get_emergency_info() -> dict:
    r = execute("SELECT * FROM emergency_info LIMIT 1", fetchone=True)
    if r: return dict(r)
    eid = new_id()
    execute("INSERT INTO emergency_info (id,updated_at) VALUES (?,?)", (eid, now_iso()), commit=True)
    return get_emergency_info()

def save_emergency_info(data: dict) -> dict:
    e = get_emergency_info()
    execute("""UPDATE emergency_info SET blood_type=?,allergies=?,conditions=?,medications=?,
               contact1_name=?,contact1_phone=?,contact2_name=?,contact2_phone=?,
               insurance_provider=?,insurance_number=?,updated_at=? WHERE id=?""",
            (data.get('blood_type',''), data.get('allergies',''), data.get('conditions',''),
             data.get('medications',''), data.get('contact1_name',''), data.get('contact1_phone',''),
             data.get('contact2_name',''), data.get('contact2_phone',''),
             data.get('insurance_provider',''), data.get('insurance_number',''),
             now_iso(), e['id']), commit=True)
    return get_emergency_info()


# ── Medicine refill tracking ──────────────────────────────────────────────────

def update_medicine_stock(mid: str, pill_count: int, pills_per_dose: int = 1, refill_threshold: int = 7) -> dict:
    execute("UPDATE medicines SET pill_count=?,pills_per_dose=?,refill_threshold=? WHERE id=?",
            (pill_count, pills_per_dose, refill_threshold, mid), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=?", (mid,), fetchone=True)
    return dict(r) if r else {}

def decrement_pill_count(mid: str):
    """Call after a dose is taken to reduce stock."""
    r = execute("SELECT pill_count,pills_per_dose FROM medicines WHERE id=?", (mid,), fetchone=True)
    if r and r['pill_count'] is not None:
        new_count = max(0, r['pill_count'] - (r['pills_per_dose'] or 1))
        execute("UPDATE medicines SET pill_count=? WHERE id=?", (new_count, mid), commit=True)

def get_low_stock_medicines():
    """Return medicines where days remaining < refill_threshold."""
    meds = list_medicines()
    low = []
    for m in meds:
        if m.get('pill_count') is None: continue
        freq_doses = {
            'once_daily':1, 'twice_daily':2, 'thrice_daily':3, 'weekly':1/7,
            'once':1, 'twice':2, 'three_times':3   # legacy keys
        }.get(m.get('frequency','once_daily'), 1)
        days_left = m['pill_count'] / max(freq_doses * (m.get('pills_per_dose') or 1), 0.01)
        if days_left < (m.get('refill_threshold') or 7):
            low.append({**m, 'days_left': round(days_left, 1)})
    return low

# ── Notification log ──────────────────────────────────────────────────────────

def add_notification(ntype: str, title: str, body: str = '', source_id: str = None) -> dict:
    nid = new_id()
    execute("INSERT INTO notification_log (id,type,title,body,source_id,read,created_at) VALUES (?,?,?,?,?,0,?)",
            (nid, ntype, title, body, source_id, now_iso()), commit=True)
    return dict(execute("SELECT * FROM notification_log WHERE id=?", (nid,), fetchone=True))

def get_notifications(limit: int = 50, unread_only: bool = False) -> list:
    if unread_only:
        rows = execute("SELECT * FROM notification_log WHERE read=0 ORDER BY created_at DESC LIMIT ?",
                       (limit,), fetchall=True)
    else:
        rows = execute("SELECT * FROM notification_log ORDER BY created_at DESC LIMIT ?",
                       (limit,), fetchall=True)
    return [dict(r) for r in rows]

def mark_notification_read(nid: str):
    execute("UPDATE notification_log SET read=1 WHERE id=?", (nid,), commit=True)

def mark_all_notifications_read():
    execute("UPDATE notification_log SET read=1", commit=True)

def unread_notification_count() -> int:
    r = execute("SELECT COUNT(*) as n FROM notification_log WHERE read=0", fetchone=True)
    return r['n'] if r else 0

# ── Weekly health report ──────────────────────────────────────────────────────

def generate_weekly_report() -> dict:
    import datetime as dt
    today = dt.date.today()
    week_start = (today - dt.timedelta(days=6)).isoformat()
    today_iso_v = today.isoformat()

    # Sleep
    sleep_rows = execute("SELECT duration_h,quality FROM sleep_logs WHERE date_key >= ? AND date_key <= ?",
                         (week_start, today_iso_v), fetchall=True)
    avg_sleep = round(sum(r['duration_h'] for r in sleep_rows) / len(sleep_rows), 1) if sleep_rows else None
    avg_sleep_q = round(sum(r['quality'] for r in sleep_rows) / len(sleep_rows), 1) if sleep_rows else None

    # Workouts
    acts = execute("SELECT * FROM fitness_activities WHERE date >= ? AND date <= ?",
                   (week_start, today_iso_v), fetchall=True)
    workout_days = len(set(r['date'] for r in acts))
    cal_burned   = sum(r['calories'] or 0 for r in acts)

    # Calories eaten
    food = execute("SELECT SUM(calories) as total FROM food_logs WHERE date_key >= ? AND date_key <= ?",
                   (week_start, today_iso_v), fetchone=True)
    cal_eaten = round(food['total'] or 0, 0)

    # Profile for target
    profile = get_profile()
    targets = calc_tdee(profile)
    target_cal_week = targets['target_calories'] * 7
    cal_adherence = round(cal_eaten / target_cal_week * 100, 1) if target_cal_week else None

    # Habits
    habit_stats = get_habit_stats()
    total_habits = len(habit_stats['habits'])
    habit_done_count = sum(len(h['done_dates']) for h in habit_stats['habits'])
    habit_possible = total_habits * 7
    habit_pct = round(habit_done_count / habit_possible * 100, 1) if habit_possible else None

    # Top symptoms
    sym_rows = execute("""SELECT name, COUNT(*) as cnt FROM symptoms
                          WHERE date_key >= ? AND date_key <= ?
                          GROUP BY name ORDER BY cnt DESC LIMIT 5""",
                       (week_start, today_iso_v), fetchall=True)
    top_symptoms = [{'name': r['name'], 'count': r['cnt']} for r in sym_rows]

    # Body metrics
    bm = execute("SELECT weight_kg,bmi FROM body_metrics WHERE date_key >= ? ORDER BY date_key DESC LIMIT 1",
                 (week_start,), fetchone=True)

    # Hydration avg
    hyd = execute("""SELECT AVG(daily_total) as avg FROM
                     (SELECT date_key, SUM(amount_ml) as daily_total FROM hydration_logs
                      WHERE date_key >= ? AND date_key <= ? GROUP BY date_key)""",
                  (week_start, today_iso_v), fetchone=True)
    avg_hydration = round(hyd['avg'] or 0) if hyd else 0

    # Vitals latest
    vitals_latest = {}
    for vtype in ['blood_pressure','blood_sugar','heart_rate']:
        r = execute("SELECT value1,value2,unit FROM vitals WHERE type=? ORDER BY logged_at DESC LIMIT 1",
                    (vtype,), fetchone=True)
        if r: vitals_latest[vtype] = dict(r)

    return {
        'period': {'start': week_start, 'end': today_iso_v},
        'sleep':   {'avg_hours': avg_sleep, 'avg_quality': avg_sleep_q, 'nights': len(sleep_rows)},
        'fitness': {'workout_days': workout_days, 'calories_burned': cal_burned, 'activities': len(acts)},
        'nutrition':{'calories_eaten': cal_eaten, 'target': targets['target_calories'],
                     'weekly_target': target_cal_week, 'adherence_pct': cal_adherence,
                     'avg_hydration_ml': avg_hydration},
        'habits':  {'total': total_habits, 'completion_pct': habit_pct, 'done_count': habit_done_count},
        'symptoms': top_symptoms,
        'body':    {'weight_kg': bm['weight_kg'] if bm else None, 'bmi': bm['bmi'] if bm else None},
        'vitals':  vitals_latest,
        'profile': {'name': profile.get('name','User'), 'goal': profile.get('goal','maintain')},
    }

# ── Global search ─────────────────────────────────────────────────────────────

def _parse_date_query(query: str):
    """
    Parse natural language date references and return (clean_query, date_filter_sql, date_params).
    Handles: 'last week', 'last monday', 'last tuesday' etc., 'yesterday', 'today',
             'this month', 'last month', specific dates like 'june 3'.
    Returns (stripped_query, date_key_col_expr, [params]) or (query, None, []).
    """
    import datetime as dt, re
    today = dt.date.today()
    q = query.lower().strip()
    date_range = None

    # today / yesterday
    if re.search(r'\btoday\b', q):
        date_range = (today.isoformat(), today.isoformat())
        q = re.sub(r'\btoday\b', '', q).strip()
    elif re.search(r'\byesterday\b', q):
        d = today - dt.timedelta(days=1)
        date_range = (d.isoformat(), d.isoformat())
        q = re.sub(r'\byesterday\b', '', q).strip()

    # last week
    elif re.search(r'\blast week\b', q):
        start = today - dt.timedelta(days=today.weekday()+7)
        end   = start + dt.timedelta(days=6)
        date_range = (start.isoformat(), end.isoformat())
        q = re.sub(r'\blast week\b', '', q).strip()

    # this week
    elif re.search(r'\bthis week\b', q):
        start = today - dt.timedelta(days=today.weekday())
        date_range = (start.isoformat(), today.isoformat())
        q = re.sub(r'\bthis week\b', '', q).strip()

    # this month
    elif re.search(r'\bthis month\b', q):
        start = today.replace(day=1)
        date_range = (start.isoformat(), today.isoformat())
        q = re.sub(r'\bthis month\b', '', q).strip()

    # last month
    elif re.search(r'\blast month\b', q):
        first_this = today.replace(day=1)
        last_prev  = first_this - dt.timedelta(days=1)
        start = last_prev.replace(day=1)
        date_range = (start.isoformat(), last_prev.isoformat())
        q = re.sub(r'\blast month\b', '', q).strip()

    # last <weekday>  e.g. "last tuesday"
    else:
        days_map = {'monday':0,'tuesday':1,'wednesday':2,'thursday':3,
                    'friday':4,'saturday':5,'sunday':6}
        m = re.search(r'\blast (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', q)
        if m:
            target_wd = days_map[m.group(1)]
            delta = (today.weekday() - target_wd) % 7 or 7
            d = today - dt.timedelta(days=delta)
            date_range = (d.isoformat(), d.isoformat())
            q = re.sub(r'\blast ' + m.group(1) + r'\b', '', q).strip()

        # on <weekday>  e.g. "on monday"
        if not date_range:
            m = re.search(r'\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', q)
            if m:
                target_wd = days_map[m.group(1)]
                delta = (today.weekday() - target_wd) % 7
                d = today - dt.timedelta(days=delta)
                date_range = (d.isoformat(), d.isoformat())
                q = re.sub(r'\bon ' + m.group(1) + r'\b', '', q).strip()

    return q.strip() or None, date_range


def global_search(query: str, limit: int = 40) -> dict:
    clean_q, date_range = _parse_date_query(query)
    # If entire query was a date phrase and nothing else, search everything in that range
    text_q = f'%{clean_q.lower()}%' if clean_q else '%'
    results = {'query': query, 'total': 0, 'sections': [], 'date_range': date_range}

    def date_filter(col):
        if not date_range: return '', []
        return f' AND {col} BETWEEN ? AND ?', list(date_range)

    # ── Food logs ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT food_name,date_key,calories,meal_type,quantity_g FROM food_logs"
        f" WHERE (LOWER(food_name) LIKE ? OR LOWER(meal_type) LIKE ?){df}"
        f" ORDER BY date_key DESC LIMIT {limit//4}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'food','label':'Food Logs','icon':'🍽️',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Thoughts ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT id,content,mood,date_key,created_at FROM thoughts"
        f" WHERE LOWER(content) LIKE ?{df}"
        f" ORDER BY created_at DESC LIMIT {limit//5}",
        [text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'thought','label':'Thoughts','icon':'💭',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Symptoms ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT id,name,severity,date_key,time_of_day,notes FROM symptoms"
        f" WHERE (LOWER(name) LIKE ? OR LOWER(notes) LIKE ?){df}"
        f" ORDER BY date_key DESC LIMIT {limit//5}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'symptom','label':'Symptoms','icon':'🩺',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Todos ──
    df, dp = date_filter('created_at')
    rows = execute(
        f"SELECT id,title,notes,status,priority,due_date,created_at FROM todos"
        f" WHERE (LOWER(title) LIKE ? OR LOWER(notes) LIKE ?){df}"
        f" ORDER BY created_at DESC LIMIT {limit//5}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'todo','label':'Tasks','icon':'✅',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Activities ──
    df, dp = date_filter('date')
    rows = execute(
        f"SELECT id,name,type,date,duration,calories,distance FROM fitness_activities"
        f" WHERE (LOWER(name) LIKE ? OR LOWER(type) LIKE ?){df}"
        f" ORDER BY date DESC LIMIT {limit//5}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'activity','label':'Workouts','icon':'🏃',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Medicines ──
    if clean_q:
        rows = execute(
            "SELECT id,name,dosage,unit,frequency FROM medicines"
            " WHERE LOWER(name) LIKE ? AND active=1 ORDER BY name LIMIT 5",
            (text_q,), fetchall=True)
        if rows:
            results['sections'].append({'type':'medicine','label':'Medicines','icon':'💊',
                                        'items':[dict(r) for r in rows]})
            results['total'] += len(rows)

    # ── Reports ──
    df, dp = date_filter('report_date')
    rows = execute(
        f"SELECT id,filename,patient_name,doctor,severity,report_date FROM reports"
        f" WHERE (LOWER(filename) LIKE ? OR LOWER(patient_name) LIKE ? OR LOWER(doctor) LIKE ?){df}"
        f" ORDER BY report_date DESC LIMIT 5",
        [text_q, text_q, text_q] + dp, fetchall=True)
    if rows:
        items = [{'id':r['id'],'filename':r['filename'],'patient':r['patient_name'],
                  'doctor':r['doctor'],'severity':r['severity'],'date':r['report_date']} for r in rows]
        results['sections'].append({'type':'report','label':'Medical Reports','icon':'📋','items':items})
        results['total'] += len(rows)

    return results

# ── Goal progress data ────────────────────────────────────────────────────────

def get_goal_progress() -> dict:
    import datetime as dt
    today = dt.date.today()
    month_start = today.replace(day=1).isoformat()
    week_start  = (today - dt.timedelta(days=6)).isoformat()
    days30_start = (today - dt.timedelta(days=29)).isoformat()

    profile = get_profile()
    targets = calc_tdee(profile)

    # Weight trend (all entries, up to 60 days for chart)
    bm_rows = execute(
        "SELECT date_key,weight_kg,bmi FROM body_metrics WHERE weight_kg IS NOT NULL ORDER BY date_key",
        fetchall=True)
    weight_trend = [{'date':r['date_key'],'weight':r['weight_kg'],'bmi':r['bmi']} for r in bm_rows[-60:]]

    # Workout frequency this month + daily workout presence for chart
    acts_month = execute("SELECT date FROM fitness_activities WHERE date >= ?", (month_start,), fetchall=True)
    workout_days_month = len(set(r['date'] for r in acts_month))
    days_in_month = today.day

    # 30-day daily workout map for mini bar chart
    acts_30 = execute("SELECT date, SUM(calories) as cal FROM fitness_activities WHERE date >= ? GROUP BY date",
                      (days30_start,), fetchall=True)
    workout_map = {r['date']: r['cal'] for r in acts_30}
    daily_workouts = []
    for i in range(29, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily_workouts.append({'date': d, 'cal': workout_map.get(d, 0)})

    # Habit completion this month + per-habit breakdown
    habit_stats = get_habit_stats(30)
    total_habits = len(habit_stats['habits'])
    habit_done = sum(len(h['done_dates']) for h in habit_stats['habits'])
    habit_possible = total_habits * days_in_month
    habit_pct = round(habit_done / habit_possible * 100, 1) if habit_possible else 0
    # Per-habit detail
    habit_detail = []
    for h in habit_stats['habits'][:6]:
        done_this_month = sum(1 for d in h['done_dates'] if d >= month_start)
        pct = round(done_this_month / days_in_month * 100)
        habit_detail.append({'name': h['name'], 'emoji': h['emoji'], 'color': h['color'],
                              'streak': h['streak'], 'pct': pct, 'done': done_this_month})

    # Sleep — 30 days of data
    sleep_rows = execute(
        "SELECT date_key,duration_h,quality FROM sleep_logs WHERE date_key >= ? ORDER BY date_key",
        (days30_start,), fetchall=True)
    sleep_list = [{'date':r['date_key'],'h':r['duration_h'],'q':r['quality']} for r in sleep_rows]
    sleep_7 = [r for r in sleep_list if r['date'] >= week_start]
    avg_sleep_7 = round(sum(r['h'] for r in sleep_7)/len(sleep_7),1) if sleep_7 else None
    avg_sleep_30 = round(sum(r['h'] for r in sleep_list)/len(sleep_list),1) if sleep_list else None

    # Calorie adherence — 30 days
    food_rows = execute(
        "SELECT date_key, SUM(calories) as total FROM food_logs WHERE date_key >= ? GROUP BY date_key",
        (days30_start,), fetchall=True)
    food_map = {r['date_key']: round(r['total'] or 0) for r in food_rows}
    daily_cals = []
    for i in range(29, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily_cals.append({'date': d, 'cal': food_map.get(d, 0)})
    cal_this_week = sum(food_map.get((today - dt.timedelta(days=i)).isoformat(), 0) for i in range(7))
    cal_target_week = targets['target_calories'] * 7
    cal_adherence = round(cal_this_week / cal_target_week * 100, 1) if cal_target_week else 0

    return {
        'profile': profile, 'targets': targets,
        'weight_trend': weight_trend,
        'workouts': {
            'this_month': workout_days_month, 'days_elapsed': days_in_month,
            'frequency_pct': round(workout_days_month/days_in_month*100),
            'daily': daily_workouts
        },
        'habits': {
            'total': total_habits, 'completion_pct': habit_pct,
            'done_count': habit_done, 'detail': habit_detail
        },
        'sleep': {
            'avg_7': avg_sleep_7, 'avg_30': avg_sleep_30,
            'target_hours': 7.5, 'logged_30': len(sleep_list),
            'daily': sleep_list
        },
        'nutrition': {
            'cal_this_week': cal_this_week, 'cal_target': cal_target_week,
            'adherence_pct': cal_adherence, 'daily': daily_cals,
            'target_daily': targets['target_calories']
        },
        'refill_alerts': get_low_stock_medicines(),
    }
