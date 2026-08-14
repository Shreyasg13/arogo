"""
db/bp_patterns.py — K4 home-vs-clinic BP and K5 morning-vs-evening BP.

K4 surfaces the "white-coat" effect: readings tagged 'clinic' compared with those
tagged 'home'. K5 splits readings by the time of day they were logged (a proxy
for when they were taken), since morning highs matter clinically.

Both are plain averages of the user's own blood-pressure readings — descriptive,
never a diagnosis. A comparison only appears when BOTH groups have data.
"""
import datetime as _dt

from .core import execute, current_user_id


def _bp_rows(days):
    uid = current_user_id()
    start = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    return execute("""SELECT value1, value2, context, logged_at FROM vitals
                      WHERE user_id=? AND type='blood_pressure' AND date_key>=?""",
                   (uid, start), fetchall=True) or []


def _avg_bp(rows):
    sys = [r['value1'] for r in rows if isinstance(r['value1'], (int, float))]
    dia = [r['value2'] for r in rows if isinstance(r['value2'], (int, float))]
    if not sys:
        return None
    return {
        'systolic': round(sum(sys) / len(sys)),
        'diastolic': round(sum(dia) / len(dia)) if dia else None,
        'count': len(sys),
    }


def get_bp_home_vs_clinic(days: int = 180) -> dict:
    """Average BP for home-tagged vs clinic-tagged readings, and the gap. Only
    reported when both groups have at least one reading."""
    days = max(7, min(int(days or 180), 3650))
    rows = _bp_rows(days)
    home = _avg_bp([r for r in rows if r['context'] == 'home'])
    clinic = _avg_bp([r for r in rows if r['context'] == 'clinic'])
    if not home or not clinic:
        return {'has_data': False, 'home': home, 'clinic': clinic}
    gap = clinic['systolic'] - home['systolic']
    return {
        'has_data': True, 'home': home, 'clinic': clinic,
        'systolic_gap': gap,                 # +ve = higher at the clinic (white-coat)
        'white_coat': gap >= 10,             # a commonly-cited threshold, framed loosely
    }


# Morning = on-waking window; evening = before-bed window. Readings outside these
# (midday/overnight) don't belong to either and are left out of this split.
# CAVEAT: logged_at is the server-local wall clock at entry time (now_iso()), used
# here as a proxy for when the reading was taken. On a server whose timezone
# matches the user's (the intended single-user self-hosted setup) this is accurate;
# a UTC-hosted server with a distant-timezone user would misbucket. Vitals don't
# store a user-tz timestamp, so a fully tz-correct split would need a schema change.
def _slot(logged_at):
    try:
        h = int(str(logged_at)[11:13])
    except (ValueError, IndexError):
        return None
    if 4 <= h < 12:
        return 'morning'
    if 17 <= h < 24:
        return 'evening'
    return None


def get_bp_time_pattern(days: int = 180) -> dict:
    """Average BP for morning vs evening readings (by the time each was logged).
    Only reported when both slots have data."""
    days = max(7, min(int(days or 180), 3650))
    rows = _bp_rows(days)
    morning = _avg_bp([r for r in rows if _slot(r['logged_at']) == 'morning'])
    evening = _avg_bp([r for r in rows if _slot(r['logged_at']) == 'evening'])
    if not morning or not evening:
        return {'has_data': False, 'morning': morning, 'evening': evening}
    return {
        'has_data': True, 'morning': morning, 'evening': evening,
        'systolic_gap': morning['systolic'] - evening['systolic'],  # +ve = higher in the morning
    }
