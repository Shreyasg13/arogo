"""
db/health.py — Habit tracker, symptoms diary, vitals log, emergency health card.

All queries are scoped to the authenticated user via current_user_id().
"""
import math

from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id, to_num, to_int


def list_habits() -> list:
    rows = execute("SELECT * FROM habits WHERE active=1 AND user_id=? ORDER BY created_at",
                   (current_user_id(),), fetchall=True)
    result = []
    for r in rows:
        d = dict(r)
        d['target_days'] = jload(d.get('target_days','[]'), [])
        result.append(d)
    return result

def create_habit(data: dict) -> dict:
    name = str(data.get('name', '') or '').strip()
    if not name:
        raise ValueError('Habit name is required')
    # target_days must be a JSON list of weekday indices; a stray string/number
    # would round-trip as a non-list and break the schedule read.
    tgt = data.get('target_days', [])
    if not isinstance(tgt, list):
        tgt = []
    hid = new_id()
    execute("""INSERT INTO habits (id,name,emoji,category,target_days,color,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (hid, name[:120], data.get('emoji','⭐'), data.get('category','general'),
             jdump(tgt), data.get('color','#0E8F7E'), now_iso(),
             current_user_id()), commit=True)
    r = execute("SELECT * FROM habits WHERE id=?", (hid,), fetchone=True)
    d = dict(r); d['target_days'] = jload(d.get('target_days','[]'), []); return d

def delete_habit(hid: str):
    uid = current_user_id()
    execute("UPDATE habits SET active=0 WHERE id=? AND user_id=?", (hid, uid), commit=True)
    execute("DELETE FROM habit_logs WHERE habit_id=? AND user_id=?", (hid, uid), commit=True)

def toggle_habit_log(habit_id: str, date_key: str) -> dict:
    uid = current_user_id()
    # Only toggle habits the user owns
    owner = execute("SELECT id FROM habits WHERE id=? AND user_id=?", (habit_id, uid), fetchone=True)
    if not owner:
        return {'done': False}
    r = execute("SELECT * FROM habit_logs WHERE habit_id=? AND date_key=? AND user_id=?",
                (habit_id, date_key, uid), fetchone=True)
    if r:
        execute("DELETE FROM habit_logs WHERE habit_id=? AND date_key=? AND user_id=?",
                (habit_id, date_key, uid), commit=True)
        return {'done': False}
    else:
        # plain INSERT is portable (SQLite + Postgres); the branch above
        # guarantees no row exists for this (habit_id, date_key, user_id)
        execute("INSERT INTO habit_logs (id,habit_id,date_key,done,logged_at,user_id) VALUES (?,?,?,1,?,?)",
                (new_id(), habit_id, date_key, now_iso(), uid), commit=True)
        return {'done': True}

def get_habit_stats(days: int = 30) -> dict:
    import datetime as dt
    uid = current_user_id()
    habits = list_habits()
    today = dt.date.today()
    today_iso = today.isoformat()
    start30  = (today - dt.timedelta(days=days-1)).isoformat()

    result = []
    for h in habits:
        logs = execute("SELECT date_key FROM habit_logs WHERE habit_id=? AND date_key >= ? AND done=1 AND user_id=?",
                       (h['id'], start30, uid), fetchall=True)
        done_dates = {r['date_key'] for r in logs}

        # Streak (consecutive days back from today)
        streak, d = 0, today
        while d.isoformat() in done_dates:
            streak += 1; d -= dt.timedelta(days=1)

        # 7-day history: list of {date, done} for bar chart
        week7 = []
        for i in range(6, -1, -1):
            dk = (today - dt.timedelta(days=i)).isoformat()
            week7.append({'date': dk, 'done': dk in done_dates,
                          'label': (today - dt.timedelta(days=i)).strftime('%a')})

        # 28-day heatmap: list of {date, done}
        cal28 = []
        for i in range(27, -1, -1):
            dk = (today - dt.timedelta(days=i)).isoformat()
            cal28.append({'date': dk, 'done': dk in done_dates})

        result.append({**h,
                       'done_dates':  list(done_dates),
                       'done_today':  today_iso in done_dates,
                       'streak':      streak,
                       'completions': len(done_dates),
                       'week7':       week7,
                       'cal28':       cal28})
    return {'habits': result, 'date': today_iso}

# ── Symptoms ──────────────────────────────────────────────────────────────────

def log_symptom(data: dict) -> dict:
    name = str(data.get('name', '')).strip()
    if not name:
        raise ValueError('Symptom name is required')
    sid = new_id()
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, name[:120], to_int(data.get('severity', 5), 5, lo=1, hi=10),
             data.get('date_key', today_iso()),
             data.get('time_of_day','morning'), data.get('notes',''), now_iso(),
             current_user_id()), commit=True)
    return dict(execute("SELECT * FROM symptoms WHERE id=?", (sid,), fetchone=True))

def get_symptoms(days: int = 14) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM symptoms WHERE date_key >= ? AND user_id=? ORDER BY logged_at DESC",
                   (start, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]

def delete_symptom(sid: str):
    execute("DELETE FROM symptoms WHERE id=? AND user_id=?",
            (sid, current_user_id()), commit=True)

# ── Vitals (BP, Blood Sugar) ──────────────────────────────────────────────────

def log_vital(data: dict) -> dict:
    vtype = str(data.get('type', '')).strip()
    if not vtype:
        raise ValueError('Vital type is required')
    if data.get('value1') in (None, ''):
        raise ValueError('A reading value is required')
    try:
        value1 = float(data['value1'])
    except (TypeError, ValueError):
        raise ValueError('Reading must be a number')
    if not math.isfinite(value1):
        raise ValueError('Reading must be a number')
    value2 = None
    if data.get('value2') not in (None, ''):
        try:
            value2 = float(data['value2'])
        except (TypeError, ValueError):
            raise ValueError('Reading must be a number')
        if not math.isfinite(value2):
            raise ValueError('Reading must be a number')
    vid = new_id()
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,notes,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (vid, data.get('date_key', today_iso()), vtype,
             value1, value2,
             data.get('unit',''), data.get('notes',''), now_iso(),
             current_user_id()), commit=True)
    return dict(execute("SELECT * FROM vitals WHERE id=?", (vid,), fetchone=True))

def get_vitals(vtype: str = None, days: int = 30) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    if vtype:
        rows = execute("SELECT * FROM vitals WHERE type=? AND date_key >= ? AND user_id=? ORDER BY logged_at DESC",
                       (vtype, start, current_user_id()), fetchall=True)
    else:
        rows = execute("SELECT * FROM vitals WHERE date_key >= ? AND user_id=? ORDER BY logged_at DESC",
                       (start, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]

def delete_vital(vid: str):
    execute("DELETE FROM vitals WHERE id=? AND user_id=?",
            (vid, current_user_id()), commit=True)

# ── Emergency Info ────────────────────────────────────────────────────────────

def get_emergency_info() -> dict:
    uid = current_user_id()
    r = execute("SELECT * FROM emergency_info WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if r: return dict(r)
    eid = new_id()
    execute("INSERT INTO emergency_info (id,updated_at,user_id) VALUES (?,?,?)",
            (eid, now_iso(), uid), commit=True)
    return get_emergency_info()

def save_emergency_info(data: dict) -> dict:
    e = get_emergency_info()
    execute("""UPDATE emergency_info SET blood_type=?,allergies=?,conditions=?,medications=?,
               contact1_name=?,contact1_phone=?,contact2_name=?,contact2_phone=?,
               insurance_provider=?,insurance_number=?,updated_at=? WHERE id=? AND user_id=?""",
            (data.get('blood_type',''), data.get('allergies',''), data.get('conditions',''),
             data.get('medications',''), data.get('contact1_name',''), data.get('contact1_phone',''),
             data.get('contact2_name',''), data.get('contact2_phone',''),
             data.get('insurance_provider',''), data.get('insurance_number',''),
             now_iso(), e['id'], current_user_id()), commit=True)
    return get_emergency_info()
