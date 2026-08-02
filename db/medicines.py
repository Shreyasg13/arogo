"""
db/medicines.py — Medicine tracker, dose logging, refill/stock management.

All queries are scoped to the authenticated user via current_user_id().
"""
import re

from .core import (execute, executemany, jdump, jload, now_iso, today_iso, user_today,
                   new_id, current_user_id)

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
    execute("""
        INSERT INTO medicines
          (id,name,dosage,unit,frequency,times,with_food,timing,notes,purpose,color,icon,start_date,end_date,active,created_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
    """, (mid, name[:120], str(data.get('dosage', '')).strip()[:60], data.get('unit','mg'),
          data.get('frequency','once_daily'),
          jdump([] if data.get('frequency') == 'as_needed'
                else _clean_times(data.get('times', ['08:00']))),
          with_food, timing, data.get('notes',''),
          str(data.get('purpose', '')).strip()[:120],
          data.get('color','teal'), data.get('icon','💊'),
          data.get('start_date', today_iso()), data.get('end_date',''), now_iso(),
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


def _fmt_med(r):
    d = dict(r)
    d['times'] = jload(d.get('times', '["08:00"]'), ['08:00'])
    d['with_food'] = bool(d.get('with_food', 0))
    d['active'] = bool(d.get('active', 1))
    d['timing'] = (d.get('timing') or '')
    d['timing_text'] = timing_label(d['timing'])
    return d


# ── Dose Logs ────────────────────────────────────────────────────────────────

def log_dose(medicine_id, date_key, time_key, taken=True):
    uid = current_user_id()
    # Only log doses against medicines the user owns
    owner = execute("SELECT id FROM medicines WHERE id=? AND user_id=?",
                    (medicine_id, uid), fetchone=True)
    if not owner:
        return False
    lid = new_id()
    # Upsert
    existing = execute(
        "SELECT id, taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
        (medicine_id, date_key, time_key, uid), fetchone=True)
    prev_taken = bool(existing and existing['taken'])
    new_taken  = bool(taken)
    if existing:
        execute("UPDATE dose_logs SET taken=?, taken_at=? WHERE id=?",
                (1 if new_taken else 0, now_iso(), existing['id']), commit=True)
    else:
        execute("""
            INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at,user_id)
            VALUES (?,?,?,?,?,?,?)
        """, (lid, medicine_id, date_key, time_key, 1 if new_taken else 0, now_iso(), uid),
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


def get_today_doses():
    uid = current_user_id()
    # The user's day, not the server's — the app and service worker write dose
    # rows keyed to the device's local date, and this is what reads them back.
    today = user_today()
    meds = [m for m in list_medicines() if m['active'] and _in_course(m, today)]
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
            if not _in_course(m, d): continue   # don't penalise days outside the course
            for t in m.get('times', []):
                total += 1
                log = execute(
                    "SELECT taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
                    (m['id'], d, t, uid), fetchone=True)
                if log and log.get('taken'): taken += 1
    return {'total': total, 'taken': taken, 'pct': round(taken/total*100, 1) if total else 0}


def get_dose_calendar(days: int = 35) -> list:
    """Per-day scheduled-dose status for a heatmap, oldest→newest.

    status: 'all' (every dose taken), 'partial', 'missed' (none taken), or
    'none' (nothing scheduled that day). As-needed meds have no schedule, so
    they never make a day count as missed."""
    from datetime import date, timedelta
    uid = current_user_id()
    days = max(1, min(int(days or 35), 120))
    meds = [m for m in list_medicines()
            if m['active'] and m.get('frequency') != 'as_needed' and m.get('times')]
    anchor = date.fromisoformat(user_today())
    out = []
    for i in range(days - 1, -1, -1):
        d = (anchor - timedelta(days=i)).isoformat()
        total = taken = 0
        for m in meds:
            if not _in_course(m, d):
                continue
            for t in m['times']:
                total += 1
                log = execute("""SELECT taken FROM dose_logs
                                 WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?""",
                              (m['id'], d, t, uid), fetchone=True)
                if log and log['taken']:
                    taken += 1
        status = ('none' if total == 0 else 'all' if taken == total
                  else 'missed' if taken == 0 else 'partial')
        out.append({'date': d, 'total': total, 'taken': taken, 'status': status})
    return out


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
                if t in m['times'] and _in_course(m, dinfo['date']):
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
