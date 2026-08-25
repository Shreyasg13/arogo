"""
db/health.py — Habit tracker, symptoms diary, vitals log, emergency health card.

All queries are scoped to the authenticated user via current_user_id().
"""
import math

from .core import execute, executemany, jdump, jload, now_iso, today_iso, user_today, new_id, current_user_id, to_num, to_int, valid_date


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

        # Streak back from today, forgiving a single missed day (grace) instead
        # of resetting to zero. A forgiven day is never counted as done.
        from streaks import forgiving_streak
        _st = forgiving_streak(done_dates, today=today, grace=1,
                               earliest=dt.date.fromisoformat(start30))
        streak = _st['streak']
        grace_used = _st['grace_used']

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

        # Best streak: the longest run of consecutive days ever (all-time, so it
        # survives outside the 30-day window). No grace here — a personal best is
        # a genuine unbroken run.
        all_dates = sorted({r['date_key'] for r in execute(
            "SELECT date_key FROM habit_logs WHERE habit_id=? AND done=1 AND user_id=?",
            (h['id'], uid), fetchall=True) or []})
        best_streak = run = 0
        prev = None
        for dk in all_dates:
            d = dt.date.fromisoformat(dk)
            run = run + 1 if (prev is not None and (d - prev).days == 1) else 1
            best_streak = max(best_streak, run)
            prev = d

        result.append({**h,
                       'done_dates':  list(done_dates),
                       'done_today':  today_iso in done_dates,
                       'streak':      streak,
                       'best_streak': best_streak,
                       'grace_used':  grace_used,
                       'completions': len(done_dates),
                       'week7':       week7,
                       'cal28':       cal28})
    return {'habits': result, 'date': today_iso}

# ── Symptoms ──────────────────────────────────────────────────────────────────

# I7 body-map: a fixed set of body regions a symptom can be tagged to. Keys are
# stored; labels/order live in the frontend. '' means unset / not localized.
BODY_REGIONS = ('head', 'neck', 'chest', 'abdomen', 'pelvis', 'back',
                'arms', 'legs', 'skin', 'general')


def _clean_region(v) -> str:
    r = str(v or '').strip().lower()
    return r if r in BODY_REGIONS else ''


def log_symptom(data: dict) -> dict:
    name = str(data.get('name', '')).strip()
    if not name:
        raise ValueError('Symptom name is required')
    from .core import clean_idem_key, find_by_idem_key
    idem = clean_idem_key(data.get('idem_key'))
    if idem:
        prior = find_by_idem_key('symptoms', idem)
        if prior:
            return prior            # replayed offline write — already recorded
    sid = new_id()
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,region,logged_at,user_id,idem_key)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, name[:120], to_int(data.get('severity', 5), 5, lo=1, hi=10),
             data.get('date_key', today_iso()),
             data.get('time_of_day','morning'), data.get('notes',''),
             _clean_region(data.get('region')), now_iso(),
             current_user_id(), idem), commit=True)
    return dict(execute("SELECT * FROM symptoms WHERE id=?", (sid,), fetchone=True))


def get_symptoms_by_region(days: int = 90) -> dict:
    """Count symptoms per body region over the window, for the body-map. Only
    the user's own logged symptoms; regions with none are omitted from `counts`
    but the full region list is returned so the map can render every zone."""
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=max(1, min(int(days or 90), 3650)))).isoformat()
    rows = execute("""SELECT region, name, severity, date_key FROM symptoms
                      WHERE user_id=? AND date_key>=? AND region!='' AND region IS NOT NULL
                      ORDER BY date_key DESC""",
                   (current_user_id(), start), fetchall=True) or []
    counts, worst = {}, {}
    for r in rows:
        rg = r['region']
        counts[rg] = counts.get(rg, 0) + 1
        sev = r['severity'] if isinstance(r['severity'], (int, float)) else 0
        worst[rg] = max(worst.get(rg, 0), sev)
    return {'regions': list(BODY_REGIONS),
            'counts': counts, 'worst': worst,
            'total': sum(counts.values()),
            'has_data': bool(counts)}

