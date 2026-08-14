"""
db/peak_flow.py — J2 peak-flow / respiratory tracker. Peak expiratory flow (PEF)
readings, zoned green / yellow / red against the user's OWN personal best — the
standard asthma-action-plan traffic-light system:

  green  >= 80% of personal best   (doing well)
  yellow  50-79%                    (caution)
  red    < 50%                      (get help)

The personal best is the highest reading the user has recorded — their own
number, not a population norm. Nothing here is a diagnosis; it's a way to read
your own trend the way an action plan does. Readings live in the shared `vitals`
table under type='peak_flow'.
"""
from .health import get_vitals
from .core import execute, current_user_id

_GREEN = 0.80
_YELLOW = 0.50


def _all_time_best():
    """The user's highest peak-flow reading EVER — the asthma-action-plan personal
    best. Must not be windowed: a best from a year ago still defines the zones, and
    a deflated best would push readings into a falsely-green zone (under-warning)."""
    r = execute("""SELECT MAX(value1) m FROM vitals
                   WHERE user_id=? AND type='peak_flow'""",
                (current_user_id(),), fetchone=True)
    try:
        return float(r['m']) if r and r['m'] is not None else None
    except (TypeError, ValueError):
        return None


def _zone(value, personal_best):
    if not personal_best:
        return None
    frac = value / personal_best
    if frac >= _GREEN:
        return 'green'
    if frac >= _YELLOW:
        return 'yellow'
    return 'red'


def get_peak_flow_state(days: int = 180) -> dict:
    """Recent PEF readings with their zones, the personal best, and the zone
    thresholds. Returns has_data False until there's at least one reading."""
    rows = get_vitals('peak_flow', days=days)      # newest first, own data only
    readings = []
    for r in rows:
        try:
            v = float(r['value1'])
        except (TypeError, ValueError):
            continue
        readings.append({'id': r['id'], 'value': v, 'date': r['date_key'],
                         'notes': r.get('notes', '')})
    if not readings:
        return {'has_data': False, 'personal_best': None, 'readings': []}

    # Order by the reading's own date (newest first), not insert time — a
    # backdated reading logged today must not read as "latest".
    readings.sort(key=lambda r: r['date'], reverse=True)

    # Zones are relative to the ALL-TIME best (not just the window's best), so an
    # older best still governs and readings aren't nudged into a greener zone.
    personal_best = _all_time_best() or max(r['value'] for r in readings)
    for r in readings:
        r['zone'] = _zone(r['value'], personal_best)
        r['pct_of_best'] = round(r['value'] / personal_best * 100)

    latest = readings[0]        # most recent reading date
    return {
        'has_data': True,
        'personal_best': personal_best,
        'green_min': round(personal_best * _GREEN),     # >= this = green
        'yellow_min': round(personal_best * _YELLOW),   # >= this = yellow, else red
        'latest': latest,
        'readings': readings,
    }
