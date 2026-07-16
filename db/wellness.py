"""
db/wellness.py — Thoughts/journal, todos with reminders, hydration, sleep, body metrics.

All queries are scoped to the authenticated user via current_user_id().
"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id, to_num, to_int, valid_date


MAX_THOUGHTS_PER_DAY = 10

def get_thoughts(date_key: str) -> list:
    rows = execute(
        "SELECT * FROM thoughts WHERE date_key=? AND user_id=? ORDER BY created_at DESC",
        (date_key, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]

def count_thoughts_today(date_key: str) -> int:
    r = execute("SELECT COUNT(*) as n FROM thoughts WHERE date_key=? AND user_id=?",
                (date_key, current_user_id()), fetchone=True)
    return r['n'] if r else 0

def save_thought(content: str, mood: str, date_key: str) -> dict:
    content = str(content or '').strip()
    if not content:
        raise ValueError("Thought content is required")
    if not valid_date(date_key):
        date_key = today_iso()
    if count_thoughts_today(date_key) >= MAX_THOUGHTS_PER_DAY:
        raise ValueError(f"Max {MAX_THOUGHTS_PER_DAY} thoughts per day reached")
    tid = new_id()
    now = now_iso()
    execute("""INSERT INTO thoughts (id,content,mood,date_key,created_at,updated_at,user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (tid, content, str(mood or 'neutral'), date_key, now, now, current_user_id()), commit=True)
    return dict(execute("SELECT * FROM thoughts WHERE id=?", (tid,), fetchone=True))

def update_thought(tid: str, content: str, mood: str) -> dict:
    execute("UPDATE thoughts SET content=?,mood=?,updated_at=? WHERE id=? AND user_id=?",
            (str(content or '').strip(), str(mood or 'neutral'), now_iso(), tid, current_user_id()), commit=True)
    r = execute("SELECT * FROM thoughts WHERE id=? AND user_id=?",
                (tid, current_user_id()), fetchone=True)
    return dict(r) if r else {}

def delete_thought(tid: str):
    execute("DELETE FROM thoughts WHERE id=? AND user_id=?",
            (tid, current_user_id()), commit=True)