def get_symptoms(days: int = 14) -> list:
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = execute("SELECT * FROM symptoms WHERE date_key >= ? AND user_id=? ORDER BY logged_at DESC",
                   (start, current_user_id()), fetchall=True)
    return [dict(r) for r in rows]

def delete_symptom(sid: str):
    from .trash import soft_delete
    return soft_delete('symptoms', sid)


def get_symptom_med_timeline(days: int = 90) -> dict:
    """Data to overlay logged symptoms against when medicines started/changed.

    This surfaces *coincidence in time* only — e.g. a symptom that first appears
    a few days after a new medicine — so the user can raise it with their doctor.
    It is NOT a causal or clinical claim, and the UI must frame it that way."""
    import datetime as dt
    from db.medicines import list_medicines
    days = max(7, min(int(days or 90), 365))
    today = dt.date.today()
    start = today - dt.timedelta(days=days)

    meds = []
    for m in list_medicines():
        if not m['active']:
            continue
        sd = (m.get('start_date') or '')[:10]
        try:
            sdd = dt.date.fromisoformat(sd)
        except Exception:
            continue
        meds.append({'name': m['name'], 'start_date': sd, 'icon': m.get('icon') or '💊',
                     'purpose': m.get('purpose') or '',
                     'started_in_window': sdd >= start})
    meds.sort(key=lambda x: x['start_date'])

    syms = [{'name': s['name'], 'date': s['date_key'], 'severity': s.get('severity')}
            for s in get_symptoms(days)]
    syms.sort(key=lambda x: x['date'])

    # Real change events (a med stopped or deleted) also mark the timeline, so a
    # symptom that eases after stopping something is visible too — not just starts.
    from db.medicines import get_medicine_events
    changes = [{'name': e['med_name'], 'kind': e['kind'], 'date': (e['at'] or '')[:10]}
               for e in get_medicine_events(days)
               if e['kind'] in ('stopped', 'deleted') and (e['at'] or '')[:10] >= start.isoformat()]
    changes.sort(key=lambda x: x['date'])

    return {
        'range': {'from': start.isoformat(), 'to': today.isoformat(), 'days': days},
        'meds': meds,
        'changes': changes,
        'symptoms': syms,
        'has_data': bool(syms),
    }

# ── Vitals (BP, Blood Sugar) ──────────────────────────────────────────────────

# Physical-plausibility bounds — deliberately WIDE (not clinical-normal ranges,
# which live in the trend endpoint as chart reference lines). These only catch
# gross typos like a 9,000,000 bpm heart rate, and are permissive enough to
# accept temperatures in either °C or °F so a valid reading is never rejected.
# (value1, value2) — value2 applies to the diastolic of blood_pressure.
_VITAL_BOUNDS = {
    'blood_pressure': ((30, 400), (10, 300)),
    'heart_rate':     ((10, 350), None),
    'blood_sugar':    ((5, 2000), None),
    'spo2':           ((10, 100), None),
    'temperature':    ((25, 120), None),   # spans both °C and °F
    'peak_flow':      ((30, 900), None),   # L/min — guards typos, not a clinical range
}


def _fmt_reading(n):
    """Human-friendly number for error copy — no scientific notation."""
    return f'{n:,.0f}' if n == int(n) else f'{n:g}'


