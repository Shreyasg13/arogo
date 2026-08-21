"""
db/experiments.py — honest N-of-1 self-experiments.

Pick a change you're trying ("cut coffee after 2pm") and a metric to watch
(sleep, blood pressure…). We compare that metric's average in a BEFORE window
(the baseline just before you started) with an AFTER window (since you started),
using only your own logs.

HONESTY — load-bearing: this is observation, NOT proof. A before/after
difference is a *clue*, never a cause: many things change at once, and a single
person's data can't establish causation. Every result carries that caveat, we
require enough readings on BOTH sides before showing a number, and we never say
a change "worked", "caused", or "improved" anything — we report the difference
and let you weigh it.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date

MIN_READINGS = 3          # need at least this many on each side to compare
_DEFAULT_BASELINE = 14

# Watchable metrics. Each: window aggregation + how the value reads.
# `agg`: 'avg' (mean of readings), 'sumday' (mean of daily totals),
# 'countday' (entries per day over the window).
_METRICS = {
    'sleep_hours':  {'label': 'Sleep', 'unit': 'h', 'table': 'sleep_logs',
                     'col': 'duration_h', 'agg': 'avg', 'where': ''},
    'weight':       {'label': 'Weight', 'unit': 'kg', 'table': 'body_metrics',
                     'col': 'weight_kg', 'agg': 'avg', 'where': ''},
    'bp_systolic':  {'label': 'Blood pressure (systolic)', 'unit': 'mmHg', 'table': 'vitals',
                     'col': 'value1', 'agg': 'avg', 'where': "AND type='blood_pressure'"},
    'bp_diastolic': {'label': 'Blood pressure (diastolic)', 'unit': 'mmHg', 'table': 'vitals',
                     'col': 'value2', 'agg': 'avg', 'where': "AND type='blood_pressure'"},
    'blood_sugar':  {'label': 'Blood sugar', 'unit': 'mg/dL', 'table': 'vitals',
                     'col': 'value1', 'agg': 'avg', 'where': "AND type='blood_sugar'"},
    'heart_rate':   {'label': 'Heart rate', 'unit': 'bpm', 'table': 'vitals',
                     'col': 'value1', 'agg': 'avg', 'where': "AND type='heart_rate'"},
    'water_daily':  {'label': 'Water', 'unit': 'ml/day', 'table': 'hydration_logs',
                     'col': 'amount_ml', 'agg': 'sumday', 'where': ''},
    'symptom_freq': {'label': 'Symptom entries', 'unit': '/day', 'table': 'symptoms',
                     'col': '*', 'agg': 'countday', 'where': ''},
}


def metric_options():
    return [{'key': k, 'label': m['label'], 'unit': m['unit']} for k, m in _METRICS.items()]


def _window_stat(m, uid, start, end):
    """{avg, n} for one metric over [start, end] (inclusive ISO dates)."""
    t, col, where, agg = m['table'], m['col'], m.get('where', ''), m['agg']
    try:
        if agg == 'avg':
            r = execute(f"SELECT AVG({col}) a, COUNT({col}) n FROM {t} "
                        f"WHERE user_id=? AND date_key BETWEEN ? AND ? {where} AND {col} IS NOT NULL",
                        (uid, start, end), fetchone=True)
            return {'avg': round(r['a'], 1) if r and r['a'] is not None else None,
                    'n': int(r['n']) if r and r['n'] else 0}
        if agg == 'sumday':
            rows = execute(f"SELECT date_key, SUM({col}) s FROM {t} "
                           f"WHERE user_id=? AND date_key BETWEEN ? AND ? GROUP BY date_key",
                           (uid, start, end), fetchall=True) or []
            vals = [row['s'] for row in rows if row['s'] is not None]
            return {'avg': round(sum(vals) / len(vals)) if vals else None, 'n': len(vals)}
        if agg == 'countday':
            r = execute(f"SELECT COUNT(*) c FROM {t} WHERE user_id=? AND date_key BETWEEN ? AND ?",
                        (uid, start, end), fetchone=True)
            total = int(r['c']) if r and r['c'] else 0
            days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
            return {'avg': round(total / days, 2) if days > 0 else None, 'n': total}
    except Exception:
        pass
    return {'avg': None, 'n': 0}


def _result(exp):
    """Compute the before/after comparison for one experiment row."""
    m = _METRICS.get(exp['metric'])
    if not m:
        return None
    uid = exp['user_id']
    start = exp['start_date']
    baseline_days = int(exp.get('baseline_days') or _DEFAULT_BASELINE)
    end = exp.get('end_date') or user_today()
    s_date = dt.date.fromisoformat(start)
    before_start = (s_date - dt.timedelta(days=baseline_days)).isoformat()
    before_end = (s_date - dt.timedelta(days=1)).isoformat()

    before = _window_stat(m, uid, before_start, before_end)
    after = _window_stat(m, uid, start, end)
    enough = before['n'] >= MIN_READINGS and after['n'] >= MIN_READINGS
    delta = None
    if enough and before['avg'] is not None and after['avg'] is not None:
        delta = round(after['avg'] - before['avg'], 2)
    return {
        'metric': exp['metric'], 'metric_label': m['label'], 'unit': m['unit'],
        'before': before, 'after': after,
        'before_window': [before_start, before_end], 'after_window': [start, end],
        'delta': delta, 'enough_data': enough, 'min_readings': MIN_READINGS,
    }


def create_experiment(data):
    title = str((data or {}).get('title') or '').strip()
    if not title:
        raise ValueError('What are you trying? Give the experiment a title.')
    metric = (data or {}).get('metric')
    if metric not in _METRICS:
        raise ValueError('Pick a metric to watch.')
    start = (data or {}).get('start_date')
    if not valid_date(start):
        start = user_today()
    try:
        baseline = max(3, min(int((data or {}).get('baseline_days') or _DEFAULT_BASELINE), 90))
    except (TypeError, ValueError):
        baseline = _DEFAULT_BASELINE
    eid = new_id()
    execute("""INSERT INTO experiments (id, title, metric, start_date, baseline_days, status, notes, created_at, user_id)
               VALUES (?,?,?,?,?, 'active', ?, ?, ?)""",
            (eid, title[:160], metric, start, baseline, str((data or {}).get('notes') or '')[:500],
             now_iso(), current_user_id()), commit=True)
    return get_experiment(eid)


def get_experiment(eid):
    r = execute("SELECT * FROM experiments WHERE id=? AND user_id=?",
                (eid, current_user_id()), fetchone=True)
    if not r:
        return None
    d = dict(r)
    d['result'] = _result(d)
    return d


def list_experiments():
    rows = execute("SELECT * FROM experiments WHERE user_id=? ORDER BY status='ended', created_at DESC",
                   (current_user_id(),), fetchall=True) or []
    out = []
    for r in rows:
        d = dict(r)
        d['result'] = _result(d)
        out.append(d)
    return out


def end_experiment(eid):
    execute("UPDATE experiments SET status='ended', end_date=? WHERE id=? AND user_id=? AND status='active'",
            (user_today(), eid, current_user_id()), commit=True)
    return get_experiment(eid)


def delete_experiment(eid):
    execute("DELETE FROM experiments WHERE id=? AND user_id=?", (eid, current_user_id()), commit=True)
