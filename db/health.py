"""
db/health.py — Habit tracker, symptoms diary, vitals log, emergency health card.

"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id


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
    today = dt.date.today()
    today_iso = today.isoformat()
    start28  = (today - dt.timedelta(days=27)).isoformat()   # 28-day calendar
    start7   = (today - dt.timedelta(days=6)).isoformat()    # 7-day bar chart
    start30  = (today - dt.timedelta(days=days-1)).isoformat()

    result = []
    for h in habits:
        logs = execute("SELECT date_key FROM habit_logs WHERE habit_id=? AND date_key >= ? AND done=1",
                       (h['id'], start30), fetchall=True)
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
             float(data['value1']),
             float(data['value2']) if data.get('value2') not in (None,'') else None,
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