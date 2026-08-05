"""
db/vital_targets.py — personal target ranges for vitals.

The user records the band THEIR doctor set (e.g. "keep systolic BP under 130",
"fasting sugar 80–110"). Readings outside the band are flagged as
below/above — a nudge to discuss with a doctor, never a diagnosis. Distinct from
the wide physical-plausibility bounds used to reject typos on entry.
"""
from .core import execute, now_iso, new_id, current_user_id

# Which vitals can carry a target, and the value they band (value1).
VITAL_TYPES = ('blood_pressure', 'blood_sugar', 'heart_rate', 'weight', 'spo2', 'temperature')


def _num(v):
    try:
        n = float(v)
        return n if n == n and abs(n) != float('inf') else None
    except (TypeError, ValueError):
        return None


def set_target(vtype, target_min, target_max) -> dict:
    vtype = str(vtype or '').strip().lower()
    if vtype not in VITAL_TYPES:
        raise ValueError('Unknown vital')
    lo, hi = _num(target_min), _num(target_max)
    if lo is None and hi is None:
        raise ValueError('Give a low, a high, or both')
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo                         # tolerate swapped bounds
    uid = current_user_id()
    execute("DELETE FROM vital_targets WHERE user_id=? AND vtype=?", (uid, vtype), commit=True)
    execute("INSERT INTO vital_targets (id, vtype, target_min, target_max, updated_at, user_id) VALUES (?,?,?,?,?,?)",
            (new_id(), vtype, lo, hi, now_iso(), uid), commit=True)
    return {'vtype': vtype, 'target_min': lo, 'target_max': hi}


def clear_target(vtype) -> bool:
    execute("DELETE FROM vital_targets WHERE user_id=? AND vtype=?",
            (current_user_id(), str(vtype or '').strip().lower()), commit=True)
    return True


def get_targets() -> dict:
    rows = execute("SELECT vtype, target_min, target_max FROM vital_targets WHERE user_id=?",
                   (current_user_id(),), fetchall=True) or []
    return {r['vtype']: {'target_min': r['target_min'], 'target_max': r['target_max']} for r in rows}


def flag(vtype, value, targets=None):
    """'below' | 'above' | 'in' (within the user's band), or None if no target /
    no value. `targets` may be a preloaded dict to avoid a per-call query."""
    v = _num(value)
    if v is None:
        return None
    t = (targets or get_targets()).get(str(vtype or '').strip().lower())
    if not t:
        return None
    lo, hi = t.get('target_min'), t.get('target_max')
    if lo is not None and v < lo:
        return 'below'
    if hi is not None and v > hi:
        return 'above'
    return 'in'
