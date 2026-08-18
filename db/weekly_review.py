"""
db/weekly_review.py — a once-a-week guided review you complete and revisit.

Not another passive recap email: it stitches the week's honest numbers —
medication adherence, which way the vitals moved, this-week-vs-last deltas, and
the parts of your record that went stale — from the app's EXISTING recap
functions (nothing recomputed or invented), then ends with a short reflection
YOU write: what went well, and one focus for next week. The reflection is saved
per week and shown back to you over time, which is what makes it a ritual rather
than a report.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today


def _week_start(iso_today):
    """Monday of the week containing `iso_today` (ISO date string)."""
    d = dt.date.fromisoformat(iso_today)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def get_weekly_review():
    """Everything the ritual shows: composed week summary + this week's saved
    reflection (if any) + a short history of past reflections."""
    uid = current_user_id()
    ws = _week_start(user_today())

    # Reuse — never rebuild — the vetted recap logic.
    from .insights import generate_health_review
    from .week_review import get_week_over_week
    from .data_trust import get_data_trust

    review = generate_health_review(7)
    deltas = (get_week_over_week() or {}).get('metrics', [])
    trust = get_data_trust()
    gaps = [r['label'] for r in (trust.get('freshness') or []) if r.get('status') == 'stale']

    saved = execute("SELECT wins, focus, updated_at FROM weekly_reviews WHERE user_id=? AND week_start=?",
                    (uid, ws), fetchone=True)
    history = execute("""SELECT week_start, wins, focus FROM weekly_reviews
                         WHERE user_id=? AND week_start<>? AND (wins<>'' OR focus<>'')
                         ORDER BY week_start DESC LIMIT 6""",
                      (uid, ws), fetchall=True) or []

    return {
        'week_start': ws,
        'review': review,
        'deltas': deltas,
        'gaps': gaps,
        'saved': dict(saved) if saved else None,
        'history': [dict(h) for h in history],
    }


def save_weekly_review(wins, focus):
    """Upsert this week's reflection (one row per user per week)."""
    uid = current_user_id()
    ws = _week_start(user_today())
    wins = str(wins or '')[:2000]
    focus = str(focus or '')[:2000]
    existing = execute("SELECT id FROM weekly_reviews WHERE user_id=? AND week_start=?",
                       (uid, ws), fetchone=True)
    if existing:
        execute("UPDATE weekly_reviews SET wins=?, focus=?, updated_at=? WHERE id=? AND user_id=?",
                (wins, focus, now_iso(), existing['id'], uid), commit=True)
    else:
        execute("""INSERT INTO weekly_reviews (id, week_start, wins, focus, created_at, updated_at, user_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (new_id(), ws, wins, focus, now_iso(), now_iso(), uid), commit=True)
    return {'week_start': ws, 'wins': wins, 'focus': focus}
