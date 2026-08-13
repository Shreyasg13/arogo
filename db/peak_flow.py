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

_GREEN = 0.80
_YELLOW = 0.50


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

    personal_best = max(r['value'] for r in readings)
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
