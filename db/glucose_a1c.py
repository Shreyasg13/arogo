"""
db/glucose_a1c.py — K2 estimated HbA1c from logged glucose. Applies the published
ADAG (A1c-Derived Average Glucose) linear relationship to the average of the
user's own blood-sugar readings:

    A1c(%) = (mean glucose mg/dL + 46.7) / 28.7          (Nathan et al., 2008)

This is the same class of standard formula as BMI: a validated conversion applied
to the user's own numbers, always framed as an ESTIMATE. It is NOT a lab HbA1c —
spot fingersticks aren't a true 24-hour average — so it needs a reasonable number
of readings and is presented as a rough figure to discuss with a doctor.
"""
from .health import get_vitals

_MIN_READINGS = 10   # too few readings and an "average glucose" means little


def _mgdl(value):
    """Blood-sugar readings are stored in mg/dL. Guard the mmol/L case (a value
    under ~40 is almost certainly mmol/L) by converting, so a stray unit doesn't
    produce a wild A1c."""
    v = float(value)
    return v * 18.0 if v < 40 else v


def estimate_a1c(days: int = 90) -> dict:
    """Estimated A1c from the mean of blood-sugar readings over the window
    (defaults to ~3 months, the span an A1c reflects). has_data is False until
    there are at least _MIN_READINGS."""
    rows = get_vitals('blood_sugar', days=days)
    values = []
    for r in rows:
        try:
            values.append(_mgdl(r['value1']))
        except (TypeError, ValueError):
            continue
    if len(values) < _MIN_READINGS:
        return {'has_data': False, 'count': len(values), 'min_readings': _MIN_READINGS}

    mean_glucose = sum(values) / len(values)
    a1c = (mean_glucose + 46.7) / 28.7
    return {
        'has_data': True,
        'avg_glucose': round(mean_glucose),
        'estimated_a1c': round(a1c, 1),
        'count': len(values),
        'days': days,
        'min_readings': _MIN_READINGS,
    }
