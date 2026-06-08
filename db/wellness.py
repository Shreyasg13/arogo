"""
db/wellness.py — Thoughts/journal, todos with reminders, hydration, sleep, body metrics.

"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id


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

# ── Sleep ─────────────────────────────────────────────────────────────────────

def _sleep_duration(bedtime: str, wake_time: str) -> float:
    try:
        import datetime as dt
        fmt  = '%Y-%m-%dT%H:%M'
        bed  = dt.datetime.strptime(bedtime[:16],  fmt)
        wake = dt.datetime.strptime(wake_time[:16], fmt)
        if wake < bed:
            wake += dt.timedelta(days=1)
        return round((wake - bed).seconds / 3600, 2)
    except Exception:
        return 0.0

def log_sleep(data: dict) -> dict:
    sid      = new_id()
    bed      = data.get('bedtime', '')
    wake     = data.get('wake_time', '')
    dur      = _sleep_duration(bed, wake)
    date_key = data.get('date_key') or (bed[:10] if bed else today_iso())
    execute("""INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,quality,notes,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, date_key, bed, wake, dur,
             int(data.get('quality', 3)), data.get('notes', ''), now_iso()), commit=True)
    return dict(execute("SELECT * FROM sleep_logs WHERE id=?", (sid,), fetchone=True))

# ── Body Metrics ──────────────────────────────────────────────────────────────

# ── Habits ────────────────────────────────────────────────────────────────────

def log_hydration(amount_ml: int, drink_type: str, date_key: str) -> dict:
    hid = new_id()
    execute("""INSERT INTO hydration_logs (id,amount_ml,drink_type,date_key,logged_at)
               VALUES (?,?,?,?,?)""", (hid, amount_ml, drink_type, date_key, now_iso()), commit=True)
    return dict(execute("SELECT * FROM hydration_logs WHERE id=?", (hid,), fetchone=True))

def get_hydration_day(date_key: str) -> dict:
    rows = execute("SELECT * FROM hydration_logs WHERE date_key=? ORDER BY logged_at", (date_key,), fetchall=True)
    logs = [dict(r) for r in rows]
    total = sum(r['amount_ml'] for r in logs)
    # Calculate goal from profile (35ml per kg body weight, default 2450ml)
    profile = execute("SELECT weight_kg FROM user_profile LIMIT 1", fetchone=True)
    weight  = float((profile or {}).get('weight_kg') or 70)
    goal_ml = round(weight * 35)
    pct     = min(round(total / goal_ml * 100), 100) if goal_ml else 0
    return {'logs': logs, 'total_ml': total, 'goal_ml': goal_ml, 'pct': pct, 'date': date_key}

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