def _check_vital_range(vtype, value1, value2):
    bounds = _VITAL_BOUNDS.get(vtype)
    if not bounds:
        return   # unknown type: accept any finite value
    (lo1, hi1), b2 = bounds
    if not (lo1 <= value1 <= hi1):
        raise ValueError(f'That reading ({_fmt_reading(value1)}) looks off — please double-check it.')
    if b2 and value2 is not None and not (b2[0] <= value2 <= b2[1]):
        raise ValueError(f'That reading ({_fmt_reading(value2)}) looks off — please double-check it.')


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
    _check_vital_range(vtype, value1, value2)
    # Context is type-specific: a meal tag for blood_sugar, a home/clinic tag for
    # blood_pressure (K4). Anything else is ignored so a stray tag can't attach
    # itself to the wrong reading.
    context = ''
    c = str(data.get('context', '') or '').strip().lower()
    if vtype == 'blood_sugar':
        context = c if c in GLUCOSE_CONTEXTS else ''
    elif vtype == 'blood_pressure':
        context = c if c in ('home', 'clinic') else ''
    # Validate the date, like log_sleep/log_body_metric do: an unchecked date_key
    # both orphans the reading on a non-navigable day AND (before escaping was
    # added downstream) let arbitrary text reach a render sink. Bad input files
    # under today rather than being trusted.
    date_key = data.get('date_key') or today_iso()
    if not valid_date(date_key):
        date_key = today_iso()
    # A replayed offline write carries the original action's key — return the
    # row we already stored instead of inserting a duplicate reading.
    from .core import clean_idem_key, find_by_idem_key
    idem = clean_idem_key(data.get('idem_key'))
    if idem:
        prior = find_by_idem_key('vitals', idem)
        if prior:
            return prior
    vid = new_id()
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,notes,context,logged_at,user_id,idem_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (vid, date_key, vtype,
             value1, value2,
             data.get('unit',''), data.get('notes',''), context, now_iso(),
             current_user_id(), idem), commit=True)
    return dict(execute("SELECT * FROM vitals WHERE id=?", (vid,), fetchone=True))


# Meal contexts for a glucose reading — the label a clinician reads a sugar
# against. 'random' = no particular relation to a meal.
GLUCOSE_CONTEXTS = ('fasting', 'pre_meal', 'post_meal', 'bedtime', 'random')


def get_glucose_logbook(days: int = 30) -> dict:
    """Blood-sugar readings grouped by meal context, with per-context stats and
    (if the user set a blood_sugar target) an in/below/above flag on each row.

    A fasting 95 and a post-meal 160 are both 'normal' — but only once you know
    which is which. This view keeps that context attached so the numbers read the
    way a doctor would read them, instead of one undifferentiated sugar average.
    """
    import datetime as dt
    from db.vital_targets import get_targets, flag
    start = (dt.date.today() - dt.timedelta(days=max(1, days))).isoformat()
    rows = execute("""SELECT * FROM vitals WHERE type='blood_sugar' AND date_key >= ? AND user_id=?
                      ORDER BY logged_at DESC""",
                   (start, current_user_id()), fetchall=True)
    target = get_targets().get('blood_sugar')
    groups = {}
    readings = []
    for r in rows:
        d = dict(r)
        ctx = d.get('context') or 'random'
        if ctx not in GLUCOSE_CONTEXTS:
            ctx = 'random'
        val = d['value1']
        f = flag('blood_sugar', val, {'blood_sugar': target}) if target else None
        item = {'id': d['id'], 'value': val, 'context': ctx,
                'date_key': d['date_key'], 'logged_at': d['logged_at'],
                'notes': d.get('notes', ''), 'flag': f}
        readings.append(item)
        g = groups.setdefault(ctx, {'context': ctx, 'values': [], 'high': 0, 'low': 0})
        g['values'].append(val)
        if f == 'above':
            g['high'] += 1
        elif f == 'below':
            g['low'] += 1
    summary = []
    for ctx in GLUCOSE_CONTEXTS:
        g = groups.get(ctx)
        if not g:
            continue
        vals = g['values']
        summary.append({
            'context': ctx,
            'count': len(vals),
            'avg': round(sum(vals) / len(vals), 1),
            'min': min(vals),
            'max': max(vals),
            'high': g['high'],
            'low': g['low'],
        })
    return {
        'days': days,
        'target': target,        # {'target_min','target_max'} or None
        'summary': summary,      # per-context roll-up, only contexts with data
        'readings': readings,    # newest-first flat list
        'has_data': bool(readings),
    }

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
    from .trash import soft_delete
    return soft_delete('vitals', vid)


