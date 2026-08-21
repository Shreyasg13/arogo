"""
db/environment.py — local air quality & weather vs how you feel.

Air quality is a real daily concern in India, but the app runs offline, so you
bring the data in: import a simple daily CSV (date + AQI, optionally temperature
/ humidity), and Arogo lines it up against your symptoms and vitals to show
whether they *moved together*.

HONESTY — correlation is NOT causation. A link between AQI and how you felt is
just that: they rose and fell together over these days. Many things move at once,
and one person's data can't prove cause. We require enough shared days before
showing anything, we say "moved together / opposite / no clear link" (never
"AQI caused your symptoms"), and every result carries that caveat. Import parses
only — nothing is saved until you confirm.
"""
from __future__ import annotations

import csv, io, datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today

_DATE_KEYS = ('date', 'day', 'timestamp', 'time')
_AQI_KEYS = ('aqi', 'air quality', 'us aqi', 'pm2.5', 'pm25', 'pm 2.5', 'index')
_TEMP_KEYS = ('temp', 'temperature')
_HUM_KEYS = ('humidity', 'rh', 'humid')

MIN_PAIRS = 6           # need at least this many shared days to correlate


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _parse_date(s):
    s = str(s or '').strip()[:10]
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%m/%d/%Y'):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _find_col(headers, keys):
    for i, h in enumerate(headers):
        hl = (h or '').strip().lower()
        if any(k in hl for k in keys):
            return i
    return None


def parse_environment_csv(text):
    """Detect date/aqi/temp/humidity columns and return candidate day rows.
    Saves nothing — the caller previews then commits."""
    try:
        rows = list(csv.reader(io.StringIO(text or '')))
    except Exception:
        rows = []
    rows = [r for r in rows if any((c or '').strip() for c in r)]
    if len(rows) < 2:
        return {'candidates': [], 'skipped': 0, 'detected': None}
    headers = rows[0]
    di = _find_col(headers, _DATE_KEYS)
    ai = _find_col(headers, _AQI_KEYS)
    ti = _find_col(headers, _TEMP_KEYS)
    hi = _find_col(headers, _HUM_KEYS)
    if di is None or ai is None:
        return {'candidates': [], 'skipped': len(rows) - 1, 'detected': None}

    cand, skipped, seen = [], 0, set()
    for r in rows[1:]:
        date_key = _parse_date(r[di]) if di < len(r) else None
        aqi = _num(r[ai]) if ai < len(r) else None
        if not date_key or aqi is None or aqi < 0 or aqi > 1000 or date_key in seen:
            skipped += 1
            continue
        seen.add(date_key)
        cand.append({
            'date_key': date_key, 'aqi': round(aqi, 1),
            'temp_c': round(_num(r[ti]), 1) if ti is not None and ti < len(r) and _num(r[ti]) is not None else None,
            'humidity': round(_num(r[hi]), 1) if hi is not None and hi < len(r) and _num(r[hi]) is not None else None,
        })
    return {'candidates': cand, 'skipped': skipped,
            'detected': {'aqi': True, 'temp': ti is not None, 'humidity': hi is not None}}


def commit_environment(candidates):
    """Upsert one row per day (re-importing a day replaces it)."""
    uid = current_user_id()
    saved = 0
    for c in (candidates or []):
        date_key = _parse_date(c.get('date_key'))
        aqi = _num(c.get('aqi'))
        if not date_key or aqi is None:
            continue
        execute("DELETE FROM environment_days WHERE user_id=? AND date_key=?", (uid, date_key), commit=True)
        execute("""INSERT INTO environment_days (id, date_key, aqi, temp_c, humidity, source, created_at, user_id)
                   VALUES (?,?,?,?,?, 'import', ?, ?)""",
                (new_id(), date_key, round(aqi, 1),
                 _num(c.get('temp_c')), _num(c.get('humidity')), now_iso(), uid), commit=True)
        saved += 1
    return {'saved': saved}


def list_environment(days=30):
    uid = current_user_id()
    start = (dt.date.fromisoformat(user_today()) - dt.timedelta(days=days)).isoformat()
    rows = execute("""SELECT date_key, aqi, temp_c, humidity FROM environment_days
                      WHERE user_id=? AND date_key>=? ORDER BY date_key DESC""",
                   (uid, start), fetchall=True) or []
    return [dict(r) for r in rows]


# What you can line AQI up against.
_TARGETS = {
    'symptoms':       {'label': 'Symptom entries', 'kind': 'symptoms'},
    'blood_pressure': {'label': 'Blood pressure (systolic)', 'kind': 'metric', 'key': 'blood_pressure'},
    'heart_rate':     {'label': 'Heart rate', 'kind': 'metric', 'key': 'heart_rate'},
    'sleep_hours':    {'label': 'Sleep', 'kind': 'metric', 'key': 'sleep_hours'},
}


def target_options():
    return [{'key': k, 'label': v['label']} for k, v in _TARGETS.items()]


def _aqi_series(uid, start):
    rows = execute("""SELECT date_key, AVG(aqi) v FROM environment_days
                      WHERE user_id=? AND date_key>=? AND aqi IS NOT NULL GROUP BY date_key""",
                   (uid, start), fetchall=True) or []
    return {r['date_key']: r['v'] for r in rows if r['v'] is not None}


def _symptom_series(uid, start):
    rows = execute("""SELECT date_key, COUNT(*) v FROM symptoms
                      WHERE user_id=? AND date_key>=? GROUP BY date_key""",
                   (uid, start), fetchall=True) or []
    return {r['date_key']: r['v'] for r in rows}


def get_environment_correlation(target='symptoms', days=90):
    """Correlate daily AQI with a chosen 'how you feel' series. Descriptive only."""
    uid = current_user_id()
    try:
        days = max(14, min(int(days or 90), 366))
    except (TypeError, ValueError):
        days = 90
    tgt = _TARGETS.get(target) or _TARGETS['symptoms']
    start = (dt.date.fromisoformat(user_today()) - dt.timedelta(days=days)).isoformat()

    from .metric_insights import _series, _pearson, STRONG

    aqi = _aqi_series(uid, start)
    if tgt['kind'] == 'symptoms':
        # A day WITH AQI data but no symptom logged is a real 0, not a gap — so
        # symptom count defaults to 0 across the AQI days.
        sc = _symptom_series(uid, start)
        other = {d: sc.get(d, 0) for d in aqi}
    else:
        other = _series(tgt['key'], start)

    shared = sorted(set(aqi) & set(other))
    pairs = [(aqi[d], other[d]) for d in shared]
    base = {'target': target, 'target_label': tgt['label'], 'n': len(pairs), 'days': days,
            'have_environment': bool(aqi),
            'caveat': ("This shows AQI and how you felt moving together over these days — "
                       "a correlation, not proof that air quality caused anything. Many "
                       "things change at once.")}
    if len(pairs) < MIN_PAIRS:
        return {**base, 'has_data': False,
                'reason': 'Not enough shared days yet — import more AQI data and keep logging.'}
    r = _pearson(pairs)
    if r is None:
        return {**base, 'has_data': True, 'r': None, 'direction': 'no_link'}
    direction = 'together' if r >= STRONG else 'opposite' if r <= -STRONG else 'no_link'
    return {**base, 'has_data': True, 'r': round(r, 2), 'direction': direction,
            'points': [{'x': round(x, 1), 'y': round(y, 2)} for (x, y) in pairs]}
