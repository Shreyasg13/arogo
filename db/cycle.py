"""
db/cycle.py — Menstrual cycle tracking.

A deliberately small, honest model: each row is one period with a start date and
an (optional, while ongoing) end date. Everything else — cycle length, period
length, the next-period estimate, where you are in the current cycle — is DERIVED
from the sequence of starts, never stored, so it can't drift from the truth.

Predictions are only offered once there are at least two recorded cycles to
average, and are always framed as estimates from the user's own history — the
app never invents a number about someone's body.
"""
from __future__ import annotations

import datetime as _dt

from .core import execute, now_iso, new_id, current_user_id

_RECENT = 6   # average the last few cycles, so a changing pattern is reflected


def _today():
    from .core import user_today
    return user_today()


def _rows():
    """All cycles for the user, newest start first."""
    uid = current_user_id()
    rows = execute("""SELECT id, start_date, end_date, notes FROM menstrual_cycles
                      WHERE user_id=? ORDER BY start_date DESC""", (uid,), fetchall=True) or []
    return [dict(r) for r in rows]


def _valid_date(s):
    try:
        _dt.date.fromisoformat(str(s))
        return True
    except (ValueError, TypeError):
        return False


def log_period_start(start_date: str, notes: str = '') -> dict:
    """Record a new period start. Idempotent on the date — starting the same day
    twice updates the row rather than stacking duplicates."""
    if not _valid_date(start_date):
        raise ValueError('A valid start date is required')
    uid = current_user_id()
    existing = execute("SELECT id FROM menstrual_cycles WHERE user_id=? AND start_date=?",
                       (uid, start_date), fetchone=True)
    if existing:
        execute("UPDATE menstrual_cycles SET notes=? WHERE id=? AND user_id=?",
                (str(notes or '')[:300], existing['id'], uid), commit=True)
    else:
        execute("""INSERT INTO menstrual_cycles (id, start_date, end_date, notes, created_at, user_id)
                   VALUES (?,?,NULL,?,?,?)""",
                (new_id(), start_date, str(notes or '')[:300], now_iso(), uid), commit=True)
    return get_cycle_summary()


def log_period_end(end_date: str) -> dict:
    """Close the most recent period with an end date (must be >= its start)."""
    if not _valid_date(end_date):
        raise ValueError('A valid end date is required')
    uid = current_user_id()
    latest = execute("""SELECT id, start_date FROM menstrual_cycles
                        WHERE user_id=? ORDER BY start_date DESC LIMIT 1""", (uid,), fetchone=True)
    if not latest:
        raise ValueError('Log a period start first')
    if end_date < latest['start_date']:
        raise ValueError('End date cannot be before the start date')
    execute("UPDATE menstrual_cycles SET end_date=? WHERE id=? AND user_id=?",
            (end_date, latest['id'], uid), commit=True)
    return get_cycle_summary()


def delete_cycle(cid: str) -> dict:
    execute("DELETE FROM menstrual_cycles WHERE id=? AND user_id=?", (cid, current_user_id()), commit=True)
    return get_cycle_summary()


def _avg(nums):
    return round(sum(nums) / len(nums)) if nums else None


def get_cycle_summary() -> dict:
    """Derived view of the user's cycle history — never stores what it computes.

    Returns cycle/period-length averages, the current cycle day (or period day
    when a period is ongoing), and — only with >=2 cycles — an estimated next
    start and days until it. All estimates are from the user's own last few
    cycles; with too little data those fields are None.
    """
    rows = _rows()          # newest first
    history = [{'id': r['id'], 'start_date': r['start_date'], 'end_date': r['end_date'],
                'length': ((_dt.date.fromisoformat(r['end_date']) - _dt.date.fromisoformat(r['start_date'])).days + 1)
                          if r['end_date'] else None} for r in rows]

    if not rows:
        return {'has_data': False, 'history': [], 'cycle_length': None, 'period_length': None,
                'predicted_next_start': None, 'days_until_next': None, 'current_day': None,
                'ongoing': False, 'ongoing_day': None}

    starts = [_dt.date.fromisoformat(r['start_date']) for r in rows]   # newest first
    # Cycle lengths = gaps between consecutive starts (older→newer).
    gaps = [(starts[i] - starts[i + 1]).days for i in range(len(starts) - 1)]
    cycle_length = _avg(gaps[:_RECENT]) if gaps else None
    period_lengths = [h['length'] for h in history if h['length']]
    period_length = _avg(period_lengths[:_RECENT])

    today = _dt.date.fromisoformat(_today())
    last_start = starts[0]
    current_day = (today - last_start).days + 1 if today >= last_start else None

    # Ongoing = the newest period has no end date yet, and today isn't before it.
    ongoing = rows[0]['end_date'] is None and today >= last_start
    ongoing_day = current_day if ongoing else None

    predicted_next_start = days_until_next = None
    if cycle_length and len(starts) >= 2:
        nxt = last_start + _dt.timedelta(days=cycle_length)
        predicted_next_start = nxt.isoformat()
        days_until_next = (nxt - today).days

    return {'has_data': True, 'history': history[:12],
            'cycle_length': cycle_length, 'period_length': period_length,
            'predicted_next_start': predicted_next_start, 'days_until_next': days_until_next,
            'current_day': current_day, 'ongoing': ongoing, 'ongoing_day': ongoing_day}
