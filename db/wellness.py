"""
db/wellness.py — Thoughts/journal, todos with reminders, hydration, sleep, body metrics.

All queries are scoped to the authenticated user via current_user_id().
"""
from .core import (execute, executemany, jdump, jload, now_iso, today_iso, user_today,
                   new_id, current_user_id, to_num, to_int, valid_date)


MAX_THOUGHTS_PER_DAY = 10

# What was driving a mood. A fixed vocabulary keeps the data analysable (so we
# can surface "exam weeks hit your mood hardest") and the UI tidy. Youth-first,
# India context. Extend deliberately — old rows just won't carry new tags.
MOOD_TRIGGERS = ['study', 'work', 'sleep', 'family', 'friends', 'money',
                 'health', 'relationship', 'future', 'self']


def clean_triggers(raw) -> list:
    """Coerce arbitrary input to a de-duped subset of MOOD_TRIGGERS (order kept)."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    seen, out = set(), []
    for t in raw:
        k = str(t or '').strip().lower()
        if k in MOOD_TRIGGERS and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _row(r):
    """Row → dict with triggers decoded from JSON to a list."""
    d = dict(r)
    d['triggers'] = jload(d['triggers']) if d.get('triggers') else []
    return d


def get_thoughts(date_key: str) -> list:
    rows = execute(
        "SELECT * FROM thoughts WHERE date_key=? AND user_id=? ORDER BY created_at DESC",
        (date_key, current_user_id()), fetchall=True)
    return [_row(r) for r in rows]

def count_thoughts_today(date_key: str) -> int:
    r = execute("SELECT COUNT(*) as n FROM thoughts WHERE date_key=? AND user_id=?",
                (date_key, current_user_id()), fetchone=True)
    return r['n'] if r else 0

def save_thought(content: str, mood: str, date_key: str, triggers=None) -> dict:
    content = str(content or '').strip()
    if not content:
        raise ValueError("Thought content is required")
    if not valid_date(date_key):
        date_key = today_iso()
    if count_thoughts_today(date_key) >= MAX_THOUGHTS_PER_DAY:
        raise ValueError(f"Max {MAX_THOUGHTS_PER_DAY} thoughts per day reached")
    tid = new_id()
    now = now_iso()
    trig = clean_triggers(triggers)
    execute("""INSERT INTO thoughts (id,content,mood,triggers,date_key,created_at,updated_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (tid, content, str(mood or 'neutral'), jdump(trig) if trig else None,
             date_key, now, now, current_user_id()), commit=True)
    return _row(execute("SELECT * FROM thoughts WHERE id=?", (tid,), fetchone=True))

def update_thought(tid: str, content: str, mood: str, triggers=None) -> dict:
    trig = clean_triggers(triggers)
    execute("UPDATE thoughts SET content=?,mood=?,triggers=?,updated_at=? WHERE id=? AND user_id=?",
            (str(content or '').strip(), str(mood or 'neutral'), jdump(trig) if trig else None,
             now_iso(), tid, current_user_id()), commit=True)
    r = execute("SELECT * FROM thoughts WHERE id=? AND user_id=?",
                (tid, current_user_id()), fetchone=True)
    return _row(r) if r else {}


# Moods we treat as "low" for the pattern read. mood values come from the
# composer's emoji scale (see moodEmoji in app.js).
_LOW_MOODS = {'awful', 'sad', 'anxious', 'angry', 'stressed', 'down', 'terrible'}


def get_trigger_patterns(days: int = 30, min_count: int = 3) -> dict:
    """Honest read of which triggers show up most on low-mood entries. Returns
    {'has_data': bool, 'window_days', 'triggers': [{key, low, total}]} — only
    triggers seen at least `min_count` times, most-low-first. Never invents a
    causal claim; the UI frames it as 'shows up with' not 'causes'."""
    rows = get_thoughts_range(days)
    tally = {}
    for r in rows:
        low = str(r.get('mood') or '').lower() in _LOW_MOODS
        for k in (r.get('triggers') or []):
            t = tally.setdefault(k, {'key': k, 'low': 0, 'total': 0})
            t['total'] += 1
            if low:
                t['low'] += 1
    items = [t for t in tally.values() if t['total'] >= min_count]
    items.sort(key=lambda t: (t['low'], t['total']), reverse=True)
    return {'has_data': bool(items), 'window_days': days, 'triggers': items}

def delete_thought(tid: str):
    execute("DELETE FROM thoughts WHERE id=? AND user_id=?",
            (tid, current_user_id()), commit=True)

