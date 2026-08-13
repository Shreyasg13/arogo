"""
db/medicines.py — Medicine tracker, dose logging, refill/stock management.

All queries are scoped to the authenticated user via current_user_id().
"""
import re

from .core import (execute, executemany, jdump, jload, now_iso, today_iso, user_today,
                   valid_date, new_id, current_user_id)

_TIME_RE = re.compile(r'^([01]?\d|2[0-3]):[0-5]\d$')

# Per-dose timing instructions. Keys are stored; labels are shown. 'with_food'
# stays in step with the older boolean with_food flag for backward compatibility.
TIMING_LABELS = {
    '':              '',
    'with_food':     'with food',
    'before_food':   'before food',
    'after_food':    'after food',
    'empty_stomach': 'on an empty stomach',
    'bedtime':       'at bedtime',
    'with_water':    'with plenty of water',
}


def timing_label(key) -> str:
    """Human label for a timing key ('' for none / unknown)."""
    return TIMING_LABELS.get((key or '').strip(), '')


def _clean_times(raw):
    """Coerce a submitted `times` value into a list of valid HH:MM strings.

    Guards against the class of bugs where a scalar string (e.g. '08:00') is
    stored as JSON and later iterated character-by-character in the today view.
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return ['08:00']
    out = []
    for t in raw:
        if not isinstance(t, str):
            continue
        t = t.strip()
        # Normalise single-digit hour ("8:00" -> "08:00")
        if _TIME_RE.match(t):
            h, m = t.split(':')
            out.append(f'{int(h):02d}:{m}')
    # De-dupe while preserving order; cap to a sane maximum
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:24] or ['08:00']


# ── Medicine history (a dated record of what changed) ────────────────────────
_EVENT_KINDS = {'started', 'stopped', 'resumed', 'deleted', 'restocked'}


def log_medicine_event(medicine_id, kind, med_name='', detail=''):
    """Record a change to a medicine so the user (and a doctor) can see what
    changed and when. Best-effort — a history-logging failure must never break
    the underlying action."""
    if kind not in _EVENT_KINDS:
        return
    try:
        execute("""INSERT INTO medicine_events (id,medicine_id,med_name,kind,detail,at,user_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (new_id(), medicine_id, (med_name or '')[:120], kind,
                 str(detail or '')[:200], now_iso(), current_user_id()), commit=True)
    except Exception:
        pass


def get_medicine_events(days: int = 365, limit: int = 100) -> list:
    uid = current_user_id()
    from datetime import date, timedelta
    days = max(1, min(int(days or 365), 3650))
    limit = max(1, min(int(limit or 100), 500))
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = execute("""SELECT * FROM medicine_events WHERE user_id=? AND at>=?
                      ORDER BY at DESC LIMIT ?""", (uid, since, limit), fetchall=True) or []
    return [dict(r) for r in rows]


def insert_medicine(data: dict) -> dict:
    name = str(data.get('name', '')).strip()
    if not name:
        raise ValueError('Medicine name is required')
    mid = new_id()
    # Timing is the richer instruction; keep with_food in step with it (and honour
    # a bare with_food flag from older clients that don't send `timing`).
    timing = (data.get('timing') or '').strip()
    if timing not in TIMING_LABELS:
        timing = ''
    if not timing and data.get('with_food'):
        timing = 'with_food'
    with_food = 1 if timing == 'with_food' else 0
    try:
        lead = max(0, min(int(data.get('reminder_lead_min') or 0), 120))
    except (TypeError, ValueError):
        lead = 0
    # Optional monthly cost — None (not 0) when the user leaves it blank, so an
    # unpriced medicine doesn't distort the "you spend ₹0" reading.
    cost = data.get('cost')
    if cost in (None, ''):
        cost = None
    else:
        try:
            cost = round(max(0.0, float(cost)), 2)
        except (TypeError, ValueError):
            cost = None
    # Repeat schedule. As-needed meds have none. Otherwise a med repeats EITHER on
    # an N-day cycle OR on fixed weekdays, never both — interval wins if sent.
    interval = None if data.get('frequency') == 'as_needed' else clean_interval_days(data.get('interval_days'))
    sched = None if (interval or data.get('frequency') == 'as_needed') else clean_schedule_days(data.get('schedule_days'))
    # The icon is rendered into innerHTML in several places; keep it a short,
    # markup-free glyph so a crafted value can't inject HTML (defence at source).
    raw_icon = str(data.get('icon') or '💊')
    icon = raw_icon[:8] if ('<' not in raw_icon and '>' not in raw_icon) else '💊'
    icon = icon or '💊'
    execute("""
        INSERT INTO medicines
          (id,name,dosage,unit,frequency,times,with_food,timing,reminder_lead_min,cost,notes,purpose,color,icon,start_date,end_date,schedule_days,interval_days,active,created_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
    """, (mid, name[:120], str(data.get('dosage', '')).strip()[:60], data.get('unit','mg'),
          data.get('frequency','once_daily'),
          jdump([] if data.get('frequency') == 'as_needed'
                else _clean_times(data.get('times', ['08:00']))),
          with_food, timing, lead, cost, data.get('notes',''),
          str(data.get('purpose', '')).strip()[:120],
          data.get('color','teal'), icon,
          data.get('start_date', today_iso()), data.get('end_date',''),
          jdump(sched) if sched else None, interval, now_iso(),
          current_user_id()),
        commit=True)
    log_medicine_event(mid, 'started', name)
    return get_medicine(mid)


def get_medicine(mid):
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?",
                (mid, current_user_id()), fetchone=True)
    return _fmt_med(r) if r else None


def list_medicines():
    uid = current_user_id()
    rows = execute("SELECT * FROM medicines WHERE user_id=? ORDER BY created_at DESC",
                   (uid,), fetchall=True)
    # Today's taken count + last-taken time per medicine — lets the card show
    # "Taken 2× today · last 2:37 PM", especially for as-needed meds.
    today = user_today()
    taken = {}
    for r in (execute("""SELECT medicine_id, COUNT(*) c, MAX(taken_at) last
                         FROM dose_logs WHERE user_id=? AND date_key=? AND taken=1
                         GROUP BY medicine_id""", (uid, today), fetchall=True) or []):
        taken[r['medicine_id']] = {'count': r['c'], 'last': r['last']}
    out = []
    for r in rows:
        m = _fmt_med(r)
        t = taken.get(m['id'], {})
        m['taken_today'] = t.get('count', 0)
        m['last_taken'] = t.get('last', '')
        out.append(m)
    return out


def _user_now_hm():
    """Current HH:MM:SS in the user's timezone (server fallback)."""
    import datetime as dt
    try:
        from db.food import get_user_timezone
        tz = get_user_timezone()
        if tz:
            import zoneinfo
            return dt.datetime.now(zoneinfo.ZoneInfo(tz)).strftime('%H:%M:%S')
    except Exception:
        pass
    return dt.datetime.now().strftime('%H:%M:%S')


def log_prn_dose(med_id: str) -> dict:
    """Log a one-off, unscheduled ('as needed') dose taken right now. The time_key
    carries seconds so it never collides with a scheduled HH:MM slot — which also
    keeps it out of the scheduled-adherence math (a rescue dose isn't a missed one)."""
    uid = current_user_id()
    if not execute("SELECT id FROM medicines WHERE id=? AND user_id=?", (med_id, uid), fetchone=True):
        return {}
    date_key, time_key = user_today(), _user_now_hm()
    log_dose(med_id, date_key, time_key, taken=True)     # reuses stock decrement
    row = execute("""SELECT COUNT(*) c, MAX(taken_at) last FROM dose_logs
                     WHERE user_id=? AND medicine_id=? AND date_key=? AND taken=1""",
                  (uid, med_id, date_key), fetchone=True)
    return {'taken_today': row['c'] if row else 1,
            'last_taken': row['last'] if row else now_iso(),
            'time': time_key[:5]}


