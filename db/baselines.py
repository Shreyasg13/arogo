"""
db/baselines.py — J7 "your own normal". For a few core vitals, compute a personal
baseline band from the user's OWN readings (mean ± 1 SD) alongside how the latest
reading sits against it. This complements the population reference bands (I6/H1):
"normal for you" can differ from "normal in general", and a value inside your own
band but outside the textbook range — or vice versa — is worth noticing.

Purely descriptive statistics of the user's own logs. Needs enough readings to
mean anything (>= _MIN_N); nothing is computed from fabricated data.
"""
import math

from .core import execute, current_user_id
import datetime as _dt

_MIN_N = 8   # too few readings and a "band" is just noise


def _stats(values):
    n = len(values)
    mean = sum(values) / n
    # Sample standard deviation (n-1); 0 when all readings are identical.
    var = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    return mean, math.sqrt(var)


def _fetch_vital(vtype, days):
    uid = current_user_id()
    start = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    rows = execute("""SELECT value1, date_key FROM vitals
                      WHERE user_id=? AND type=? AND date_key>=? ORDER BY date_key""",
                   (uid, vtype, start), fetchall=True) or []
    return [(float(r['value1']), r['date_key']) for r in rows
            if isinstance(r['value1'], (int, float))]


def _fetch_weight(days):
    uid = current_user_id()
    start = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    rows = execute("""SELECT weight_kg, date_key FROM body_metrics
                      WHERE user_id=? AND weight_kg IS NOT NULL AND date_key>=? ORDER BY date_key""",
                   (uid, start), fetchall=True) or []
    return [(float(r['weight_kg']), r['date_key']) for r in rows
            if isinstance(r['weight_kg'], (int, float))]


def get_personal_baselines(days: int = 180) -> dict:
    """Per metric: your mean and a ±1 SD band from your own readings, plus the
    latest reading and whether it sits within/above/below your band. Metrics with
    fewer than _MIN_N readings are omitted."""
    days = max(7, min(int(days or 180), 3650))
    metrics = [
        ('systolic',   'Systolic BP',        'mmHg', 0, _fetch_vital('blood_pressure', days)),
        ('heart_rate', 'Resting heart rate', 'bpm',  0, _fetch_vital('heart_rate', days)),
        ('weight',     'Weight',             'kg',   1, _fetch_weight(days)),
    ]

    out = []
    for key, label, unit, decimals, series in metrics:
        if len(series) < _MIN_N:
            continue
        values = [v for v, _ in series]
        mean, sd = _stats(values)
        low, high = mean - sd, mean + sd
        latest_v, latest_d = series[-1]
        if latest_v < low:
            position = 'below'
        elif latest_v > high:
            position = 'above'
        else:
            position = 'within'
        r = lambda x: round(x, decimals)
        out.append({
            'key': key, 'label': label, 'unit': unit,
            'mean': r(mean), 'sd': round(sd, 1),
            'low': r(low), 'high': r(high),
            'count': len(values),
            'latest': r(latest_v), 'latest_date': latest_d,
            'position': position,
        })

    return {'has_data': bool(out), 'metrics': out, 'min_readings': _MIN_N}
