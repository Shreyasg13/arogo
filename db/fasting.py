"""
db/fasting.py — intermittent-fasting window tracker.

A session is a start time + a target length (e.g. 16h) that the user ends when
they eat. Everything shown is measured from the user's own clock — elapsed and
remaining are derived, never invented. One active fast at a time.

Deliberately NOT gamified: no streak pressure, no "you failed" language. Fasting
can be a sensitive area; this is a neutral log, not a coach. The client shows a
soft note pointing anyone who feels food is controlling them toward support.
"""
import datetime as _dt
import math

from .core import execute, now_iso, new_id, current_user_id

MAX_HOURS = 48.0            # a sane upper bound; nothing longer is a "window"
DEFAULT_TARGET = 16.0


def _num(v, default=None):
    try:
        n = float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _parse(ts):
    """Parse an ISO datetime string to a naive datetime, or None."""
    if not ts:
        return None
    try:
        return _dt.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _hours_between(start_iso, end_iso):
    a, b = _parse(start_iso), _parse(end_iso)
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 3600.0, 2)


def get_active():
    uid = current_user_id()
    row = execute("SELECT * FROM fasting_sessions WHERE user_id=? AND status='active' "
                  "ORDER BY start_at DESC LIMIT 1", (uid,), fetchone=True)
    return _decorate(row) if row else None


def start_fast(target_hours=None, start_at=None, notes='') -> dict:
    uid = current_user_id()
    if get_active():
        raise ValueError('A fast is already in progress')
    target = _num(target_hours, DEFAULT_TARGET)
    if target is None or target <= 0:
        target = DEFAULT_TARGET
    target = min(target, MAX_HOURS)
    # A caller-supplied start must parse and not be in the future; otherwise use now.
    now = now_iso()
    start = start_at if (_parse(start_at) and _parse(start_at) <= _parse(now)) else now
    fid = new_id()
    execute("""INSERT INTO fasting_sessions
                 (id, start_at, end_at, target_hours, status, notes, created_at, user_id)
               VALUES (?,?,NULL,?, 'active', ?, ?, ?)""",
            (fid, start, target, str(notes or '')[:280], now, uid), commit=True)
    return _decorate(execute("SELECT * FROM fasting_sessions WHERE id=?", (fid,), fetchone=True))


def end_fast(fid=None, end_at=None) -> dict:
    """End the active fast (or a specific one). end_at defaults to now; a
    supplied end that predates the start, or doesn't parse, falls back to now."""
    uid = current_user_id()
    if fid:
        row = execute("SELECT * FROM fasting_sessions WHERE id=? AND user_id=?", (fid, uid), fetchone=True)
    else:
        row = execute("SELECT * FROM fasting_sessions WHERE user_id=? AND status='active' "
                      "ORDER BY start_at DESC LIMIT 1", (uid,), fetchone=True)
    if not row:
        raise ValueError('No fast to end')
    now = now_iso()
    end = end_at if (_parse(end_at) and _parse(end_at) >= _parse(row['start_at'])) else now
    execute("UPDATE fasting_sessions SET status='completed', end_at=? WHERE id=? AND user_id=?",
            (end, row['id'], uid), commit=True)
    return _decorate(execute("SELECT * FROM fasting_sessions WHERE id=?", (row['id'],), fetchone=True))


def delete_fast(fid) -> bool:
    execute("DELETE FROM fasting_sessions WHERE id=? AND user_id=?", (fid, current_user_id()), commit=True)
    return True


def _decorate(row):
    d = dict(row)
    active = d['status'] == 'active'
    end_ref = now_iso() if active else d['end_at']
    elapsed = _hours_between(d['start_at'], end_ref)
    d['elapsed_hours'] = elapsed
    d['duration_hours'] = None if active else elapsed
    target = d['target_hours'] or 0
    if elapsed is not None and target > 0:
        d['remaining_hours'] = round(max(0.0, target - elapsed), 2)
        d['reached_target'] = elapsed >= target
        d['progress'] = max(0.0, min(elapsed / target, 1.0))
    else:
        d['remaining_hours'] = None
        d['reached_target'] = False
        d['progress'] = None
    return d


def list_fasts(limit=30) -> dict:
    uid = current_user_id()
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 30
    rows = execute("""SELECT * FROM fasting_sessions WHERE user_id=? AND status='completed'
                      ORDER BY start_at DESC LIMIT ?""", (uid, limit), fetchall=True) or []
    history = [_decorate(r) for r in rows]
    durations = [h['duration_hours'] for h in history if h['duration_hours'] is not None]
    stats = {
        'completed': len(history),
        'avg_hours': round(sum(durations) / len(durations), 1) if durations else None,
        'longest_hours': round(max(durations), 1) if durations else None,
    }
    return {'active': get_active(), 'history': history, 'stats': stats,
            'presets': [
                {'label': '16:8',   'hours': 16},
                {'label': '18:6',   'hours': 18},
                {'label': '20:4',   'hours': 20},
                {'label': 'OMAD',   'hours': 23},
            ]}
