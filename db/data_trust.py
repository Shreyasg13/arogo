"""
db/data_trust.py — honest data-freshness + confidence signals.

Elsewhere the app computes adherence %, trends and averages and shows them with
authority. This layer answers the quieter question the rest of the app doesn't:
*how current is your record, and how much data actually backs the numbers you're
shown?*

Two deliberate honesty rules:
  1. We never tell you how often you "should" log. We report facts only — when
     you last logged, and how many entries fall in the last 30 days — and let
     you weigh them. A tracker you've chosen never to use is never nagged about;
     only trackers you've actually used are surfaced.
  2. We flag summaries that rest on thin data (a "trend" from one reading, an
     adherence % from a handful of doses) so a small sample can't masquerade as
     a confident signal.

All strings here are structured data + English fallbacks; the frontend composes
and translates the user-facing sentence (freshness counts, "N days ago", etc.).
"""
from __future__ import annotations

from datetime import date, timedelta

from .core import execute, current_user_id, user_today

# Dated health signals. Only trackers the user has ACTUALLY used are ever
# surfaced. (key, table, date column, English label). Every table below carries
# a user_id column (originals via migrate_add_user_id, newer ones natively).
_TRACKERS = [
    ('doses',    'dose_logs',          'date_key', 'Medication doses'),
    ('vitals',   'vitals',             'date_key', 'Vitals'),
    ('weight',   'body_metrics',       'date_key', 'Body measurements'),
    ('labs',     'lab_results',        'date_key', 'Lab results'),
    ('symptoms', 'symptoms',           'date_key', 'Symptoms'),
    ('sleep',    'sleep_logs',         'date_key', 'Sleep'),
    ('food',     'food_logs',          'date_key', 'Food'),
    ('water',    'hydration_logs',     'date_key', 'Water'),
    ('activity', 'fitness_activities', 'date',     'Activity'),
]

# days-since thresholds for the neutral freshness band (no cadence is implied —
# these only describe how recent the newest entry is, not how often you "should"
# log). A tracker with total==1 is "thin" regardless of recency.
_RECENT_DAYS = 7
_WEEK_DAYS = 30
_THIN_TOTAL = 2           # <= this many entries → summaries can't show a trend
_THIN_ADHERENCE = 10      # < this many scheduled doses → adherence % is thin


def _days_since(iso_today: str, iso_then):
    """Whole days between two ISO dates, or None if either is unparseable."""
    if not iso_then:
        return None
    try:
        return (date.fromisoformat(iso_today) - date.fromisoformat(str(iso_then)[:10])).days
    except Exception:
        return None


def _band(days_since):
    if days_since is None:
        return 'none'
    if days_since <= _RECENT_DAYS:
        return 'recent'
    if days_since <= _WEEK_DAYS:
        return 'week'
    return 'stale'


def get_data_freshness():
    """Per-tracker freshness for trackers the user has actually used.

    Each record: {key, label, last_date, days_since, count_30d, total, status,
    thin}. `status` is a neutral recency band (recent / week / stale); `thin`
    means the whole tracker holds <=2 entries, so any "trend" over it is not yet
    meaningful. Never includes a tracker with zero entries.
    """
    uid = current_user_id()
    today = user_today()
    cutoff30 = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    out = []
    for key, table, dcol, label in _TRACKERS:
        try:
            row = execute(
                f"SELECT MAX({dcol}) AS last, COUNT(*) AS total, "
                f"SUM(CASE WHEN {dcol} >= ? THEN 1 ELSE 0 END) AS recent "
                f"FROM {table} WHERE user_id=?",
                (cutoff30, uid), fetchone=True) or {}
        except Exception:
            continue
        total = int(row.get('total') or 0)
        if total <= 0:
            continue                       # never used — don't surface or nag
        last = row.get('last')
        days = _days_since(today, last)
        out.append({
            'key': key,
            'label': label,
            'last_date': str(last)[:10] if last else None,
            'days_since': days,
            'count_30d': int(row.get('recent') or 0),
            'total': total,
            'status': _band(days),
            'thin': total <= _THIN_TOTAL,
        })
    # Stalest first so the tiles that most need attention lead; recency unknown
    # sorts last within its group.
    out.sort(key=lambda r: (-(r['days_since'] if r['days_since'] is not None else -1)))
    return out


def get_confidence_notes():
    """Honest caveats on headline numbers whose sample is thin. Structured so
    the frontend can localise the sentence. Empty when nothing is thin."""
    notes = []
    try:
        from .medicines import get_adherence_stats
        a = get_adherence_stats(30) or {}
        total = int(a.get('total') or 0)
        if 0 < total < _THIN_ADHERENCE:
            notes.append({'kind': 'thin_adherence', 'metric': 'adherence', 'count': total})
    except Exception:
        pass
    return notes


def get_data_trust():
    """Full payload for the Data check view: per-tracker freshness, thin-data
    caveats, and a small rollup. Purely descriptive — no advice, no verdicts."""
    fresh = get_data_freshness()
    notes = get_confidence_notes()
    return {
        'freshness': fresh,
        'notes': notes,
        'today': user_today(),
        'summary': {
            'tracked': len(fresh),
            'stale': sum(1 for r in fresh if r['status'] == 'stale'),
            'thin': sum(1 for r in fresh if r['thin']),
        },
    }