# ── Emergency QR (for the health-ID card) ────────────────────────────────────

def _emergency_qr_text() -> str:
    """A compact, offline-readable emergency summary — what a first responder
    needs at a glance. Built from the user's own emergency + profile rows; no
    URL, so it works without a network."""
    from .food import get_profile
    e = get_emergency_info() or {}
    p = get_profile() or {}
    urow = execute("SELECT name FROM users WHERE id=? LIMIT 1", (current_user_id(),), fetchone=True)
    name = (p.get('name') or (urow['name'] if urow else '') or '').strip()
    lines = ['EMERGENCY' + (f' - {name}' if name else '')]
    if e.get('blood_type'):
        lines.append(f"Blood: {e['blood_type']}")
    if e.get('allergies'):
        lines.append(f"Allergies: {e['allergies']}")
    if e.get('conditions'):
        lines.append(f"Conditions: {e['conditions']}")
    c1n, c1p = (e.get('contact1_name') or '').strip(), (e.get('contact1_phone') or '').strip()
    if c1n or c1p:
        lines.append(f"ICE: {c1n} {c1p}".strip())
    # QR capacity is finite — keep the payload sane.
    return '\n'.join(lines)[:600]


def build_emergency_qr() -> dict:
    """A self-contained SVG QR of the emergency summary. `available` is False
    (with no svg) when the optional `segno` library isn't installed or there's
    nothing worth encoding — the UI then simply omits the QR."""
    text = _emergency_qr_text()
    # Only worth a QR once there's more than the bare "EMERGENCY" header.
    if '\n' not in text:
        return {'available': False, 'reason': 'no_emergency_info', 'svg': None}
    try:
        import segno
    except ImportError:
        return {'available': False, 'reason': 'qr_lib_missing', 'svg': None}
    try:
        import io
        qr = segno.make(text, error='m')
        buf = io.StringIO()
        qr.save(buf, kind='svg', scale=4, border=2, dark='#243027')
        return {'available': True, 'svg': buf.getvalue(), 'text': text}
    except Exception:
        return {'available': False, 'reason': 'qr_error', 'svg': None}


# ── Condition-tailored daily check-in ────────────────────────────────────────
# Each focus maps to the specific readings worth capturing daily. Diabetes uses
# the fasting/post-meal glucose contexts (from the logbook feature); hypertension
# is a single daily BP. Kept small on purpose — a focused ask beats a long form.
CONDITION_FOCUSES = {
    'diabetes': {
        'label': 'Diabetes',
        'prompts': [
            {'key': 'sugar_fasting', 'label': 'Fasting sugar', 'type': 'blood_sugar', 'context': 'fasting', 'unit': 'mg/dL'},
            {'key': 'sugar_post',    'label': 'After-meal sugar', 'type': 'blood_sugar', 'context': 'post_meal', 'unit': 'mg/dL'},
        ],
    },
    'hypertension': {
        'label': 'Blood pressure',
        'prompts': [
            {'key': 'bp', 'label': "Today's blood pressure", 'type': 'blood_pressure', 'context': '', 'unit': 'mmHg'},
        ],
    },
}


def get_condition_focus():
    r = execute("SELECT condition_focus FROM user_profile WHERE user_id=? LIMIT 1",
                (current_user_id(),), fetchone=True)
    f = (r or {}).get('condition_focus') if r else None
    return f if f in CONDITION_FOCUSES else None


def set_condition_focus(focus):
    from .food import get_profile
    uid = current_user_id()
    get_profile()          # ensure a row
    f = str(focus or '').strip().lower()
    if f not in CONDITION_FOCUSES:
        f = ''
    execute("UPDATE user_profile SET condition_focus=? WHERE user_id=?", (f, uid), commit=True)
    return f or None


