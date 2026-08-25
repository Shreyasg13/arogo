"""
db/goals.py — outcome health goals with a finish line.

A goal is a metric + a target + a direction + an optional deadline (e.g. "HbA1c
below 6.5 by December", "reach 8,000 steps/day"). Progress is DERIVED from the
user's own logged values — never invented — and framed honestly: if there's no
current reading, we say "log a <metric> to see progress" rather than guess.
"""
import datetime as _dt
import math

from .core import execute, now_iso, new_id, current_user_id, valid_date, user_today

# metric → how to read its latest value + display + default direction.
# dir: 'below' (lower is better: weight loss, HbA1c), 'above' (higher is better:
# HDL, weight gain), 'reach' (hit a number: steps).
METRICS = {
    'weight':          {'name': 'Weight',          'unit': 'kg',    'dir': 'below', 'src': ('body', 'weight_kg')},
    'body_fat':        {'name': 'Body fat',        'unit': '%',     'dir': 'below', 'src': ('body', 'body_fat_pct')},
    'hba1c':           {'name': 'HbA1c',           'unit': '%',     'dir': 'below', 'src': ('lab', 'hba1c')},
    'ldl':             {'name': 'LDL cholesterol', 'unit': 'mg/dL', 'dir': 'below', 'src': ('lab', 'ldl')},
    'fasting_glucose': {'name': 'Fasting glucose', 'unit': 'mg/dL', 'dir': 'below', 'src': ('lab', 'fasting_glucose')},
    'systolic_bp':     {'name': 'Systolic BP',     'unit': 'mmHg',  'dir': 'below', 'src': ('vital', 'blood_pressure')},
    'steps':           {'name': 'Daily steps',     'unit': 'steps', 'dir': 'reach', 'src': ('steps', None)},
    'custom':          {'name': 'Custom goal',     'unit': '',      'dir': 'reach', 'src': (None, None)},
}
_DIRS = {'below', 'above', 'reach'}


def _num(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def latest_value(metric):
    """The user's most-recent logged value for a metric, or None. Read-only."""
    uid = current_user_id()
    meta = METRICS.get(metric)
    if not meta:
        return None
    kind, key = meta['src']
    if kind == 'body':
        r = execute(f"""SELECT {key} v FROM body_metrics WHERE user_id=? AND {key} IS NOT NULL
                        ORDER BY date_key DESC, created_at DESC LIMIT 1""", (uid,), fetchone=True)
        return r['v'] if r else None
    if kind == 'lab':
        r = execute("""SELECT value v FROM lab_results WHERE user_id=? AND lab_key=?
                       ORDER BY date_key DESC, created_at DESC LIMIT 1""", (uid, key), fetchone=True)
        return r['v'] if r else None
    if kind == 'vital':
        r = execute("""SELECT value1 v FROM vitals WHERE user_id=? AND type=?
                       ORDER BY logged_at DESC LIMIT 1""", (uid, key), fetchone=True)
        return r['v'] if r else None
    if kind == 'steps':
        r = execute("""SELECT steps v FROM fitness_activities WHERE user_id=? AND steps > 0
                       ORDER BY date DESC, created_at DESC LIMIT 1""", (uid,), fetchone=True)
        return r['v'] if r else None
    return None


def _progress(direction, start, current, target):
    """0..1 progress + achieved flag. None progress when we can't compute it
    honestly (no current reading, or a degenerate start==target for below/above)."""
    if current is None:
        return None, False
    if direction == 'reach':
        pct = current / target if target else 0
        return max(0.0, min(pct, 1.0)), current >= target
    if direction == 'below':
        achieved = current <= target
        if start is None or start <= target:
            return (1.0 if achieved else None), achieved
        pct = (start - current) / (start - target)
        return max(0.0, min(pct, 1.0)), achieved
    # above
    achieved = current >= target
    if start is None or start >= target:
        return (1.0 if achieved else None), achieved
    pct = (current - start) / (target - start)
    return max(0.0, min(pct, 1.0)), achieved


def create_goal(metric, target_value, direction=None, deadline=None, title='') -> dict:
    if metric not in METRICS:
        raise ValueError('Unknown metric')
    target = _num(target_value)
    if target is None:
        raise ValueError('A numeric target is required')
    if target <= 0:
        raise ValueError('Target must be greater than zero')
    direction = direction if direction in _DIRS else METRICS[metric]['dir']
    dl = deadline if (deadline and valid_date(deadline)) else None
    # Capture today's value as the baseline (so "below/above" progress has a
    # from-point). None if nothing logged yet — progress fills in once they log.
    start = latest_value(metric) if metric != 'custom' else None
    gid = new_id()
    execute("""INSERT INTO health_goals
                 (id, title, metric, target_value, direction, start_value, deadline, status, created_at, user_id)
               VALUES (?,?,?,?,?,?,?, 'active', ?,?)""",
            (gid, str(title or '')[:120], metric, target, direction, start, dl, now_iso(), current_user_id()),
            commit=True)
    return _decorate(execute("SELECT * FROM health_goals WHERE id=?", (gid,), fetchone=True))


def update_goal(gid, data) -> dict:
    uid = current_user_id()
    row = execute("SELECT * FROM health_goals WHERE id=? AND user_id=?", (gid, uid), fetchone=True)
    if not row:
        raise ValueError('Goal not found')
    status = data.get('status')
    if status in ('active', 'achieved', 'archived'):
        execute("UPDATE health_goals SET status=? WHERE id=? AND user_id=?", (status, gid, uid), commit=True)
    return _decorate(execute("SELECT * FROM health_goals WHERE id=? AND user_id=?", (gid, uid), fetchone=True))


def delete_goal(gid) -> bool:
    from .trash import soft_delete
    return soft_delete('health_goals', gid)
    return True


def _decorate(row):
    d = dict(row)
    meta = METRICS.get(d['metric'], METRICS['custom'])
    d['metric_name'] = meta['name']
    d['unit'] = meta['unit']
    current = latest_value(d['metric']) if d['metric'] != 'custom' else None
    d['current'] = current
    start = d['start_value']
    # Lazy baseline: if no reading existed at creation (start_value is NULL) but
    # one exists now, adopt it as the from-point and persist it. Without this a
    # below/above goal created before its first reading would be stuck showing
    # "no progress" forever, then jump straight to 100% on crossing the target.
    if start is None and current is not None and d['metric'] != 'custom':
        execute("UPDATE health_goals SET start_value=? WHERE id=? AND user_id=? AND start_value IS NULL",
                (current, d['id'], current_user_id()), commit=True)
        start = current
        d['start_value'] = current
    pct, achieved = _progress(d['direction'], start, current, d['target_value'])
    d['progress'] = pct
    d['auto_achieved'] = achieved
    # Days left (never negative-surprising: negative = overdue).
    d['days_left'] = None
    if d['deadline']:
        try:
            d['days_left'] = (_dt.date.fromisoformat(d['deadline']) - _dt.date.fromisoformat(user_today())).days
        except ValueError:
            pass
    return d


def list_goals(include_done=False) -> dict:
    uid = current_user_id()
    rows = execute("""SELECT * FROM health_goals WHERE user_id=?
                      ORDER BY (status<>'active'), created_at DESC""", (uid,), fetchall=True) or []
    goals = [_decorate(r) for r in rows]
    if not include_done:
        goals = [g for g in goals if g['status'] == 'active']
    return {'goals': goals,
            'metrics': [{'key': k, **{x: v[x] for x in ('name', 'unit', 'dir')}} for k, v in METRICS.items()]}