def get_thoughts_range(days: int = 7) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute(
        "SELECT * FROM thoughts WHERE date_key >= ? AND user_id=? ORDER BY created_at DESC",
        (start, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]

# ── Todos ─────────────────────────────────────────────────────────────────────

def list_todos(status: str = None) -> list:
    if status:
        rows = execute(
            "SELECT * FROM todos WHERE status=? AND user_id=? ORDER BY priority DESC, due_date ASC, created_at DESC",
            (status, current_user_id()), fetchall=True)
    else:
        rows = execute(
            "SELECT * FROM todos WHERE user_id=? ORDER BY status ASC, priority DESC, due_date ASC, created_at DESC",
            (current_user_id(),), fetchall=True)
    result = []
    for r in rows:
        d = dict(r)
        d['tags'] = jload(d.get('tags', '[]'), [])
        result.append(d)
    return result

def _todo_tags(v):
    """Tags must be a JSON list. A stray string/number would be stored and
    then re-read as a non-list, breaking the UI's tag iteration."""
    return jdump(v if isinstance(v, list) else [])

def create_todo(data: dict) -> dict:
    title = str(data.get('title', '') or '').strip()
    if not title:
        raise ValueError("Todo title is required")
    tid = new_id()
    now = now_iso()
    execute("""INSERT INTO todos
               (id,title,notes,priority,status,due_date,reminder_at,tags,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (tid, title, str(data.get('notes','') or ''),
             str(data.get('priority','medium') or 'medium'), 'pending',
             data.get('due_date') or None, data.get('reminder_at') or None,
             _todo_tags(data.get('tags',[])), now, current_user_id()), commit=True)
    r = execute("SELECT * FROM todos WHERE id=?", (tid,), fetchone=True)
    d = dict(r)
    d['tags'] = jload(d.get('tags','[]'), [])
    return d

def update_todo(tid: str, data: dict) -> dict:
    title = str(data.get('title', '') or '').strip()
    if not title:
        raise ValueError("Todo title is required")
    execute("""UPDATE todos SET title=?,notes=?,priority=?,due_date=?,
               reminder_at=?,tags=? WHERE id=? AND user_id=?""",
            (title, str(data.get('notes','') or ''),
             str(data.get('priority','medium') or 'medium'), data.get('due_date') or None,
             data.get('reminder_at') or None,
             _todo_tags(data.get('tags',[])), tid, current_user_id()), commit=True)
    r = execute("SELECT * FROM todos WHERE id=? AND user_id=?",
                (tid, current_user_id()), fetchone=True)
    if not r: return {}
    d = dict(r)
    d['tags'] = jload(d.get('tags','[]'), [])
    return d

def toggle_todo(tid: str) -> dict:
    r = execute("SELECT status FROM todos WHERE id=? AND user_id=?",
                (tid, current_user_id()), fetchone=True)
    if not r: return {}
    new_status = 'done' if r['status'] == 'pending' else 'pending'
    completed = now_iso() if new_status == 'done' else None
    execute("UPDATE todos SET status=?,completed_at=? WHERE id=? AND user_id=?",
            (new_status, completed, tid, current_user_id()), commit=True)
    r2 = execute("SELECT * FROM todos WHERE id=?", (tid,), fetchone=True)
    d = dict(r2)
    d['tags'] = jload(d.get('tags','[]'), [])
    return d

def delete_todo(tid: str):
    execute("DELETE FROM todos WHERE id=? AND user_id=?",
            (tid, current_user_id()), commit=True)

def get_due_reminders() -> list:
    """Return todos with reminder_at <= now that haven't been sent."""
    now = now_iso()[:16]  # YYYY-MM-DDTHH:MM
    rows = execute(
        "SELECT * FROM todos WHERE reminder_at IS NOT NULL AND reminder_at <= ? AND reminder_sent=0 AND status='pending' AND user_id=?",
        (now, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]

def mark_reminder_sent(tid: str):
    execute("UPDATE todos SET reminder_sent=1 WHERE id=? AND user_id=?",
            (tid, current_user_id()), commit=True)


# ── Sleep helpers ─────────────────────────────────────────────────────────────

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
    bed      = data.get('bedtime', '') if isinstance(data.get('bedtime'), str) else ''
    wake     = data.get('wake_time', '') if isinstance(data.get('wake_time'), str) else ''
    dur      = _sleep_duration(bed, wake)
    # A garbage date_key would orphan the log on a non-navigable day; fall back
    # to the bedtime's date, then today. Quality is coerced/clamped (1..5) so a
    # non-numeric or out-of-range value can't 500 or poison the trend view.
    date_key = data.get('date_key') or (bed[:10] if bed else today_iso())
    if not valid_date(date_key):
        date_key = bed[:10] if valid_date(bed[:10]) else today_iso()
    execute("""INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,quality,notes,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sid, date_key, bed, wake, dur,
             to_int(data.get('quality', 3), 3, lo=1, hi=5),
             str(data.get('notes', '') or ''), now_iso(),
             current_user_id()), commit=True)
    return dict(execute("SELECT * FROM sleep_logs WHERE id=?", (sid,), fetchone=True))

# ── Hydration ─────────────────────────────────────────────────────────────────

def log_hydration(amount_ml: int, drink_type: str, date_key: str,
                  source_id: str = None) -> dict:
    # Coerce & clamp: a non-numeric amount would otherwise brick the whole
    # day view (sum() over a mix of ints and strings raises forever).
    # `source_id` links an auto-credited drink back to the food log it came
    # from, so deleting that food log removes the credit too.
    amount_ml = to_int(amount_ml, default=250, lo=0, hi=10000)
    hid = new_id()
    execute("""INSERT INTO hydration_logs
                 (id,amount_ml,drink_type,date_key,logged_at,user_id,source_id)
               VALUES (?,?,?,?,?,?,?)""",
            (hid, amount_ml, drink_type, date_key, now_iso(), current_user_id(),
             source_id), commit=True)
    return dict(execute("SELECT * FROM hydration_logs WHERE id=?", (hid,), fetchone=True))

def usual_sip_ml(uid: str = None, default: int = 250) -> int:
    """The user's most-frequent deliberate water amount — i.e. their real glass
    or bottle — so quick-log buttons offer what they actually drink instead of
    a made-up 250ml. Auto-credited drinks (source_id set) are excluded: a
    latte's 360ml is not your water container."""
    try:
        r = execute("""SELECT amount_ml, COUNT(*) AS n FROM hydration_logs
                       WHERE user_id=? AND amount_ml > 0 AND source_id IS NULL
                       GROUP BY amount_ml ORDER BY n DESC, amount_ml DESC""",
                    (uid or current_user_id(),), fetchone=True)
        if r and r['amount_ml']:
            return max(50, min(int(r['amount_ml']), 2000))
    except Exception:
        pass
    return default


def get_hydration_day(date_key: str) -> dict:
    uid = current_user_id()
    rows = execute("SELECT * FROM hydration_logs WHERE date_key=? AND user_id=? ORDER BY logged_at",
                   (date_key, uid), fetchall=True)
    logs = [dict(r) for r in rows]
    total = sum(to_num(r.get('amount_ml'), 0) for r in logs)
    # Calculate goal from profile (35ml per kg body weight, default 2450ml)
    profile = execute("SELECT weight_kg FROM user_profile WHERE user_id=? LIMIT 1",
                      (uid,), fetchone=True)
    weight  = float((profile or {}).get('weight_kg') or 70)
    goal_ml = round(weight * 35)
    pct     = min(round(total / goal_ml * 100), 100) if goal_ml else 0
    return {'logs': logs, 'total_ml': total, 'goal_ml': goal_ml, 'pct': pct,
            'date': date_key, 'usual_ml': usual_sip_ml(uid)}

def delete_hydration_log(lid: str):
    execute("DELETE FROM hydration_logs WHERE id=? AND user_id=?",
            (lid, current_user_id()), commit=True)

def get_hydration_week(days: int = 7) -> list:
    import datetime as dt
    uid = current_user_id()
    result = []
    for i in range(days-1, -1, -1):
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        rows = execute("SELECT SUM(amount_ml) as total FROM hydration_logs WHERE date_key=? AND user_id=?",
                       (d, uid), fetchone=True)
        result.append({'date': d, 'total_ml': rows['total'] or 0})
    return result

# ── Sleep ─────────────────────────────────────────────────────────────────────

def get_sleep_logs(days: int = 14) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM sleep_logs WHERE date_key >= ? AND user_id=? ORDER BY date_key DESC",
                   (start, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]

def delete_sleep_log(lid: str):
    execute("DELETE FROM sleep_logs WHERE id=? AND user_id=?",
            (lid, current_user_id()), commit=True)

# ── Body Metrics ──────────────────────────────────────────────────────────────

def _opt_num(v, lo=None, hi=None):
    """Coerce an optional numeric field: blank/None stays NULL; anything
    non-numeric also becomes NULL rather than 500ing or poisoning a chart."""
    if v in (None, ''):
        return None
    return to_num(v, 0.0, lo=lo, hi=hi)

def log_body_metric(data: dict) -> dict:
    bid = new_id()
    # Coerce all numerics: a string weight used to TypeError on the BMI math,
    # and negatives/NaN would flow straight into the weight-trend chart.
    w    = _opt_num(data.get('weight_kg'),    lo=0, hi=1000)
    h_cm = _opt_num(data.get('height_cm'),    lo=0, hi=300)
    bf   = _opt_num(data.get('body_fat_pct'), lo=0, hi=100)
    waist= _opt_num(data.get('waist_cm'),     lo=0, hi=500)
    bmi = round(w / ((h_cm/100)**2), 1) if w and h_cm else None
    # A garbage/missing date_key would orphan the row; default to today.
    date_key = data.get('date_key')
    if not valid_date(date_key):
        date_key = today_iso()
    execute("""INSERT INTO body_metrics (id,date_key,weight_kg,body_fat_pct,waist_cm,bmi,notes,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (bid, date_key, w, bf,
             waist, bmi, str(data.get('notes','') or ''), now_iso(),
             current_user_id()), commit=True)
    return dict(execute("SELECT * FROM body_metrics WHERE id=?", (bid,), fetchone=True))

def get_body_metrics(days: int = 30) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM body_metrics WHERE date_key >= ? AND user_id=? ORDER BY date_key",
                   (start, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]