def get_condition_checkin() -> dict:
    """Today's tailored check-in for the user's chosen condition: which of its
    readings are already logged today and which are still open. None focus →
    empty, so the dashboard shows nothing until the user opts in."""
    focus = get_condition_focus()
    if not focus:
        return {'focus': None, 'prompts': [], 'options': [
            {'key': k, 'label': v['label']} for k, v in CONDITION_FOCUSES.items()]}
    today = user_today()      # the USER's day, matching how the client stamps date_key
    uid = current_user_id()
    prompts = []
    for p in CONDITION_FOCUSES[focus]['prompts']:
        if p['type'] == 'blood_sugar' and p['context']:
            row = execute("""SELECT value1, value2 FROM vitals WHERE user_id=? AND type='blood_sugar'
                             AND context=? AND date_key=? ORDER BY logged_at DESC LIMIT 1""",
                          (uid, p['context'], today), fetchone=True)
        else:
            row = execute("""SELECT value1, value2 FROM vitals WHERE user_id=? AND type=?
                             AND date_key=? ORDER BY logged_at DESC LIMIT 1""",
                          (uid, p['type'], today), fetchone=True)
        r = dict(row) if row else None
        prompts.append({**p, 'done': bool(row),
                        'value': (r.get('value1') if r else None),
                        'value2': (r.get('value2') if r else None)})
    return {'focus': focus, 'focus_label': CONDITION_FOCUSES[focus]['label'],
            'prompts': prompts,
            'all_done': all(p['done'] for p in prompts),
            'options': [{'key': k, 'label': v['label']} for k, v in CONDITION_FOCUSES.items()]}


# ── Blood-pressure & resting-HR classification ───────────────────────────────
# Standard, published bands (ACC/AHA 2017 for BP; common adult resting-HR
# ranges). These describe a single reading — a category, not a diagnosis; a
# clinic diagnoses hypertension off repeated readings, not one.
_BP_BANDS = ['normal', 'elevated', 'stage1', 'stage2', 'crisis']
_BP_LABEL = {'normal': 'Normal', 'elevated': 'Elevated', 'stage1': 'Stage 1',
             'stage2': 'Stage 2', 'crisis': 'Crisis'}
_HR_LABEL = {'low': 'Low', 'normal': 'Normal', 'high': 'High'}


def classify_bp(systolic, diastolic):
    """Return (band, label) for a BP reading using the worse of the two numbers,
    or (None, None) if either is missing/invalid."""
    try:
        s = float(systolic); d = float(diastolic)
    except (TypeError, ValueError):
        return None, None
    if not (math.isfinite(s) and math.isfinite(d)):
        return None, None
    if s > 180 or d > 120:
        band = 'crisis'
    elif s >= 140 or d >= 90:
        band = 'stage2'
    elif s >= 130 or d >= 80:
        band = 'stage1'
    elif s >= 120:
        band = 'elevated'
    else:
        band = 'normal'
    return band, _BP_LABEL[band]


def classify_hr(bpm):
    """Return (band, label) for a resting heart rate. 'low' is framed neutrally —
    trained people sit below 60 without concern — so the UI never alarms on it."""
    try:
        b = float(bpm)
    except (TypeError, ValueError):
        return None, None
    if not math.isfinite(b):
        return None, None
    band = 'low' if b < 60 else 'high' if b > 100 else 'normal'
    return band, _HR_LABEL[band]