def toggle_medicine(mid):
    uid = current_user_id()
    prev = execute("SELECT name, active FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    execute("UPDATE medicines SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=? AND user_id=?",
            (mid, uid), commit=True)
    if prev:
        # 'stopped' if it was active before the flip, else 'resumed'.
        log_medicine_event(mid, 'stopped' if prev['active'] else 'resumed', prev['name'])


def delete_medicine(mid):
    uid = current_user_id()
    prev = execute("SELECT name FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    execute("DELETE FROM medicines WHERE id=? AND user_id=?", (mid, uid), commit=True)
    if prev:
        log_medicine_event(mid, 'deleted', prev['name'])


def clean_schedule_days(raw):
    """Normalise a day-of-week schedule to a sorted list of unique ints 0–6
    (Mon=0 … Sun=6). Anything empty, all-seven, or invalid → None, meaning
    'every day' — so the storage layer never carries a redundant [0..6] and the
    'is it due today' check can treat None as the fast daily path."""
    if not raw:
        return None
    try:
        days = sorted({int(x) for x in raw if 0 <= int(x) <= 6})
    except (TypeError, ValueError):
        return None
    if not days or len(days) == 7:
        return None
    return days


def clean_interval_days(raw):
    """Normalise an N-day cycle to an int in [2, 60], or None (not interval-based).
    1 would just be 'daily', so it collapses to None."""
    if raw in (None, '', 0, 1):
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if 2 <= n <= 60 else None


def _fmt_med(r):
    d = dict(r)
    d['times'] = jload(d.get('times', '["08:00"]'), ['08:00'])
    d['with_food'] = bool(d.get('with_food', 0))
    d['active'] = bool(d.get('active', 1))
    d['timing'] = (d.get('timing') or '')
    d['timing_text'] = timing_label(d['timing'])
    # None = daily; otherwise a list of weekday ints (Mon=0 … Sun=6).
    d['schedule_days'] = clean_schedule_days(jload(d.get('schedule_days'), None))
    # None = not interval-based; otherwise an N-day cycle from start_date.
    d['interval_days'] = clean_interval_days(d.get('interval_days'))
    return d


# ── Dose Logs ────────────────────────────────────────────────────────────────

# Reasons a dose can be skipped — a small closed set so the summary can count
# them. 'other' is the catch-all; anything unrecognised is dropped to None.
SKIP_REASONS = ('forgot', 'away', 'side_effect', 'ran_out', 'felt_ok', 'other')


def log_dose(medicine_id, date_key, time_key, taken=True, reason=None):
    uid = current_user_id()
    # Only log doses against medicines the user owns
    owner = execute("SELECT id FROM medicines WHERE id=? AND user_id=?",
                    (medicine_id, uid), fetchone=True)
    if not owner:
        return False
    lid = new_id()
    new_taken = bool(taken)
    # A reason only means anything on a SKIP; a taken dose clears it.
    skip_reason = None
    if not new_taken:
        r = str(reason or '').strip().lower()
        skip_reason = r if r in SKIP_REASONS else None
    # Upsert
    existing = execute(
        "SELECT id, taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
        (medicine_id, date_key, time_key, uid), fetchone=True)
    prev_taken = bool(existing and existing['taken'])
    if existing:
        execute("UPDATE dose_logs SET taken=?, taken_at=?, skip_reason=? WHERE id=?",
                (1 if new_taken else 0, now_iso(), skip_reason, existing['id']), commit=True)
    else:
        execute("""
            INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at,user_id,skip_reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (lid, medicine_id, date_key, time_key, 1 if new_taken else 0, now_iso(), uid, skip_reason),
            commit=True)
    # Keep pill stock honest: consume on a fresh "taken", restore on un-take.
    # Guarded on the state *transition* so a double-log never double-counts,
    # and on the recorded ledger so an un-take restores exactly what the take
    # removed — never more. Restoring blind is how the count invented pills.
    row_id = existing['id'] if existing else lid
    if new_taken and not prev_taken:
        applied = _consume_stock(medicine_id)
        execute("UPDATE dose_logs SET pills_applied=? WHERE id=? AND user_id=?",
                (applied, row_id, uid), commit=True)
    elif prev_taken and not new_taken:
        _restore_stock(medicine_id, _pills_applied(row_id, uid))
        execute("UPDATE dose_logs SET pills_applied=0 WHERE id=? AND user_id=?",
                (row_id, uid), commit=True)
    if new_taken:      # a taken dose shouldn't re-fire a snoozed reminder
        execute("DELETE FROM dose_snoozes WHERE med_id=? AND date_key=? AND time_key=? AND user_id=?",
                (medicine_id, date_key, time_key, uid), commit=True)
    return True


def _in_course(m, day):
    """True if `day` (ISO date) falls within a medicine's active course.

    start_date defaults to the creation day; an empty end_date means ongoing.
    Used so the today view and adherence math ignore days before the medicine
    existed and days after a finished course.
    """
    start = m.get('start_date') or ''
    end = m.get('end_date') or ''
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _scheduled_on_day(m, day):
    """True if the medicine is actually due on `day` (ISO date): within its
    course window AND — when it has a day-of-week schedule — this weekday is one
    of the chosen days. schedule_days is None for the common daily case, so that
    path costs nothing. This is what stops a weekly med from showing as due (and
    firing a reminder) all seven days."""
    if not _in_course(m, day):
        return False
    from datetime import date
    iv = m.get('interval_days')
    if iv:
        # Due every N days counting from the course start (alternate-day = 2).
        try:
            start = m.get('start_date') or day
            delta = (date.fromisoformat(day) - date.fromisoformat(start)).days
            return delta >= 0 and delta % iv == 0
        except (ValueError, TypeError):
            return True   # a bad date should never silently hide a real dose
    sd = m.get('schedule_days')
    if not sd:
        return True
    try:
        return date.fromisoformat(day).weekday() in sd
    except (ValueError, TypeError):
        return True   # a bad date should never silently hide a real dose


def get_today_doses():
    uid = current_user_id()
    # The user's day, not the server's — the app and service worker write dose
    # rows keyed to the device's local date, and this is what reads them back.
    today = user_today()
    meds = [m for m in list_medicines() if m['active'] and _scheduled_on_day(m, today)]
    doses = []
    for m in meds:
        for t in m.get('times', []):
            log = execute(
                "SELECT * FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
                (m['id'], today, t, uid), fetchone=True)
            doses.append({
                'med_id': m['id'], 'med_name': m['name'], 'dosage': m['dosage'],
                'unit': m['unit'], 'time': t, 'icon': m.get('icon', '💊'),
                'color': m.get('color', 'teal'), 'with_food': m.get('with_food', False),
                'timing': m.get('timing', ''), 'timing_text': m.get('timing_text', ''),
                'reminder_lead_min': m.get('reminder_lead_min') or 0,
                'purpose': m.get('purpose', ''),
                'taken': bool(log and log.get('taken')),
                'taken_at': log['taken_at'] if log else ''
            })
    doses.sort(key=lambda x: x['time'])
    return doses


def get_adherence_stats(days=30):
    """Compute adherence % over the past N days."""
    from datetime import date, timedelta
    uid = current_user_id()
    total, taken = 0, 0
    meds = list_medicines()
    for i in range(max(0, days)):
        d = (date.today() - timedelta(days=i)).isoformat()
        for m in meds:
            if not m['active']: continue
            if not _scheduled_on_day(m, d): continue   # skip days the med isn't due (course + weekday)
            for t in m.get('times', []):
                total += 1
                log = execute(
                    "SELECT taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
                    (m['id'], d, t, uid), fetchone=True)
                if log and log.get('taken'): taken += 1
    return {'total': total, 'taken': taken, 'pct': round(taken/total*100, 1) if total else 0}


# The part of the day a dose slot falls in. A reading of the clock only — the
# labels are for grouping, not clinical claims.
_TOD_BUCKETS = [
    ('morning',   'Morning',   5, 12),   # 05:00–11:59
    ('afternoon', 'Afternoon', 12, 17),  # 12:00–16:59
    ('evening',   'Evening',   17, 21),  # 17:00–20:59
    ('night',     'Night',     21, 5),   # 21:00–04:59 (wraps midnight)
]


def _time_bucket(time_key: str) -> str:
    try:
        h = int(str(time_key)[:2])
    except (ValueError, TypeError):
        return 'morning'
    for key, _lbl, lo, hi in _TOD_BUCKETS:
        if lo < hi:
            if lo <= h < hi:
                return key
        else:                       # night wraps midnight
            if h >= lo or h < hi:
                return key
    return 'morning'


def get_adherence_by_timeofday(days: int = 30) -> dict:
    """Per-part-of-day miss rate over the window — which dose slot the user
    actually struggles with. Same scheduling rules as get_adherence_stats, but
    grouped by morning/afternoon/evening/night. The taken flags are prefetched in
    one query so a 30-day span isn't hundreds of round-trips.

    'worst' names the bucket with the lowest adherence among those with enough
    scheduled doses to be meaningful (>= _TOD_MIN); None if none qualify — we
    don't crown a 'worst' off one or two doses."""
    from datetime import date, timedelta
    uid = current_user_id()
    days = max(1, min(int(days or 30), 366))
    meds = [m for m in list_medicines() if m['active'] and m.get('times')]
    # Anchor on the USER's day, not the server's — same rule the dose rows, the
    # calendar, and get_at_risk_dose_today follow — so an IST user near a UTC
    # midnight doesn't see today's taken doses counted as missed.
    try:
        anchor = date.fromisoformat(user_today())
    except ValueError:
        anchor = date.today()
    start = (anchor - timedelta(days=days - 1)).isoformat()

    taken_set = set()
    for r in (execute("""SELECT medicine_id, date_key, time_key FROM dose_logs
                         WHERE user_id=? AND taken=1 AND date_key>=?""",
                      (uid, start), fetchall=True) or []):
        taken_set.add((r['medicine_id'], r['date_key'], r['time_key']))

    agg = {key: {'bucket': key, 'label': lbl, 'total': 0, 'taken': 0}
           for key, lbl, _lo, _hi in _TOD_BUCKETS}
    for i in range(days):
        d = (anchor - timedelta(days=i)).isoformat()
        for m in meds:
            if not _scheduled_on_day(m, d):
                continue
            for t in m.get('times', []):
                b = agg[_time_bucket(t)]
                b['total'] += 1
                if (m['id'], d, t) in taken_set:
                    b['taken'] += 1

    _TOD_MIN = 5
    out = []
    for key, lbl, _lo, _hi in _TOD_BUCKETS:
        b = agg[key]
        b['missed'] = b['total'] - b['taken']
        b['pct'] = round(b['taken'] / b['total'] * 100, 1) if b['total'] else None
        out.append(b)
    eligible = [b for b in out if b['total'] >= _TOD_MIN]
    worst = min(eligible, key=lambda b: b['pct']) if eligible else None
    return {'days': days, 'buckets': out,
            'worst': worst['bucket'] if worst else None,
            'has_data': any(b['total'] for b in out)}


_WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday"]
_WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def get_adherence_by_weekday(days: int = 90) -> dict:
    """Per-weekday adherence over the window — the behavioural cut that shows
    'weekends slip' where the time-of-day view can't. Same scheduling rules as
    get_adherence_by_timeofday, grouped Mon–Sun by each day's weekday.

    'worst' names the weekday with the lowest adherence among those with enough
    scheduled doses to matter (>= _WD_MIN); None if none qualify — we don't crown
    a worst day off one or two doses."""
    from datetime import date, timedelta
    uid = current_user_id()
    days = max(1, min(int(days or 90), 366))
    meds = [m for m in list_medicines() if m['active'] and m.get('times')]
    try:
        anchor = date.fromisoformat(user_today())
    except ValueError:
        anchor = date.today()
    start = (anchor - timedelta(days=days - 1)).isoformat()

    taken_set = set()
    for r in (execute("""SELECT medicine_id, date_key, time_key FROM dose_logs
                         WHERE user_id=? AND taken=1 AND date_key>=?""",
                      (uid, start), fetchall=True) or []):
        taken_set.add((r['medicine_id'], r['date_key'], r['time_key']))

    agg = {i: {'weekday': i, 'label': _WEEKDAY_LABELS[i], 'short': _WEEKDAY_SHORT[i],
               'total': 0, 'taken': 0} for i in range(7)}
    for i in range(days):
        day = anchor - timedelta(days=i)
        d = day.isoformat()
        wd = day.weekday()          # Mon=0 … Sun=6
        for m in meds:
            if not _scheduled_on_day(m, d):
                continue
            for t in m.get('times', []):
                agg[wd]['total'] += 1
                if (m['id'], d, t) in taken_set:
                    agg[wd]['taken'] += 1

    _WD_MIN = 4
    out = []
    for i in range(7):
        b = agg[i]
        b['missed'] = b['total'] - b['taken']
        b['pct'] = round(b['taken'] / b['total'] * 100, 1) if b['total'] else None
        out.append(b)
    eligible = [b for b in out if b['total'] >= _WD_MIN]
    worst = min(eligible, key=lambda b: b['pct']) if eligible else None
    best = max(eligible, key=lambda b: b['pct']) if eligible else None
    # Only name a "hardest day" when there's an actual miss to talk about —
    # crowning a 100%-adherence day as "worst" would read as a false criticism.
    if worst and worst['pct'] >= 100:
        worst = None
    return {'days': days, 'weekdays': out,
            'worst': worst['weekday'] if worst else None,
            'best': best['weekday'] if best else None,
            'has_data': any(b['total'] for b in out)}


def set_medicine_photo(mid: str, filename: str) -> str:
    """Attach an identification photo to the caller's medicine. Returns the
    PREVIOUS filename (so the route can delete the old file), or '' if none/not
    owned. Ownership is enforced by the user_id clause."""
    uid = current_user_id()
    row = execute("SELECT photo_path FROM medicines WHERE id=? AND user_id=?",
                  (mid, uid), fetchone=True)
    if not row:
        return ''
    prev = row['photo_path'] or ''
    execute("UPDATE medicines SET photo_path=? WHERE id=? AND user_id=?",
            (filename, mid, uid), commit=True)
    return prev


def clear_medicine_photo(mid: str) -> str:
    """Remove the photo reference from the caller's medicine. Returns the removed
    filename (for file cleanup), or '' if none/not owned."""
    uid = current_user_id()
    row = execute("SELECT photo_path FROM medicines WHERE id=? AND user_id=?",
                  (mid, uid), fetchone=True)
    if not row or not row['photo_path']:
        return ''
    prev = row['photo_path']
    execute("UPDATE medicines SET photo_path='' WHERE id=? AND user_id=?",
            (mid, uid), commit=True)
    return prev


def get_new_med_watch(recent_days: int = 45) -> dict:
    """For medicines started in the last `recent_days` days, list the symptoms
    the user has logged since that start date. This is a TIMING view — a prompt
    to mention new symptoms to a doctor — and deliberately NOT a causal claim:
    Arogo can't and won't say a medicine caused a symptom. No invented data;
    every symptom is one the user logged themselves.

    A med appears only if it has at least one symptom logged on/after its start
    date. Symptoms are grouped by name with a count and the worst severity seen."""
    from datetime import date, timedelta
    uid = current_user_id()
    recent_days = max(1, min(int(recent_days or 45), 180))
    try:
        today = date.fromisoformat(user_today())
    except ValueError:
        today = date.today()
    cutoff = (today - timedelta(days=recent_days)).isoformat()

    started = []
    for m in list_medicines():
        if not m.get('active'):
            continue
        sd = m.get('start_date')
        if not sd or not valid_date(sd) or sd < cutoff or sd > today.isoformat():
            continue
        started.append((m, sd))
    if not started:
        return {'has_data': False, 'meds': []}

    out = []
    for m, sd in started:
        rows = execute("""SELECT name, severity, date_key FROM symptoms
                          WHERE user_id=? AND date_key>=? ORDER BY date_key""",
                       (uid, sd), fetchall=True) or []
        if not rows:
            continue
        groups = {}
        for r in rows:
            nm = (r['name'] or '').strip() or 'Symptom'
            g = groups.setdefault(nm, {'name': nm, 'count': 0, 'worst': None,
                                       'first': r['date_key'], 'last': r['date_key']})
            g['count'] += 1
            sev = r['severity']
            if isinstance(sev, (int, float)):
                g['worst'] = sev if g['worst'] is None else max(g['worst'], sev)
            if r['date_key'] < g['first']:
                g['first'] = r['date_key']
            if r['date_key'] > g['last']:
                g['last'] = r['date_key']
        symptoms = sorted(groups.values(), key=lambda x: -x['count'])
        try:
            days_since = (today - date.fromisoformat(sd)).days
        except ValueError:
            days_since = None
        out.append({'id': m['id'], 'name': m.get('name') or 'Medicine',
                    'start_date': sd, 'days_since': days_since,
                    'symptom_count': sum(g['count'] for g in symptoms),
                    'symptoms': symptoms})

    out.sort(key=lambda x: (x['days_since'] if x['days_since'] is not None else 9999))
    return {'has_data': bool(out), 'meds': out}


def get_dose_calendar(days: int = 35) -> list:
    """Per-day scheduled-dose status for a heatmap, oldest→newest.

    status: 'all' (every dose taken), 'partial', 'missed' (none taken), or
    'none' (nothing scheduled that day). As-needed meds have no schedule, so
    they never make a day count as missed."""
    from datetime import date, timedelta
    uid = current_user_id()
    days = max(1, min(int(days or 35), 366))
    meds = [m for m in list_medicines()
            if m['active'] and m.get('frequency') != 'as_needed' and m.get('times')]
    anchor = date.fromisoformat(user_today())
    start = (anchor - timedelta(days=days - 1)).isoformat()

    # One query for the whole window instead of one per dose-slot per day — at a
    # year's span with several meds that was thousands of round-trips. Build a set
    # of the taken (med, date, time) slots and read from it in the loop.
    taken_set = set()
    for r in (execute("""SELECT medicine_id, date_key, time_key FROM dose_logs
                         WHERE user_id=? AND taken=1 AND date_key>=?""",
                      (uid, start), fetchall=True) or []):
        taken_set.add((r['medicine_id'], r['date_key'], r['time_key']))

    out = []
    for i in range(days - 1, -1, -1):
        d = (anchor - timedelta(days=i)).isoformat()
        total = taken = 0
        for m in meds:
            if not _in_course(m, d):
                continue
            for t in m['times']:
                total += 1
                if (m['id'], d, t) in taken_set:
                    taken += 1
        status = ('none' if total == 0 else 'all' if taken == total
                  else 'missed' if taken == 0 else 'partial')
        out.append({'date': d, 'total': total, 'taken': taken, 'status': status})
    return out


def get_adherence_streak(window: int = 180) -> dict:
    """Consecutive 'perfect' days (every scheduled dose taken), ending today or
    yesterday, plus the best such run in the window.

    A day with nothing scheduled is NEUTRAL — it never breaks a run and never
    pads it, so a genuine day off doesn't cost you a streak. Today is counted
    only once it's complete; an in-progress today (some doses not yet taken)
    doesn't break the streak — it just doesn't extend it until it's done."""
    cal = get_dose_calendar(max(1, min(int(window or 180), 365)))
    if not cal:
        return {'streak': 0, 'best': 0, 'perfect_today': False}

    # Current streak: walk newest → oldest.
    streak = 0
    for i, day in enumerate(reversed(cal)):
        st = day['status']
        if st == 'all':
            streak += 1
        elif st == 'none':
            continue                       # neutral — skip without breaking
        elif i == 0 and st in ('partial', 'missed'):
            continue                       # today still in progress — don't break
        else:
            break

    # Best streak in the window (neutral days bridge, misses reset).
    best = cur = 0
    for day in cal:
        st = day['status']
        if st == 'all':
            cur += 1
            best = max(best, cur)
        elif st == 'none':
            continue
        else:
            cur = 0

    return {'streak': streak, 'best': best,
            'perfect_today': bool(cal[-1]['status'] == 'all')}


def get_pill_planner(days: int = 7) -> dict:
    """A days×times grid of the UPCOMING plan — what to take in each slot over
    the next N days. Rows are the union of scheduled dose times; each cell lists
    the meds due then that day, respecting each med's course window. As-needed
    meds have no fixed slot, so they're excluded (they live on the card instead)."""
    from datetime import date, timedelta
    days = max(1, min(int(days or 7), 14))
    meds = [m for m in list_medicines()
            if m['active'] and m.get('frequency') != 'as_needed' and m.get('times')]
    anchor = date.fromisoformat(user_today())

    daylist = []
    for i in range(days):
        d = anchor + timedelta(days=i)
        daylist.append({'date': d.isoformat(), 'weekday': d.strftime('%a'),
                        'day': d.day, 'is_today': i == 0})

    times = sorted({t for m in meds for t in m['times']})
    rows = []
    for t in times:
        cells = []
        for dinfo in daylist:
            due = []
            for m in meds:
                if t in m['times'] and _scheduled_on_day(m, dinfo['date']):
                    dosage = (m.get('dosage') or '').strip()
                    dose = (dosage + ' ' + (m.get('unit') or '')).strip() if dosage else ''
                    due.append({'name': m['name'], 'icon': m.get('icon') or '💊',
                                'dose': dose, 'timing_text': m.get('timing_text') or ''})
            cells.append(due)
        rows.append({'time': t, 'label': _slot_label(t), 'cells': cells})

    return {'days': daylist, 'rows': rows, 'has_schedule': bool(rows)}


def get_adherence_breakdown(days: int = 30, min_scheduled: int = 3) -> dict:
    """Per-slot adherence over the last N days, worst first, to answer
    'which doses do I miss most?'. Each row is one medicine at one time; slots
    with fewer than min_scheduled scheduled doses are omitted (too little data
    to judge). Returns the worst slot as a headline when one stands out."""
    from datetime import date, timedelta
    uid = current_user_id()
    days = max(1, min(int(days or 30), 365))
    meds = [m for m in list_medicines()
            if m['active'] and m.get('frequency') != 'as_needed' and m.get('times')]
    anchor = date.fromisoformat(user_today())
    daykeys = [(anchor - timedelta(days=i)).isoformat() for i in range(days)]

    rows = []
    for m in meds:
        for t in m['times']:
            total = taken = 0
            for d in daykeys:
                if not _in_course(m, d):
                    continue
                total += 1
                log = execute("""SELECT taken FROM dose_logs
                                 WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?""",
                              (m['id'], d, t, uid), fetchone=True)
                if log and log['taken']:
                    taken += 1
            if total >= min_scheduled:
                rows.append({'med_id': m['id'], 'med_name': m['name'],
                             'icon': m.get('icon') or '💊', 'time': t,
                             'label': _slot_label(t),
                             'timing_text': m.get('timing_text') or '',
                             'total': total, 'taken': taken, 'missed': total - taken,
                             'pct': round(taken / total * 100)})
    # Worst adherence first; ties broken by more misses, then earlier time.
    rows.sort(key=lambda r: (r['pct'], -r['missed'], r['time']))
    # A headline only if the worst slot has real misses and isn't already perfect.
    worst = next((r for r in rows if r['missed'] > 0), None)
    return {'days': days, 'slots': rows, 'worst': worst, 'has_data': bool(rows)}


_SKIP_LABEL = {'forgot': 'Forgot', 'away': 'Was away', 'side_effect': 'Side effect',
               'ran_out': 'Ran out', 'felt_ok': 'Felt fine', 'other': 'Other'}


def get_skip_reasons(days: int = 30) -> dict:
    """How often each skip reason was given over the window — so a pattern (you
    skip when travelling, or over side-effects) becomes visible. Only counts
    rows the user explicitly tagged; an untagged miss isn't guessed at."""
    from datetime import date, timedelta
    uid = current_user_id()
    days = max(1, min(int(days or 30), 366))
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = execute("""SELECT skip_reason, COUNT(*) AS n FROM dose_logs
                      WHERE user_id=? AND taken=0 AND skip_reason IS NOT NULL AND date_key>=?
                      GROUP BY skip_reason""", (uid, start), fetchall=True) or []
    counts = []
    total = 0
    for r in rows:
        reason = r['skip_reason']
        if reason not in SKIP_REASONS:
            continue
        counts.append({'reason': reason, 'label': _SKIP_LABEL.get(reason, reason), 'count': r['n']})
        total += r['n']
    counts.sort(key=lambda x: -x['count'])
    return {'days': days, 'reasons': counts, 'total': total,
            'top': counts[0]['reason'] if counts else None, 'has_data': bool(counts)}


def get_reminder_responsiveness(days: int = 30) -> dict:
    """How soon you log a dose after it's due — from taken_at vs the scheduled
    time. Buckets each taken dose into early / on-time (≤30 min) / late (≤3 h) /
    very late, and reports the median delay and the on-time share.

    Honest caveat: taken_at is the log time (server clock) and the scheduled time
    is your local HH:MM, so on a self-hosted box in one timezone they line up,
    but the delays are approximate. Same-day backfills far from the slot are
    excluded from the median as noise."""
    import datetime as dt
    import statistics
    uid = current_user_id()
    days = max(1, min(int(days or 30), 366))
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("""SELECT date_key, time_key, taken_at FROM dose_logs
                      WHERE user_id=? AND taken=1 AND taken_at IS NOT NULL AND date_key>=?""",
                   (uid, start), fetchall=True) or []

    delays = []                      # minutes; +ve = logged after the scheduled time
    buckets = {'early': 0, 'ontime': 0, 'late': 0, 'very_late': 0}
    for r in rows:
        tk = str(r['time_key'] or '')
        if len(tk) < 4 or tk[2] != ':':
            continue
        # PRN (as-needed) doses stamp a HH:MM:SS time_key at log time, so their
        # "delay" is ~0 by construction and would inflate on-time %. They have no
        # scheduled due-time — skip anything longer than HH:MM.
        if len(tk) > 5:
            continue
        try:
            sched = dt.datetime.fromisoformat(f"{r['date_key']}T{tk[:5]}:00")
            logged = dt.datetime.fromisoformat(str(r['taken_at'])[:19])
        except ValueError:
            continue
        delta_min = (logged - sched).total_seconds() / 60.0
        # Exclude far-off backfills (|Δ| > 2 days) from the median — they're
        # catch-up logging, not "how fast did you respond".
        if abs(delta_min) > 2 * 24 * 60:
            continue
        delays.append(delta_min)
        if delta_min < 0:
            buckets['early'] += 1
        elif delta_min <= 30:
            buckets['ontime'] += 1
        elif delta_min <= 180:
            buckets['late'] += 1
        else:
            buckets['very_late'] += 1

    n = len(delays)
    median_delay = round(statistics.median(delays)) if delays else None
    within = buckets['early'] + buckets['ontime']
    ontime_pct = round(within / n * 100) if n else None
    return {
        'days': days, 'count': n,
        'median_delay_min': median_delay,
        'ontime_pct': ontime_pct,
        'buckets': [
            {'key': 'early',     'label': 'Early',     'count': buckets['early']},
            {'key': 'ontime',    'label': 'On time',   'count': buckets['ontime']},
            {'key': 'late',      'label': 'Late',      'count': buckets['late']},
            {'key': 'very_late', 'label': 'Very late', 'count': buckets['very_late']},
        ],
        'has_data': n > 0,
    }


def get_adherence_goal():
    """The user's monthly adherence-% target, or None if unset."""
    r = execute("SELECT adherence_goal_pct FROM reminder_settings WHERE user_id=? LIMIT 1",
                (current_user_id(),), fetchone=True)
    g = (r or {}).get('adherence_goal_pct') if r else None
    try:
        return int(g) if g not in (None, '') else None
    except (TypeError, ValueError):
        return None


def set_adherence_goal(pct):
    """Set (or clear with None/0) the monthly adherence target, clamped 1–100."""
    uid = current_user_id()
    exists = execute("SELECT id FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if not exists:
        execute("INSERT INTO reminder_settings (id, user_id, updated_at) VALUES (?,?,?)",
                (new_id(), uid, now_iso()), commit=True)
    if pct in (None, '', 0, '0'):
        execute("UPDATE reminder_settings SET adherence_goal_pct=NULL WHERE user_id=?", (uid,), commit=True)
        return None
    try:
        p = max(1, min(int(pct), 100))
    except (TypeError, ValueError):
        raise ValueError('Adherence goal must be a number')
    execute("UPDATE reminder_settings SET adherence_goal_pct=? WHERE user_id=?", (p, uid), commit=True)
    return p


def get_adherence_forecast() -> dict:
    """This calendar month's adherence so far and where it's heading. Projection
    assumes the rest of the month is taken at the same rate you've kept to date
    (so 'projected' == your current rate) — honest, not optimistic. Also: how
    many more doses you can miss and still hit your goal.

    None goal → the goal-relative fields are None; the month-to-date numbers are
    always real."""
    import datetime as dt
    uid = current_user_id()
    try:
        today = dt.date.fromisoformat(user_today())
    except ValueError:
        today = dt.date.today()
    month_start = today.replace(day=1)
    # last day of month
    if today.month == 12:
        month_end = dt.date(today.year, 12, 31)
    else:
        month_end = dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)

    meds = [m for m in list_medicines() if m['active'] and m.get('frequency') != 'as_needed' and m.get('times')]
    taken_set = set()
    for r in (execute("""SELECT medicine_id, date_key, time_key FROM dose_logs
                         WHERE user_id=? AND taken=1 AND date_key>=? AND date_key<=?""",
                      (uid, month_start.isoformat(), month_end.isoformat()), fetchall=True) or []):
        taken_set.add((r['medicine_id'], r['date_key'], r['time_key']))

    scheduled_to_date = taken_to_date = remaining_scheduled = 0
    d = month_start
    while d <= month_end:
        ds = d.isoformat()
        for m in meds:
            if not _scheduled_on_day(m, ds):
                continue
            for tkey in m['times']:
                if d <= today:
                    scheduled_to_date += 1
                    if (m['id'], ds, tkey) in taken_set:
                        taken_to_date += 1
                else:
                    remaining_scheduled += 1
        d += dt.timedelta(days=1)

    total_month = scheduled_to_date + remaining_scheduled
    current_pct = round(taken_to_date / scheduled_to_date * 100, 1) if scheduled_to_date else None
    projected_pct = current_pct       # taking the rest at the same rate lands here

    goal = get_adherence_goal()
    on_track = misses_allowed = None
    if goal is not None and total_month:
        # doses that must be taken over the whole month to hit the goal
        import math as _m
        need_taken = _m.ceil(goal / 100 * total_month)
        can_miss_total = total_month - need_taken
        already_missed = scheduled_to_date - taken_to_date
        misses_allowed = max(0, can_miss_total - already_missed)
        on_track = (projected_pct is not None and projected_pct >= goal)

    return {
        'month': today.strftime('%Y-%m'),
        'goal_pct': goal,
        'current_pct': current_pct,
        'projected_pct': projected_pct,
        'taken_to_date': taken_to_date, 'scheduled_to_date': scheduled_to_date,
        'remaining_scheduled': remaining_scheduled, 'total_month': total_month,
        'on_track': on_track, 'misses_allowed': misses_allowed,
        'has_data': scheduled_to_date > 0,
    }


def get_at_risk_dose_today(history_days: int = 30, min_history: int = 4, risk_threshold: int = 25):
    """Of today's STILL-PENDING doses, the one the user most often misses — a
    forward-looking "don't forget this one today" rather than a backward report.

    Distinct from get_adherence_nudge (what slipped this week) and
    get_adherence_breakdown (all-time worst slot): this looks only at doses
    actually due-and-untaken today, ranked by their own historical miss rate.
    Returns None unless a pending slot has enough history (>= min_history days)
    AND is missed at least risk_threshold% of the time — we don't nag about a
    dose you rarely miss.
    """
    from datetime import date, timedelta
    uid = current_user_id()
    today = user_today()
    pending = [d for d in get_today_doses() if not d['taken']]
    if not pending:
        return None
    try:
        anchor = date.fromisoformat(today)
    except ValueError:
        return None
    start = (anchor - timedelta(days=history_days)).isoformat()
    taken_set = set()
    for r in (execute("""SELECT medicine_id, date_key, time_key FROM dose_logs
                         WHERE user_id=? AND taken=1 AND date_key>=? AND date_key<?""",
                      (uid, start, today), fetchall=True) or []):
        taken_set.add((r['medicine_id'], r['date_key'], r['time_key']))
    meds_by_id = {m['id']: m for m in list_medicines()}

    best = None
    for dose in pending:
        m = meds_by_id.get(dose['med_id'])
        if not m or m.get('frequency') == 'as_needed':
            continue
        sched = taken = 0
        for i in range(1, history_days + 1):        # yesterday backwards; today excluded
            day = (anchor - timedelta(days=i)).isoformat()
            if not _scheduled_on_day(m, day):
                continue
            sched += 1
            if (m['id'], day, dose['time']) in taken_set:
                taken += 1
        if sched < min_history:
            continue
        miss_pct = round((sched - taken) / sched * 100)
        if miss_pct < risk_threshold:
            continue
        if best is None or miss_pct > best['miss_pct']:
            best = {'med_id': m['id'], 'med_name': m['name'], 'icon': m.get('icon') or '💊',
                    'time': dose['time'], 'label': _slot_label(dose['time']),
                    'miss_pct': miss_pct, 'missed': sched - taken, 'scheduled': sched}
    return best


def _slot_label(hhmm: str) -> str:
    """Bucket a HH:MM dose time into a plain time-of-day label."""
    try:
        h = int(hhmm.split(':')[0])
    except (ValueError, AttributeError, IndexError):
        return 'Anytime'
    if h < 12:  return 'Morning'
    if h < 17:  return 'Afternoon'
    if h < 21:  return 'Evening'
    return 'Night'


def get_adherence_nudge(recent_days: int = 7, min_recent: int = 3) -> dict:
    """A single timely, per-slot adherence nudge from recent dose logs, or
    {'kind': None}.

    Complements get_adherence_breakdown (a 30-day 'which do I miss most'
    aggregate) by looking at just the last `recent_days` days — what's slipping
    NOW — and naming the specific dose to act on. Surfaces the most useful of:
      - 'slipping': a slot that was reliable the prior week (>=80% taken) and has
        fallen this week (<=50%). A change worth catching early.
      - 'recent_misses': a slot missed on most of its recent scheduled days.
    Requires >= min_recent scheduled occurrences in the window (so it never
    judges on thin data) and stays silent when recent adherence is fine. Every
    count comes from dose_logs — nothing is invented.
    """
    from datetime import date, timedelta
    uid = current_user_id()
    meds = [m for m in list_medicines()
            if m['active'] and m.get('frequency') != 'as_needed' and m.get('times')]
    anchor = date.fromisoformat(user_today())
    recent = [(anchor - timedelta(days=i)).isoformat() for i in range(recent_days)]
    prior  = [(anchor - timedelta(days=i)).isoformat() for i in range(recent_days, recent_days * 2)]

    def tally(m, t, daykeys):
        sched = taken = 0
        for d in daykeys:
            if not _scheduled_on_day(m, d):
                continue
            sched += 1
            log = execute("""SELECT taken FROM dose_logs
                             WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?""",
                          (m['id'], d, t, uid), fetchone=True)
            if log and log['taken']:
                taken += 1
        return sched, taken

    slipping = None
    misses = None
    for m in meds:
        for t in m['times']:
            rs, rt = tally(m, t, recent)
            if rs < min_recent:
                continue
            rmissed = rs - rt
            rpct = rt / rs
            # 'slipping': reliable last week, not this week — the biggest drop wins.
            ps, pt = tally(m, t, prior)
            if ps >= min_recent and (pt / ps) >= 0.8 and rpct <= 0.5:
                drop = round((pt / ps - rpct) * 100)
                if not slipping or drop > slipping['_drop']:
                    slipping = {'kind': 'slipping', 'med_id': m['id'], 'med_name': m['name'],
                                'icon': m.get('icon') or '💊', 'time': t, 'label': _slot_label(t),
                                'missed': rmissed, 'scheduled': rs, 'recent_pct': round(rpct * 100),
                                'prev_pct': round(pt / ps * 100), 'days': recent_days, '_drop': drop}
            # 'recent_misses': missed at least half of its recent occurrences (and >=2).
            if rmissed >= 2 and rmissed * 2 >= rs and not (slipping and slipping.get('med_id') == m['id'] and slipping.get('time') == t):
                if not misses or rmissed > misses['missed']:
                    misses = {'kind': 'recent_misses', 'med_id': m['id'], 'med_name': m['name'],
                              'icon': m.get('icon') or '💊', 'time': t, 'label': _slot_label(t),
                              'missed': rmissed, 'scheduled': rs, 'days': recent_days}

    nudge = slipping or misses
    if nudge:
        nudge.pop('_drop', None)
        return nudge
    return {'kind': None}


def get_medication_card() -> dict:
    """The data behind the printable medication card — a fridge/wallet reference
    of what to take when, plus emergency contacts. Read-only aggregation of the
    user's own active medicines and emergency info (nothing fabricated)."""
    from db.health import get_emergency_info

    active = [m for m in list_medicines() if m['active']]
    scheduled = [m for m in active
                 if m.get('frequency') != 'as_needed' and m.get('times')]
    as_needed = [m for m in active
                 if m.get('frequency') == 'as_needed' or not m.get('times')]

    def _row(m):
        # Only show a dose when there's an actual amount — the unit defaults to
        # 'mg', so a med with no dosage would otherwise render a bare "mg".
        dosage = (m.get('dosage') or '').strip()
        dose = (dosage + ' ' + (m.get('unit') or '')).strip() if dosage else ''
        return {
            'name': m['name'],
            'dose': dose,
            'purpose': m.get('purpose') or '',
            'with_food': bool(m.get('with_food')),
            'timing': m.get('timing') or '',
            'timing_text': m.get('timing_text') or '',
            'icon': m.get('icon') or '💊',
        }

    # Group scheduled meds by dose time so the card reads "at 9:00 AM, take …".
    slots = {}
    for m in scheduled:
        for t in m['times']:
            slots.setdefault(t, []).append(_row(m))
    schedule = [{'time': t, 'label': _slot_label(t), 'meds': slots[t]}
                for t in sorted(slots)]

    emg = get_emergency_info() or {}
    contacts = []
    for n, p in ((emg.get('contact1_name'), emg.get('contact1_phone')),
                 (emg.get('contact2_name'), emg.get('contact2_phone'))):
        if (n or '').strip() or (p or '').strip():
            contacts.append({'name': (n or '').strip(), 'phone': (p or '').strip()})

    return {
        'schedule': schedule,
        'as_needed': [_row(m) for m in as_needed],
        'count': len(active),
        'emergency': {
            'blood_type': (emg.get('blood_type') or '').strip(),
            'allergies': (emg.get('allergies') or '').strip(),
            'conditions': (emg.get('conditions') or '').strip(),
            'contacts': contacts,
        },
    }


# ── Refill / stock ────────────────────────────────────────────────────────────

def update_medicine_stock(mid: str, pill_count: int, pills_per_dose: int = 1,
                          refill_threshold: int = 7, pharmacy_note=None) -> dict:
    uid = current_user_id()
    prev = execute("SELECT pill_count FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    prev_count = prev['pill_count'] if prev and prev['pill_count'] is not None else 0
    # Restocking (count went up) means the refill arrived — clear any pending
    # "ordered" flag so it doesn't keep showing as on-the-way.
    clear = pill_count > prev_count
    sets = "pill_count=?, pills_per_dose=?, refill_threshold=?"
    params = [pill_count, pills_per_dose, refill_threshold]
    if pharmacy_note is not None:
        sets += ", pharmacy_note=?"; params.append((pharmacy_note or '')[:200])
    if clear:
        sets += ", refill_status=NULL, refill_ordered_at=NULL"
    params += [mid, uid]
    execute(f"UPDATE medicines SET {sets} WHERE id=? AND user_id=?", tuple(params), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    if r and clear:            # count went up → the refill arrived
        log_medicine_event(mid, 'restocked', r['name'], f'{pill_count} left')
    return _fmt_med(r) if r else {}


def mark_refill_ordered(mid: str) -> dict:
    """Mark a refill as ordered so it stops nagging until it arrives."""
    uid = current_user_id()
    execute("UPDATE medicines SET refill_status='ordered', refill_ordered_at=? WHERE id=? AND user_id=?",
            (now_iso(), mid, uid), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    return _fmt_med(r) if r else {}


def set_pharmacy_note(mid: str, note: str) -> dict:
    """Where/how you refill this one — a free-text reminder to yourself."""
    uid = current_user_id()
    execute("UPDATE medicines SET pharmacy_note=? WHERE id=? AND user_id=?",
            ((note or '')[:200], mid, uid), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    return _fmt_med(r) if r else {}


def set_reminder_lead(mid: str, minutes) -> dict:
    """How many minutes before a scheduled dose to fire its reminder (0–120).
    Editable from the reminders panel without re-adding the medicine."""
    uid = current_user_id()
    try:
        m = max(0, min(int(minutes), 120))
    except (TypeError, ValueError):
        m = 0
    if not execute("SELECT id FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True):
        return {}
    execute("UPDATE medicines SET reminder_lead_min=? WHERE id=? AND user_id=?",
            (m, mid, uid), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    return _fmt_med(r) if r else {}


# ── Dose snooze (a real "remind me later") ───────────────────────────────────

def snooze_dose(med_id: str, time_key: str, minutes: int = 15) -> dict:
    """Re-remind this dose after a short delay. A snooze is a RELATIVE delay, so
    server time is used consistently on both ends — no per-user timezone needed."""
    import datetime as dt
    uid = current_user_id()
    if not execute("SELECT id FROM medicines WHERE id=? AND user_id=?", (med_id, uid), fetchone=True):
        return {}
    try:
        m = max(1, min(int(minutes), 180))
    except (TypeError, ValueError):
        m = 15
    until = (dt.datetime.now() + dt.timedelta(minutes=m)).isoformat()
    today = user_today()
    execute("DELETE FROM dose_snoozes WHERE user_id=? AND med_id=? AND date_key=? AND time_key=?",
            (uid, med_id, today, time_key), commit=True)
    execute("""INSERT INTO dose_snoozes (id,user_id,med_id,date_key,time_key,snooze_until,notified,created_at)
               VALUES (?,?,?,?,?,?,0,?)""",
            (new_id(), uid, med_id, today, time_key, until, now_iso()), commit=True)
    return {'snooze_until': until, 'minutes': m}


def get_due_snoozes() -> list:
    """Snoozes whose delay has elapsed, not yet re-notified, dose still untaken."""
    import datetime as dt
    uid = current_user_id()
    now = dt.datetime.now().isoformat()
    rows = execute("SELECT * FROM dose_snoozes WHERE user_id=? AND notified=0 AND snooze_until<=?",
                   (uid, now), fetchall=True) or []
    out = []
    for r in rows:
        log = execute("SELECT taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
                      (r['med_id'], r['date_key'], r['time_key'], uid), fetchone=True)
        med = execute("SELECT name, purpose FROM medicines WHERE id=? AND user_id=? AND active=1",
                      (r['med_id'], uid), fetchone=True)
        if (log and log['taken']) or not med:
            execute("DELETE FROM dose_snoozes WHERE id=?", (r['id'],), commit=True)
            continue
        out.append({'id': r['id'], 'med_id': r['med_id'], 'time': r['time_key'],
                    'med_name': med['name'], 'purpose': med['purpose'] or ''})
    return out


def mark_snooze_notified(sid: str):
    execute("UPDATE dose_snoozes SET notified=1 WHERE id=? AND user_id=?",
            (sid, current_user_id()), commit=True)

def _pills_applied(dose_log_id: str, uid: str) -> int:
    r = execute("SELECT pills_applied FROM dose_logs WHERE id=? AND user_id=?",
                (dose_log_id, uid), fetchone=True)
    try:
        return max(0, int(r['pills_applied'] or 0)) if r else 0
    except (KeyError, TypeError, IndexError):
        return 0        # pre-migration row: restore nothing rather than invent


def _consume_stock(mid: str) -> int:
    """Take one dose's worth of pills out of stock; return how many actually
    came out. Stock can't go below zero, so a user who's out of pills consumes
    0 — and that 0 is what an un-take must give back. Returns 0 when the
    medicine tracks no stock (pill_count IS NULL)."""
    uid = current_user_id()
    r = execute("SELECT pill_count,pills_per_dose FROM medicines WHERE id=? AND user_id=?",
                (mid, uid), fetchone=True)
    if not r or r['pill_count'] is None:
        return 0
    applied = min(r['pills_per_dose'] or 1, r['pill_count'])
    if applied <= 0:
        return 0
    execute("UPDATE medicines SET pill_count=? WHERE id=? AND user_id=?",
            (r['pill_count'] - applied, mid, uid), commit=True)
    return applied


def _restore_stock(mid: str, pills: int):
    """Put back exactly the pills a take removed — no more."""
    if pills <= 0:
        return
    uid = current_user_id()
    r = execute("SELECT pill_count FROM medicines WHERE id=? AND user_id=?",
                (mid, uid), fetchone=True)
    if not r or r['pill_count'] is None:
        return
    execute("UPDATE medicines SET pill_count=? WHERE id=? AND user_id=?",
            (r['pill_count'] + pills, mid, uid), commit=True)


def _apply_stock_delta(mid: str, doses: int):
    """Back-compat shim for callers outside the dose-log ledger."""
    if doses < 0:
        _consume_stock(mid)
    elif doses > 0:
        r = execute("SELECT pills_per_dose FROM medicines WHERE id=? AND user_id=?",
                    (mid, current_user_id()), fetchone=True)
        _restore_stock(mid, (r['pills_per_dose'] or 1) if r else 1)


def decrement_pill_count(mid: str):
    """Call after a dose is taken to reduce stock (one dose's worth)."""
    _apply_stock_delta(mid, -1)

_FREQ_DOSES = {
    'once_daily': 1, 'twice_daily': 2, 'thrice_daily': 3, 'weekly': 1/7,
    'once': 1, 'twice': 2, 'three_times': 3,   # legacy keys
}


def _days_of_supply(m):
    """Days of stock left for a medicine, or None if it isn't tracking pills.

    A day-of-week schedule stretches the supply: a med taken only 2 of 7 days
    lasts ~3.5× longer than the daily rate, so scale the per-day burn by how many
    weekdays it's actually taken — otherwise a weekly med reads as 'low' when it
    has weeks of pills left."""
    pc = m.get('pill_count')
    if pc is None:
        return None
    per_dose = m.get('pills_per_dose') or 1
    doses = max(len(m.get('times') or []), 1)      # doses per active day
    iv = m.get('interval_days')
    sd = m.get('schedule_days')
    if iv:
        # Taken one active day in every `iv` days.
        per_day = doses * per_dose / iv
    elif sd:
        # Taken on `len(sd)` weekdays out of 7.
        per_day = doses * per_dose * (len(sd) / 7.0)
    else:
        per_day = _FREQ_DOSES.get(m.get('frequency', 'once_daily'), 1) * per_dose
    return round(pc / max(per_day, 0.01), 1)


def get_med_spend_timeline(months: int = 12) -> dict:
    """Estimated medicine spend per month over the last N months, from each med's
    monthly cost and the span it was on your list (start_date → stop event, or
    still active). Plus this year's total and a projected annual at the current
    run-rate.

    Honest caveats baked in: costs are treated as constant at their CURRENT value
    (there's no cost-history), and DELETED meds are gone from the list so their
    past cost isn't counted — so it's clearly an estimate, labelled as such.
    """
    import datetime as dt
    uid = current_user_id()
    months = max(1, min(int(months or 12), 36))
    try:
        today = dt.date.fromisoformat(user_today())
    except ValueError:
        today = dt.date.today()

    meds = [m for m in list_medicines() if m.get('cost') is not None]
    # Stop date per med (earliest stop/delete event) for inactive meds.
    stop_date = {}
    for e in get_medicine_events(days=3650):
        if e.get('kind') in ('stopped', 'deleted'):
            d = (e.get('at') or '')[:10]
            mid = e.get('medicine_id')
            if mid and d and (mid not in stop_date or d < stop_date[mid]):
                stop_date[mid] = d

    def _month_start(y, mo):
        return dt.date(y, mo, 1)

    # Build the last `months` month anchors, oldest → newest.
    anchors = []
    y, mo = today.year, today.month
    for _ in range(months):
        anchors.append((y, mo))
        mo -= 1
        if mo == 0:
            mo = 12; y -= 1
    anchors.reverse()

    timeline = []
    for (yy, mm) in anchors:
        m_start = _month_start(yy, mm)
        m_end = _month_start(yy + (mm // 12), (mm % 12) + 1) - dt.timedelta(days=1)
        spend = 0.0
        for m in meds:
            try:
                start = dt.date.fromisoformat((m.get('start_date') or m.get('created_at') or '')[:10])
            except (ValueError, TypeError):
                start = None
            if not start or start > m_end:
                continue                     # not started yet this month
            sd = stop_date.get(m['id'])
            if not m['active'] and sd:
                try:
                    if dt.date.fromisoformat(sd) < m_start:
                        continue             # already stopped before this month
                except ValueError:
                    pass
            elif not m['active'] and not sd:
                # inactive with no recorded stop date — only count up to today's month
                if m_start > today.replace(day=1):
                    continue
            spend += float(m['cost'])
        timeline.append({'month': f'{yy:04d}-{mm:02d}', 'spend': round(spend, 2)})

    current_monthly = timeline[-1]['spend'] if timeline else 0.0
    ytd = round(sum(t['spend'] for t in timeline if t['month'][:4] == str(today.year)), 2)
    projected_annual = round(current_monthly * 12, 2)
    return {'months': months, 'timeline': timeline, 'current_monthly': current_monthly,
            'ytd': ytd, 'projected_annual': projected_annual,
            'has_data': any(t['spend'] > 0 for t in timeline)}


def get_monthly_med_cost() -> dict:
    """Total monthly spend across active medicines that have a cost set, plus a
    per-medicine breakdown (dearest first). Medicines with no cost are omitted —
    an unpriced med shouldn't read as ₹0."""
    items, total = [], 0.0
    for m in list_medicines():
        if not m['active'] or m.get('cost') is None:
            continue
        c = round(float(m['cost']), 2)
        items.append({'id': m['id'], 'name': m['name'], 'icon': m.get('icon') or '💊', 'cost': c})
        total += c
    items.sort(key=lambda x: -x['cost'])
    return {'total': round(total, 2), 'items': items, 'count': len(items)}


def get_timing_conflicts() -> list:
    """Medicines scheduled at the SAME time with conflicting food instructions —
    one 'with food' and another 'on an empty stomach'/'before food' at, say,
    09:00. This is timing HYGIENE only (spacing/food), never a drug-interaction
    or safety claim; the user decides what to do about it."""
    WITH = {'with_food'}
    WITHOUT = {'empty_stomach', 'before_food'}
    by_time = {}
    for m in list_medicines():
        if not m['active'] or m.get('frequency') == 'as_needed':
            continue
        tk = (m.get('timing') or '').strip()
        if tk not in WITH and tk not in WITHOUT:
            continue
        for t in (m.get('times') or []):
            by_time.setdefault(t, []).append({'name': m['name'], 'icon': m.get('icon') or '💊', 'timing': tk})
    conflicts = []
    for t, meds in sorted(by_time.items()):
        withs = [x for x in meds if x['timing'] in WITH]
        withouts = [x for x in meds if x['timing'] in WITHOUT]
        if withs and withouts:
            conflicts.append({'time': t, 'with_food': withs, 'without_food': withouts})
    return conflicts


def get_med_forecast() -> dict:
    """Forward view of medication logistics: for each tracked medicine, the DATE
    it runs out (today + real days-of-supply), plus the monthly/yearly cost
    projection from the per-med costs. All derived from the user's own data."""
    import datetime as dt
    try:
        today = dt.date.fromisoformat(user_today())
    except ValueError:
        today = dt.date.today()
    run_outs, monthly = [], 0.0
    for m in list_medicines():
        if not m['active']:
            continue
        if m.get('cost') is not None:
            monthly += float(m['cost'])
        # As-needed (PRN) meds have no daily schedule, so there's no honest
        # run-out date to project — _days_of_supply would assume 1 dose/day and
        # invent a countdown. Skip the forecast (cost above still counts).
        if m.get('frequency') == 'as_needed':
            continue
        dl = _days_of_supply(m)
        if dl is not None:
            run_outs.append({
                'id': m['id'], 'name': m['name'], 'icon': m.get('icon') or '💊',
                'days_left': dl, 'run_out': (today + dt.timedelta(days=int(dl))).isoformat(),
                'pill_count': m.get('pill_count'),
                'threshold': m.get('refill_threshold') or 7,
                'low': dl < (m.get('refill_threshold') or 7),
            })
    run_outs.sort(key=lambda x: x['days_left'])
    cost = get_monthly_med_cost()
    return {
        'run_outs': run_outs,
        'next_runout': run_outs[0] if run_outs else None,
        'monthly_cost': round(monthly, 2),
        'yearly_cost': round(monthly * 12, 2),
        'cost_items': cost['items'],
        'priced_count': cost['count'],
    }


def get_refill_list():
    """Every active medicine that needs attention on a pharmacy run: running low,
    out of stock, or already marked ordered (on the way). Worst first."""
    out = []
    for m in list_medicines():
        if not m['active']:
            continue
        pc = m.get('pill_count')
        ordered = m.get('refill_status') == 'ordered'
        days_left = _days_of_supply(m)
        low = days_left is not None and days_left < (m.get('refill_threshold') or 7)
        if not (low or ordered):
            continue
        dosage = (m.get('dosage') or '').strip()
        out.append({
            'id': m['id'], 'name': m['name'], 'icon': m.get('icon') or '💊',
            'dose': (dosage + ' ' + (m.get('unit') or '')).strip() if dosage else '',
            'pill_count': pc, 'days_left': days_left,
            'out': pc == 0, 'ordered': ordered,
            'pharmacy_note': m.get('pharmacy_note') or '',
        })
    # Ordered items sink to the bottom; otherwise out-of-stock first, then fewest days.
    out.sort(key=lambda x: (x['ordered'], not x['out'],
                            x['days_left'] if x['days_left'] is not None else 999))
    return out


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
