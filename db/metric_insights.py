"""
db/metric_insights.py — "do these two things move together?" explorer.

Pick any two tracked metrics; over the shared days, compute a correlation and
report it honestly as move-together / move-opposite / no-clear-link. Never
claims causation, and stays silent until there are enough shared days to mean
anything. All the user's own data.
"""
from __future__ import annotations
import math

from .core import execute, current_user_id

# Each metric maps to a per-day series query. Vitals use value1; others have
# their own table. Add a row here to expose another numeric metric.
METRICS = {
    'blood_pressure': {'label': 'Blood pressure (systolic)', 'kind': 'vital', 'type': 'blood_pressure', 'unit': 'mmHg'},
    'blood_sugar':    {'label': 'Blood sugar',    'kind': 'vital', 'type': 'blood_sugar', 'unit': 'mg/dL'},
    'heart_rate':     {'label': 'Resting heart rate', 'kind': 'vital', 'type': 'heart_rate', 'unit': 'bpm'},
    'spo2':           {'label': 'SpO2',           'kind': 'vital', 'type': 'spo2', 'unit': '%'},
    'temperature':    {'label': 'Temperature',    'kind': 'vital', 'type': 'temperature', 'unit': ''},
    'weight':         {'label': 'Weight',         'kind': 'body', 'unit': 'kg'},
    'sleep_hours':    {'label': 'Sleep hours',    'kind': 'sleep', 'unit': 'h'},
    'hydration_ml':   {'label': 'Water',          'kind': 'hydration', 'unit': 'ml'},
}

MIN_PAIRS = 6          # fewer shared days than this = not enough to judge
STRONG = 0.4           # |r| at/above this earns a direction label


def _series(key: str, start: str) -> dict:
    """{date_key: value} for a metric over the window, one value per day."""
    m = METRICS.get(key)
    if not m:
        return {}
    uid = current_user_id()
    if m['kind'] == 'vital':
        rows = execute("""SELECT date_key, AVG(value1) v FROM vitals
                          WHERE type=? AND user_id=? AND date_key>=? AND value1 IS NOT NULL
                          GROUP BY date_key""", (m['type'], uid, start), fetchall=True) or []
    elif m['kind'] == 'body':
        rows = execute("""SELECT date_key, AVG(weight_kg) v FROM body_metrics
                          WHERE user_id=? AND date_key>=? AND weight_kg IS NOT NULL
                          GROUP BY date_key""", (uid, start), fetchall=True) or []
    elif m['kind'] == 'sleep':
        rows = execute("""SELECT date_key, AVG(duration_h) v FROM sleep_logs
                          WHERE user_id=? AND date_key>=? AND duration_h IS NOT NULL
                          GROUP BY date_key""", (uid, start), fetchall=True) or []
    elif m['kind'] == 'hydration':
        rows = execute("""SELECT date_key, SUM(amount_ml) v FROM hydration_logs
                          WHERE user_id=? AND date_key>=?
                          GROUP BY date_key""", (uid, start), fetchall=True) or []
    else:
        rows = []
    return {r['date_key']: r['v'] for r in rows if r['v'] is not None}


def _pearson(pairs):
    n = len(pairs)
    if n < 2:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    if sxx <= 0 or syy <= 0:      # one metric was flat → correlation undefined
        return None
    return sxy / math.sqrt(sxx * syy)


def get_correlatable_metrics(days: int = 90) -> dict:
    """Metrics that have at least a few logged days, so the picker only offers
    ones that could actually be compared."""
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=max(1, days))).isoformat()
    out = []
    for key, m in METRICS.items():
        n = len(_series(key, start))
        if n >= 3:
            out.append({'key': key, 'label': m['label'], 'unit': m['unit'], 'days': n})
    return {'metrics': out}


def get_metric_correlation(metric_a: str, metric_b: str, days: int = 90) -> dict:
    import datetime as dt
    days = max(7, min(int(days or 90), 366))
    if metric_a not in METRICS or metric_b not in METRICS or metric_a == metric_b:
        return {'has_data': False, 'error': 'pick two different tracked metrics'}
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    sa, sb = _series(metric_a, start), _series(metric_b, start)
    shared = sorted(set(sa) & set(sb))
    pairs = [(sa[d], sb[d]) for d in shared]

    ma, mb = METRICS[metric_a], METRICS[metric_b]
    base = {'a': metric_a, 'b': metric_b, 'a_label': ma['label'], 'b_label': mb['label'],
            'a_unit': ma['unit'], 'b_unit': mb['unit'], 'n': len(pairs), 'days': days}
    if len(pairs) < MIN_PAIRS:
        return {**base, 'has_data': False, 'reason': 'not enough shared days yet'}
    r = _pearson(pairs)
    if r is None:
        return {**base, 'has_data': True, 'r': None, 'direction': 'no_link'}
    direction = 'together' if r >= STRONG else 'opposite' if r <= -STRONG else 'no_link'
    return {**base, 'has_data': True, 'r': round(r, 2), 'direction': direction,
            'points': [{'x': round(x, 2), 'y': round(y, 2)} for (x, y) in pairs]}