def get_vital_categories(days: int = 90) -> dict:
    """Recent BP and resting-HR readings, each tagged with its standard category,
    plus a per-category distribution — so the user sees where their readings sit
    at a glance. Only their own data; empty sections are omitted."""
    import datetime as dt
    uid = current_user_id()
    start = (dt.date.today() - dt.timedelta(days=max(1, days))).isoformat()

    bp_rows = execute("""SELECT value1, value2, date_key FROM vitals
                         WHERE type='blood_pressure' AND user_id=? AND date_key>=?
                         ORDER BY date_key DESC, logged_at DESC""",
                      (uid, start), fetchall=True) or []
    bp_readings, bp_dist = [], {b: 0 for b in _BP_BANDS}
    for r in bp_rows:
        band, label = classify_bp(r['value1'], r['value2'])
        if not band:
            continue
        bp_dist[band] += 1
        bp_readings.append({'systolic': r['value1'], 'diastolic': r['value2'],
                            'date': r['date_key'], 'band': band, 'label': label})

    hr_rows = execute("""SELECT value1, date_key FROM vitals
                         WHERE type='heart_rate' AND user_id=? AND date_key>=?
                         ORDER BY date_key DESC, logged_at DESC""",
                      (uid, start), fetchall=True) or []
    hr_readings, hr_dist = [], {'low': 0, 'normal': 0, 'high': 0}
    for r in hr_rows:
        band, label = classify_hr(r['value1'])
        if not band:
            continue
        hr_dist[band] += 1
        hr_readings.append({'bpm': r['value1'], 'date': r['date_key'], 'band': band, 'label': label})

    return {
        'days': days,
        'bp': {'latest': bp_readings[0] if bp_readings else None,
               'distribution': [{'band': b, 'label': _BP_LABEL[b], 'count': bp_dist[b]} for b in _BP_BANDS],
               'total': len(bp_readings)},
        'hr': {'latest': hr_readings[0] if hr_readings else None,
               'distribution': [{'band': b, 'label': _HR_LABEL[b], 'count': hr_dist[b]} for b in ('low', 'normal', 'high')],
               'total': len(hr_readings)},
        'has_data': bool(bp_readings or hr_readings),
    }

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
               insurance_provider=?,insurance_number=?,
               organ_donor=?,directive_wishes=?,directive_location=?,updated_at=? WHERE id=? AND user_id=?""",
            (data.get('blood_type',''), data.get('allergies',''), data.get('conditions',''),
             data.get('medications',''), data.get('contact1_name',''), data.get('contact1_phone',''),
             data.get('contact2_name',''), data.get('contact2_phone',''),
             data.get('insurance_provider',''), data.get('insurance_number',''),
             str(data.get('organ_donor','') or '')[:40],
             str(data.get('directive_wishes','') or '')[:500],
             str(data.get('directive_location','') or '')[:200],
             now_iso(), e['id'], current_user_id()), commit=True)
    return get_emergency_info()


# ── Appointments (doctor visits, lab tests, vaccinations) ────────────────────

_APPT_KINDS = {'doctor', 'lab', 'vaccine', 'other'}


def _valid_date(s):
    import datetime as dt
    try:
        return dt.date.fromisoformat(str(s)[:10]).isoformat()
    except Exception:
        return None


def _clean_reminder_days(v, default=1):
    """Days before the appointment to nudge (0–30). 0 = only the morning-of."""
    try:
        return max(0, min(int(v), 30))
    except (TypeError, ValueError):
        return default


def _valid_provider_id(pid):
    """Only accept a provider the caller actually owns (else NULL) — keeps the
    appointment→care-team link honest and un-spoofable."""
    pid = str(pid or '').strip()
    if not pid:
        return None
    own = execute("SELECT id FROM providers WHERE id=? AND user_id=?",
                  (pid, current_user_id()), fetchone=True)
    return pid if own else None


def create_appointment(data: dict) -> dict:
    title = str(data.get('title', '')).strip()
    if not title:
        raise ValueError('An appointment title is required')
    date = _valid_date(data.get('date'))
    if not date:
        raise ValueError('A valid date (YYYY-MM-DD) is required')
    kind = data.get('kind', 'doctor')
    if kind not in _APPT_KINDS:
        kind = 'other'
    time = str(data.get('time', '') or '')[:5]
    provider_id = _valid_provider_id(data.get('provider_id'))
    aid = new_id()
    execute("""INSERT INTO appointments
                 (id,user_id,title,kind,date,time,location,notes,remind,reminder_days,provider_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, current_user_id(), title[:160], kind, date, time,
             str(data.get('location', ''))[:200], str(data.get('notes', ''))[:500],
             0 if data.get('remind') is False else 1, _clean_reminder_days(data.get('reminder_days')),
             provider_id, now_iso()), commit=True)
    return dict(execute("SELECT * FROM appointments WHERE id=? AND user_id=?",
                        (aid, current_user_id()), fetchone=True))


