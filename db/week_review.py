"""
db/week_review.py — I10 "this week vs last" delta card. Compares the last 7 days
with the 7 before them across a few core metrics, and only reports a metric when
BOTH weeks actually have data — a comparison against an empty week would be
meaningless. Everything is the user's own logged data.

'higher_better' tells the UI how to colour a change: True (adherence, sleep),
or None where up/down carries no built-in verdict (weight, blood pressure) — we
show the direction but don't call it good or bad.
"""
import datetime as _dt

from .core import execute, current_user_id, user_today
from .medicines import list_medicines, _scheduled_on_day


def _windows():
    try:
        today = _dt.date.fromisoformat(user_today())
    except ValueError:
        today = _dt.date.today()
    this_start = today - _dt.timedelta(days=6)          # last 7 days incl. today
    last_end = this_start - _dt.timedelta(days=1)
    last_start = last_end - _dt.timedelta(days=6)
    return (this_start, today), (last_start, last_end)


def _avg(rows, col):
    vals = [r[col] for r in rows if isinstance(r[col], (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


def _adherence_pct(win):
    """Taken / scheduled over an inclusive [start, end] window, honouring each
    med's schedule. Returns None when nothing was scheduled that week."""
    uid = current_user_id()
    start, end = win
    meds = [m for m in list_medicines() if m['active'] and m.get('times')]
    taken = set()
    for r in (execute("""SELECT medicine_id, date_key, time_key FROM dose_logs
                         WHERE user_id=? AND taken=1 AND date_key>=? AND date_key<=?""",
                      (uid, start.isoformat(), end.isoformat()), fetchall=True) or []):
        taken.add((r['medicine_id'], r['date_key'], r['time_key']))
    total = hit = 0
    d = start
    while d <= end:
        ds = d.isoformat()
        for m in meds:
            if _scheduled_on_day(m, ds):
                for t in m.get('times', []):
                    total += 1
                    if (m['id'], ds, t) in taken:
                        hit += 1
        d += _dt.timedelta(days=1)
    return round(hit / total * 100, 1) if total else None


def _metric_avg(table, col, win, where_extra='', extra_params=()):
    uid = current_user_id()
    start, end = win
    rows = execute(
        f"SELECT {col} FROM {table} WHERE user_id=? AND date_key>=? AND date_key<=? {where_extra}",
        (uid, start.isoformat(), end.isoformat(), *extra_params), fetchall=True) or []
    return _avg(rows, col)


def _delta(this_v, last_v):
    if this_v is None or last_v is None:
        return None
    return round(this_v - last_v, 2)


def get_week_over_week() -> dict:
    """Per-metric {this, last, delta, dir, higher_better}, only for metrics with
    data in both weeks."""
    this_w, last_w = _windows()

    defs = [
        # key, label, unit, this, last, higher_better
        ('adherence', 'Adherence', '%',
         _adherence_pct(this_w), _adherence_pct(last_w), True),
        ('sleep', 'Sleep', 'h',
         _metric_avg('sleep_logs', 'duration_h', this_w),
         _metric_avg('sleep_logs', 'duration_h', last_w), True),
        ('weight', 'Weight', 'kg',
         _metric_avg('body_metrics', 'weight_kg', this_w),
         _metric_avg('body_metrics', 'weight_kg', last_w), None),
        ('bp_systolic', 'BP (systolic)', 'mmHg',
         _metric_avg('vitals', 'value1', this_w, "AND type='blood_pressure'"),
         _metric_avg('vitals', 'value1', last_w, "AND type='blood_pressure'"), None),
    ]

    metrics = []
    for key, label, unit, tv, lv, hb in defs:
        if tv is None or lv is None:
            continue        # need BOTH weeks — no half-comparisons
        delta = _delta(tv, lv)
        metrics.append({
            'key': key, 'label': label, 'unit': unit,
            'this': tv, 'last': lv, 'delta': delta,
            'dir': 'flat' if delta == 0 else ('up' if delta > 0 else 'down'),
            'higher_better': hb,
        })

    return {'has_data': bool(metrics),
            'this_week_start': this_w[0].isoformat(),
            'last_week_start': last_w[0].isoformat(),
            'metrics': metrics}
