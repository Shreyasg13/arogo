"""
db/year_story.py — an honest "year in health" recap.

A cinematic, motivating look back over a period (a year by default) — how many
days you showed up, doses taken, vitals recorded, workouts, and a few milestones.
Built ONLY from what you actually logged: no invented "health score", no verdicts,
and every highlight is threshold-gated so a near-empty account never gets a
fabricated brag.

Two audiences:
  • get_year_story() — the full in-app recap (your own eyes), may include health
    values (a weight change, your most-logged symptom).
  • story_public_safe() — the shareable subset: consistency + counts only. It
    strips anything the share wall forbids (no symptom names, no weight/vital
    values, and never journal/mood/cycle — which the story never reads anyway).
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, user_today


def _label(days):
    if days >= 360:
        return 'Your last year'
    if days >= 180:
        return 'Your last 6 months'
    if days >= 90:
        return 'Your last 90 days'
    return f'Your last {days} days'


def _count(table, col, start, end, uid, extra=''):
    try:
        row = execute(f"SELECT COUNT(*) c FROM {table} WHERE user_id=? AND {col} BETWEEN ? AND ? {extra}",
                      (uid, start, end), fetchone=True)
        return int(row['c']) if row else 0
    except Exception:
        return 0


def _distinct_days(table, col, start, end, uid):
    try:
        rows = execute(f"SELECT DISTINCT {col} d FROM {table} WHERE user_id=? AND {col} BETWEEN ? AND ?",
                       (uid, start, end), fetchall=True) or []
        return {str(r['d'])[:10] for r in rows if r['d']}
    except Exception:
        return set()


def get_year_story(days=365):
    """Full recap for the calling user's own view."""
    uid = current_user_id()
    try:
        days = max(30, min(int(days or 365), 366))
    except (TypeError, ValueError):
        days = 365
    end = user_today()
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)).isoformat()

    counts = {
        'vitals':       _count('vitals', 'date_key', start, end, uid),
        'foods':        _count('food_logs', 'date_key', start, end, uid),
        'workouts':     _count('fitness_activities', 'date', start, end, uid),
        'labs':         _count('lab_results', 'date_key', start, end, uid),
        'appointments': _count('appointments', 'date', start, end, uid),
        'symptoms':     _count('symptoms', 'date_key', start, end, uid),
        'sleep_nights': _count('sleep_logs', 'date_key', start, end, uid),
    }
    doses_taken = _count('dose_logs', 'date_key', start, end, uid, extra='AND taken=1')

    # Distinct days you logged ANYTHING — "you showed up N days".
    active = set()
    for table, col in [('dose_logs', 'date_key'), ('vitals', 'date_key'), ('food_logs', 'date_key'),
                       ('body_metrics', 'date_key'), ('sleep_logs', 'date_key'), ('symptoms', 'date_key'),
                       ('hydration_logs', 'date_key'), ('fitness_activities', 'date')]:
        active |= _distinct_days(table, col, start, end, uid)
    active_days = len(active)

    # Best perfect-medication-day streak inside the window (cheap; capped at 365).
    try:
        from .medicines import get_adherence_streak
        streak = get_adherence_streak(min(days, 365)) or {}
    except Exception:
        streak = {}

    # A weight change, if there are two points to compare (in-app only, private).
    weight_change = None
    try:
        rows = execute("""SELECT date_key, weight_kg FROM body_metrics
                          WHERE user_id=? AND date_key BETWEEN ? AND ? AND weight_kg IS NOT NULL
                          ORDER BY date_key""", (uid, start, end), fetchall=True) or []
        if len(rows) >= 2:
            a, b = rows[0]['weight_kg'], rows[-1]['weight_kg']
            weight_change = {'from': round(a, 1), 'to': round(b, 1), 'delta': round(b - a, 1)}
    except Exception:
        pass

    # Most-logged symptom (in-app only, private).
    top_symptom = None
    try:
        r = execute("""SELECT name, COUNT(*) c FROM symptoms
                       WHERE user_id=? AND date_key BETWEEN ? AND ?
                       GROUP BY name ORDER BY c DESC LIMIT 1""", (uid, start, end), fetchone=True)
        if r and r['c']:
            top_symptom = {'name': r['name'], 'count': int(r['c'])}
    except Exception:
        pass

    # Highlights — only what the data supports; `public` marks shareable ones.
    hl = []
    if active_days:
        hl.append({'icon': '📅', 'text': f'You showed up {active_days} day{"s" if active_days != 1 else ""}', 'public': True})
    if doses_taken:
        hl.append({'icon': '💊', 'text': f'{doses_taken} dose{"s" if doses_taken != 1 else ""} taken', 'public': True})
    if streak.get('best', 0) >= 3:
        hl.append({'icon': '🔥', 'text': f'Best streak: {streak["best"]} perfect days', 'public': True})
    if counts['vitals']:
        hl.append({'icon': '❤️', 'text': f'{counts["vitals"]} vitals recorded', 'public': True})
    if counts['workouts']:
        hl.append({'icon': '🏃', 'text': f'{counts["workouts"]} workouts logged', 'public': True})
    if counts['labs']:
        hl.append({'icon': '🧪', 'text': f'{counts["labs"]} lab result{"s" if counts["labs"] != 1 else ""} on file', 'public': True})
    if counts['foods']:
        hl.append({'icon': '🍽️', 'text': f'{counts["foods"]} meals logged', 'public': True})
    # Private (in-app only) highlights.
    if weight_change and weight_change['delta']:
        d = weight_change['delta']
        hl.append({'icon': '⚖️', 'text': f'Weight {"down" if d < 0 else "up"} {abs(d)} kg over the period', 'public': False})
    if top_symptom:
        hl.append({'icon': '📝', 'text': f'Most-noted symptom: {top_symptom["name"]} ({top_symptom["count"]}×)', 'public': False})

    started = bool(active_days or doses_taken or any(counts.values()))

    return {
        'period': {'days': days, 'start': start, 'end': end, 'label': _label(days)},
        'active_days': active_days,
        'total_days': days,
        'doses_taken': doses_taken,
        'streak': {'streak': streak.get('streak', 0), 'best': streak.get('best', 0)},
        'counts': counts,
        'highlights': hl,
        'weight_change': weight_change,
        'top_symptom': top_symptom,
        'started': started,
    }


def story_public_safe(story):
    """The shareable subset of a story: consistency + counts only. Strips every
    health value and keeps only highlights flagged public — so a shared story can
    never leak a symptom name, a weight, a vital, or anything private."""
    s = story or {}
    return {
        'period': s.get('period', {}),
        'active_days': s.get('active_days', 0),
        'total_days': s.get('total_days', 0),
        'doses_taken': s.get('doses_taken', 0),
        'streak': s.get('streak', {}),
        'counts': {k: v for k, v in (s.get('counts') or {}).items() if k != 'symptoms'},
        'highlights': [h for h in (s.get('highlights') or []) if h.get('public')],
    }