def list_appointments(upcoming_only: bool = False) -> list:
    uid = current_user_id()
    if upcoming_only:
        rows = execute("""SELECT * FROM appointments WHERE user_id=? AND date >= ?
                          ORDER BY date, time""", (uid, today_iso()), fetchall=True)
    else:
        rows = execute("""SELECT * FROM appointments WHERE user_id=?
                          ORDER BY date DESC, time""", (uid,), fetchall=True)
    return [dict(r) for r in rows]


def update_appointment(aid: str, data: dict) -> dict:
    """Edit an existing appointment (fix a typo, reschedule, or add post-visit
    notes). Only the caller's own row; unknown fields ignored; validation mirrors
    create so a bad edit can't corrupt the row."""
    uid = current_user_id()
    row = execute("SELECT * FROM appointments WHERE id=? AND user_id=?", (aid, uid), fetchone=True)
    if not row:
        raise ValueError('Appointment not found')
    cur = dict(row)
    title = str(data.get('title', cur['title'])).strip() or cur['title']
    # Mirror create: an explicitly-supplied but invalid date is an error, not a
    # silent keep (which would falsely report "rescheduled").
    if 'date' in data:
        date = _valid_date(data.get('date'))
        if not date:
            raise ValueError('A valid date (YYYY-MM-DD) is required')
    else:
        date = cur['date']
    kind = data.get('kind', cur['kind'])
    if kind not in _APPT_KINDS:
        kind = cur['kind']
    time = str(data.get('time', cur['time']) or '')[:5]
    remind = cur['remind'] if 'remind' not in data else (0 if data.get('remind') is False else 1)
    reminder_days = _clean_reminder_days(data['reminder_days'], cur.get('reminder_days', 1)) \
        if 'reminder_days' in data else cur.get('reminder_days', 1)
    # Post-visit capture (J6): what the doctor said + follow-ups. Only overwritten
    # when explicitly supplied, so editing a reminder can't wipe visit notes.
    visit_summary = str(data.get('visit_summary', cur.get('visit_summary', '')))[:2000] \
        if 'visit_summary' in data else cur.get('visit_summary', '')
    follow_up = str(data.get('follow_up', cur.get('follow_up', '')))[:2000] \
        if 'follow_up' in data else cur.get('follow_up', '')
    provider_id = _valid_provider_id(data.get('provider_id')) if 'provider_id' in data \
        else cur.get('provider_id')
    execute("""UPDATE appointments SET title=?, kind=?, date=?, time=?, location=?, notes=?, remind=?, reminder_days=?,
               visit_summary=?, follow_up=?, provider_id=?
               WHERE id=? AND user_id=?""",
            (title[:160], kind, date, time,
             str(data.get('location', cur['location']))[:200],
             str(data.get('notes', cur['notes']))[:500], remind, reminder_days,
             visit_summary, follow_up, provider_id, aid, uid), commit=True)
    return dict(execute("SELECT * FROM appointments WHERE id=? AND user_id=?", (aid, uid), fetchone=True))


def delete_appointment(aid: str):
    from .trash import soft_delete
    return soft_delete('appointments', aid)


def get_next_appointment():
    """The soonest upcoming appointment — for the dashboard. None if none."""
    r = execute("""SELECT * FROM appointments WHERE user_id=? AND date >= ?
                   ORDER BY date, time LIMIT 1""",
                (current_user_id(), today_iso()), fetchone=True)
    return dict(r) if r else None