def get_thoughts_range(days: int = 7) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute(
        "SELECT * FROM thoughts WHERE date_key >= ? AND user_id=? ORDER BY created_at DESC",
        (start, current_user_id()), fetchall=True)
    return [_row(r) for r in rows]

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
    """Record a night's sleep — one entry per night.

    Logging the same date again REPLACES that night rather than stacking a
    duplicate: you sleep once a night, and re-logging is a correction, not a
    second night. Keyed on (user_id, date_key).
    """
    uid      = current_user_id()
    bed      = data.get('bedtime', '') if isinstance(data.get('bedtime'), str) else ''
    wake     = data.get('wake_time', '') if isinstance(data.get('wake_time'), str) else ''
    dur      = _sleep_duration(bed, wake)
    quality  = to_int(data.get('quality', 3), 3, lo=1, hi=5)
    notes    = str(data.get('notes', '') or '')
    # A night is identified by the morning you woke, NOT the bedtime date —
    # otherwise "11pm → 7am" and "1am → 7am" (same night) get different keys,
    # and re-logging one duplicates instead of replacing the other. Prefer the
    # wake date; fall back to bedtime's date, then today. A garbage date_key
    # would orphan the log on a non-navigable day, so it's validated too.
    date_key = data.get('date_key') or (wake[:10] if wake else bed[:10]) or today_iso()
    if not valid_date(date_key):
        for cand in (wake[:10], bed[:10]):
            if valid_date(cand):
                date_key = cand
                break
        else:
            date_key = today_iso()

    existing = execute("SELECT id FROM sleep_logs WHERE date_key=? AND user_id=? LIMIT 1",
                       (date_key, uid), fetchone=True)
    if existing:
        sid = existing['id']
        execute("""UPDATE sleep_logs
                      SET bedtime=?, wake_time=?, duration_h=?, quality=?, notes=?, created_at=?
                    WHERE id=? AND user_id=?""",
                (bed, wake, dur, quality, notes, now_iso(), sid, uid), commit=True)
    else:
        sid = new_id()
        execute("""INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,quality,notes,created_at,user_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (sid, date_key, bed, wake, dur, quality, notes, now_iso(), uid), commit=True)
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
    """The user's most-frequent DELIBERATE water amount — their real glass or
    bottle — so quick-log buttons offer what they actually drink instead of a
    made-up 250ml.

    Only rows with no source_id count, which excludes two kinds of number that
    aren't a container the user chose:

      - auto-credited drinks: a latte's 360ml is not your water bottle.
      - taps on the reminder's quick-log button: that button's amount comes
        from *this function*, so counting the tap as a preference feeds our own
        default straight back in. Five taps of the suggested 250 would then
        outvote four deliberate 500ml logs — the feature defeating its own
        purpose, and laundering a number we invented into "what they drink".
    """
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

    # The goal, in order of how much we actually know:
    #   1. what the user set        → theirs
    #   2. 35ml/kg of their weight  → derived from their body
    #   3. nothing                  → say so
    #
    # It used to fall through to 35 × an assumed 70kg = 2450ml and label that
    # "Goal: 2450ml". The oddly specific number is what sells it — the user
    # assumes we know something about them. We didn't; we'd never asked.
    rs = execute("SELECT water_goal_ml FROM reminder_settings WHERE user_id=? LIMIT 1",
                 (uid,), fetchone=True)
    goal_ml = (rs or {}).get('water_goal_ml') or None
    goal_is_default = False
    if not goal_ml:
        profile = execute("SELECT weight_kg FROM user_profile WHERE user_id=? LIMIT 1",
                          (uid,), fetchone=True)
        weight = (profile or {}).get('weight_kg')
        if weight:
            goal_ml = round(float(weight) * 35)
        else:
            goal_ml = 2450          # a starting point, flagged as not theirs
            goal_is_default = True

    pct = min(round(total / goal_ml * 100), 100) if goal_ml else 0
    return {'logs': logs, 'total_ml': total, 'goal_ml': goal_ml, 'pct': pct,
            'goal_is_default': goal_is_default,
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


# ── Sleep debt & bedtime consistency ─────────────────────────────────────────

def get_sleep_target() -> float:
    """The user's nightly sleep goal in hours, or None if they haven't set one.
    We never invent a target: sleep-debt math is only shown once it's theirs."""
    r = execute("SELECT sleep_goal_h FROM reminder_settings WHERE user_id=? LIMIT 1",
                (current_user_id(),), fetchone=True)
    g = (r or {}).get('sleep_goal_h') if r else None
    try:
        return round(float(g), 1) if g not in (None, '') else None
    except (TypeError, ValueError):
        return None


def set_sleep_target(hours) -> float:
    """Set (or, with None/0, clear) the nightly sleep goal. Clamped to 3–14 h —
    outside that a 'debt' figure would be nonsense rather than useful."""
    uid = current_user_id()
    # A row may not exist yet (settings are lazily created elsewhere); ensure one.
    exists = execute("SELECT id FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if not exists:
        execute("INSERT INTO reminder_settings (id, user_id, updated_at) VALUES (?,?,?)",
                (new_id(), uid, now_iso()), commit=True)
    if hours in (None, '', 0, '0'):
        execute("UPDATE reminder_settings SET sleep_goal_h=NULL WHERE user_id=?", (uid,), commit=True)
        return None
    h = to_num(hours, None)
    if h is None:
        raise ValueError('Sleep goal must be a number')
    h = max(3.0, min(round(float(h), 1), 14.0))
    execute("UPDATE reminder_settings SET sleep_goal_h=? WHERE user_id=?", (h, uid), commit=True)
    return h


def _bedtime_offset_min(bedtime: str):
    """Minutes past 18:00 for a bedtime, wrapping into [0,1440). Anchoring at 6pm
    keeps a normal night's bedtimes on one continuous scale — 23:30 and 00:30 sit
    60 min apart, not ~1380 apart as raw midnight-minutes would make them."""
    try:
        hh = int(bedtime[11:13]); mm = int(bedtime[14:16])
    except (ValueError, IndexError, TypeError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return ((hh * 60 + mm) - 18 * 60) % 1440


def get_sleep_insights(days: int = 14) -> dict:
    """Sleep debt (cumulative shortfall vs the user's target) and bedtime
    consistency (spread of bedtimes) over the recent window.

    Both are None until the inputs exist — no target set, or too few nights —
    rather than a fabricated zero. Debt counts only nights that fell short; a long
    Sunday lie-in doesn't erase a week of short nights the way a simple average
    would.
    """
    import statistics
    target = get_sleep_target()
    logs = get_sleep_logs(days=days)
    nights = [l for l in logs if to_num(l.get('duration_h'), 0) > 0]
    n = len(nights)

    debt_h = None
    avg_dur = None
    short_nights = None
    if n:
        durs = [to_num(l['duration_h'], 0) for l in nights]
        avg_dur = round(sum(durs) / n, 1)
        if target is not None:
            shortfalls = [max(0.0, target - d) for d in durs]
            debt_h = round(sum(shortfalls), 1)
            short_nights = sum(1 for s in shortfalls if s > 0)

    # Bedtime consistency — stdev of bedtime offsets, in minutes. Needs ≥3 nights
    # with a real bedtime to mean anything.
    offsets = [o for o in (_bedtime_offset_min(l.get('bedtime', '')) for l in nights) if o is not None]
    consistency_min = round(statistics.stdev(offsets)) if len(offsets) >= 3 else None
    # A friendly typical bedtime (median offset → clock time), only when we have it.
    typical_bedtime = None
    if offsets:
        med = int(statistics.median(offsets))
        tot = (med + 18 * 60) % 1440
        typical_bedtime = f'{tot // 60:02d}:{tot % 60:02d}'

    return {
        'days': days,
        'nights': n,
        'target_h': target,
        'avg_duration_h': avg_dur,
        'debt_h': debt_h,                 # None if no target; cumulative shortfall
        'short_nights': short_nights,
        'consistency_min': consistency_min,   # stdev of bedtime, minutes (lower = steadier)
        'typical_bedtime': typical_bedtime,
        'has_data': n > 0,
    }

# ── Body Metrics ──────────────────────────────────────────────────────────────

def _opt_num(v, lo=None, hi=None):
    """Coerce an optional numeric field: blank/None stays NULL; anything
    non-numeric also becomes NULL rather than 500ing or poisoning a chart."""
    if v in (None, ''):
        return None
    return to_num(v, 0.0, lo=lo, hi=hi)

def _plausible_weight(raw, coerced):
    """Guard the weight, distinguishing "didn't tell us" from "typo".

    This matters more now that weighing in feeds the calorie target and the
    hydration goal: a fat-fingered 700 would quietly hand someone a budget
    derived from a body nobody has.

      - absent, blank, or non-numeric → None. They didn't give us a weight;
        that's not an error, there's just nothing to record.
      - a real number outside human range → reject and ask them to check,
        rather than clamp it to a number they never typed. (Same call as
        db/health.py's vitals bounds.)
    """
    if raw in (None, ''):
        return None
    try:
        float(raw)
    except (TypeError, ValueError):
        return None                     # garbage reads as "not provided"
    if coerced is not None and not (20 <= coerced <= 400):
        raise ValueError(f'That weight ({coerced:g}kg) looks off — please double-check it.')
    return coerced


def log_body_metric(data: dict) -> dict:
    bid = new_id()
    # Coerce all numerics: a string weight used to TypeError on the BMI math,
    # and negatives/NaN would flow straight into the weight-trend chart.
    w    = _opt_num(data.get('weight_kg'),    lo=0, hi=1000)
    h_cm = _opt_num(data.get('height_cm'),    lo=0, hi=300)
    bf   = _opt_num(data.get('body_fat_pct'), lo=0, hi=100)
    waist= _opt_num(data.get('waist_cm'),     lo=0, hi=500)
    hip  = _opt_num(data.get('hip_cm'),       lo=0, hi=500)
    chest= _opt_num(data.get('chest_cm'),     lo=0, hi=500)
    arm  = _opt_num(data.get('arm_cm'),       lo=0, hi=200)

    w = _plausible_weight(data.get('weight_kg'), w)

    # Height comes from the profile when the caller doesn't send it — and no
    # logging path ever does, which is why bmi was always NULL while the UI
    # dutifully reported "BMI: —" after every weigh-in. The column was dead.
    if not h_cm:
        try:
            from .food import get_profile
            h_cm = _opt_num((get_profile() or {}).get('height_cm'), lo=0, hi=300)
        except Exception:
            h_cm = None
    bmi = round(w / ((h_cm/100)**2), 1) if w and h_cm else None

    # A garbage/missing date_key would orphan the row; default to today.
    date_key = data.get('date_key')
    if not valid_date(date_key):
        date_key = user_today()
    execute("""INSERT INTO body_metrics
                 (id,date_key,weight_kg,body_fat_pct,waist_cm,hip_cm,chest_cm,arm_cm,bmi,notes,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (bid, date_key, w, bf,
             waist, hip, chest, arm, bmi, str(data.get('notes','') or ''), now_iso(),
             current_user_id()), commit=True)

    # Logging your weight should move the things that depend on your weight.
    # body_metrics feeds the trend chart; user_profile.weight_kg feeds the
    # calorie target (calc_tdee) and the hydration goal (35ml/kg). Nothing
    # connected them, so weighing in moved the chart and left every number
    # derived from your body sitting at whatever the profile last said — or at
    # an assumed 70kg if it never said anything.
    #
    # Only for today's entry: backfilling last month's weight shouldn't
    # rewrite what you weigh now.
    if w and date_key == user_today():
        try:
            from .food import update_profile
            update_profile({'weight_kg': w})     # merges; other fields untouched
        except Exception:
            pass

    return dict(execute("SELECT * FROM body_metrics WHERE id=?", (bid,), fetchone=True))

def get_body_metrics(days: int = 30) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM body_metrics WHERE date_key >= ? AND user_id=? ORDER BY date_key",
                   (start, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]


# Girth measurements we trend, in display order.
_MEASURE_FIELDS = [('waist_cm', 'Waist'), ('hip_cm', 'Hip'), ('chest_cm', 'Chest'), ('arm_cm', 'Arm')]


def get_measurement_trends(days: int = 180) -> dict:
    """Change over the window for each body measurement (waist/hip/chest/arm) and
    weight — first logged value vs latest, plus a recomposition read.

    Recomposition = losing inches while holding or gaining weight (fat down,
    muscle up). We only claim it when BOTH a weight series and a waist series
    have >=2 points spanning the window; otherwise recomp is None, not guessed.
    All values are the user's own; a measurement absent from every entry is
    simply omitted.
    """
    import datetime as dt
    uid = current_user_id()
    start = (dt.date.today() - dt.timedelta(days=max(1, days))).isoformat()
    rows = execute("""SELECT * FROM body_metrics WHERE date_key >= ? AND user_id=?
                      ORDER BY date_key ASC, created_at ASC""",
                   (start, uid), fetchall=True) or []

    def _series(field):
        pts = [(r['date_key'], r[field]) for r in rows if r[field] is not None]
        return pts

    trends = []
    for field, label in _MEASURE_FIELDS + [('weight_kg', 'Weight')]:
        pts = _series(field)
        if len(pts) < 2:
            continue
        first_v, last_v = pts[0][1], pts[-1][1]
        change = round(last_v - first_v, 1)
        unit = 'kg' if field == 'weight_kg' else 'cm'
        trends.append({'field': field, 'label': label, 'unit': unit,
                       'first': round(first_v, 1), 'latest': round(last_v, 1),
                       'change': change, 'points': len(pts),
                       'from_date': pts[0][0], 'to_date': pts[-1][0]})

    # Recomposition read — needs both weight and waist series.
    recomp = None
    wser, waister = _series('weight_kg'), _series('waist_cm')
    if len(wser) >= 2 and len(waister) >= 2:
        dw = wser[-1][1] - wser[0][1]
        dwaist = waister[-1][1] - waister[0][1]
        if dwaist <= -1 and dw >= -0.5:
            # waist down meaningfully while weight held or rose
            recomp = {'kind': 'recomp', 'weight_change': round(dw, 1), 'waist_change': round(dwaist, 1)}
        elif dwaist <= -1 and dw <= -1:
            recomp = {'kind': 'fat_loss', 'weight_change': round(dw, 1), 'waist_change': round(dwaist, 1)}

    return {'days': days, 'trends': trends, 'recomp': recomp, 'has_data': bool(trends)}