# ── Doctor-visit prep questions ──────────────────────────────────────────────

def add_doctor_question(text: str, appointment_id: str = None) -> dict:
    """Add a question to ask a doctor. appointment_id=None → the general
    'ask at my next visit' list; a real id → pinned to that specific visit
    (the visit-flow). If an id is given it must be the caller's own appointment."""
    q = str(text or '').strip()
    if not q:
        raise ValueError('A question is required')
    if appointment_id:
        own = execute("SELECT id FROM appointments WHERE id=? AND user_id=?",
                      (appointment_id, current_user_id()), fetchone=True)
        if not own:
            raise ValueError('Appointment not found')
    qid = new_id()
    execute("""INSERT INTO doctor_questions (id,user_id,question,asked,created_at,appointment_id)
               VALUES (?,?,?,0,?,?)""",
            (qid, current_user_id(), q[:400], now_iso(), appointment_id or None), commit=True)
    return dict(execute("SELECT * FROM doctor_questions WHERE id=? AND user_id=?",
                        (qid, current_user_id()), fetchone=True))


def list_doctor_questions() -> list:
    """The GENERAL question list only (appointment_id IS NULL). Per-visit
    questions live in the visit detail, so they don't clutter this list."""
    rows = execute("""SELECT * FROM doctor_questions
                      WHERE user_id=? AND appointment_id IS NULL
                      ORDER BY asked, created_at""", (current_user_id(),), fetchall=True)
    return [dict(r) for r in rows]


def toggle_doctor_question(qid: str):
    """Flip 'asked' — only touches the caller's own row."""
    execute("""UPDATE doctor_questions SET asked = CASE WHEN asked=1 THEN 0 ELSE 1 END
               WHERE id=? AND user_id=?""", (qid, current_user_id()), commit=True)


def delete_doctor_question(qid: str):
    execute("DELETE FROM doctor_questions WHERE id=? AND user_id=?",
            (qid, current_user_id()), commit=True)


# ── Measurement reminders (check your BP / sugar / weight …) ─────────────────

_MEASURE_KINDS = {'blood_pressure', 'blood_sugar', 'weight', 'spo2',
                  'temperature', 'heart_rate'}


def add_measurement_reminder(kind: str, time: str) -> dict:
    if kind not in _MEASURE_KINDS:
        raise ValueError('Pick a measurement to be reminded about')
    t = str(time or '')[:5]
    if len(t) != 5 or t[2] != ':':
        raise ValueError('A valid time (HH:MM) is required')
    rid = new_id()
    execute("""INSERT INTO measurement_reminders (id,user_id,kind,time,enabled,created_at)
               VALUES (?,?,?,?,1,?)""",
            (rid, current_user_id(), kind, t, now_iso()), commit=True)
    return dict(execute("SELECT * FROM measurement_reminders WHERE id=? AND user_id=?",
                        (rid, current_user_id()), fetchone=True))


def list_measurement_reminders() -> list:
    rows = execute("""SELECT * FROM measurement_reminders WHERE user_id=?
                      ORDER BY time""", (current_user_id(),), fetchall=True) or []
    return [dict(r) for r in rows]


def toggle_measurement_reminder(rid: str) -> dict:
    uid = current_user_id()
    r = execute("SELECT enabled FROM measurement_reminders WHERE id=? AND user_id=?",
                (rid, uid), fetchone=True)
    if not r:
        return {}
    execute("UPDATE measurement_reminders SET enabled=? WHERE id=? AND user_id=?",
            (0 if r['enabled'] else 1, rid, uid), commit=True)
    return dict(execute("SELECT * FROM measurement_reminders WHERE id=? AND user_id=?",
                        (rid, uid), fetchone=True))


def delete_measurement_reminder(rid: str):
    execute("DELETE FROM measurement_reminders WHERE id=? AND user_id=?",
            (rid, current_user_id()), commit=True)
