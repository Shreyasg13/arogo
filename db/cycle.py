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

from .core import execute, now_iso, new_id, current_user_id, jdump, jload

_RECENT = 6   # average the last few cycles, so a changing pattern is reflected

# Fixed vocab keeps symptom data analysable and the UI tidy. Common,
# PCOS-relevant, non-diagnostic. Extend deliberately.
SYMPTOMS = ['cramps', 'headache', 'bloating', 'acne', 'mood_swings', 'fatigue',
            'tender_breasts', 'cravings', 'back_pain', 'nausea']
FLOWS = ['spotting', 'light', 'medium', 'heavy']


def clean_symptoms(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    seen, out = set(), []
    for s in raw:
        k = str(s or '').strip().lower()
        if k in SYMPTOMS and k not in seen:
            seen.add(k)
            out.append(k)
    return out


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


# ── Symptom + flow logging (PCOS-relevant, non-diagnostic) ───────────────────

def _clean_flow(v):
    v = str(v or '').strip().lower()
    return v if v in FLOWS else None


def log_symptoms(date_key: str, symptoms=None, flow=None, notes: str = '') -> dict:
    """Record how a given day felt — symptoms + optional flow. Idempotent per
    date (re-logging the same day replaces it). Logging an empty day clears it."""
    if not _valid_date(date_key):
        raise ValueError('A valid date is required')
    uid = current_user_id()
    syms = clean_symptoms(symptoms)
    fl = _clean_flow(flow)
    note = str(notes or '').strip()[:300]   # strip so a whitespace-only note still clears the day
    existing = execute("SELECT id FROM cycle_symptoms WHERE user_id=? AND date_key=?",
                       (uid, date_key), fetchone=True)
    # Nothing to store → remove any prior row for that day, stay tidy.
    if not syms and not fl and not note:
        if existing:
            execute("DELETE FROM cycle_symptoms WHERE id=? AND user_id=?", (existing['id'], uid), commit=True)
        return get_symptom_day(date_key)
    now = now_iso()
    if existing:
        execute("""UPDATE cycle_symptoms SET symptoms=?, flow=?, notes=?, updated_at=?
                   WHERE id=? AND user_id=?""",
                (jdump(syms) if syms else None, fl, note, now, existing['id'], uid), commit=True)
    else:
        execute("""INSERT INTO cycle_symptoms (id, date_key, symptoms, flow, notes, created_at, updated_at, user_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id(), date_key, jdump(syms) if syms else None, fl, note, now, now, uid), commit=True)
    return get_symptom_day(date_key)


def get_symptom_day(date_key: str) -> dict:
    r = execute("SELECT * FROM cycle_symptoms WHERE user_id=? AND date_key=?",
                (current_user_id(), date_key), fetchone=True)
    if not r:
        return {'date_key': date_key, 'symptoms': [], 'flow': None, 'notes': ''}
    d = dict(r)
    return {'date_key': date_key, 'symptoms': jload(d['symptoms']) if d.get('symptoms') else [],
            'flow': d.get('flow'), 'notes': d.get('notes') or ''}


def get_symptom_summary(days: int = 90) -> dict:
    """Most-logged symptoms over the window — a plain frequency count, no claims."""
    start = (_dt.date.fromisoformat(_today()) - _dt.timedelta(days=days)).isoformat()
    rows = execute("""SELECT symptoms FROM cycle_symptoms
                      WHERE user_id=? AND date_key >= ?""",
                   (current_user_id(), start), fetchall=True) or []
    tally = {}
    for r in rows:
        for k in (jload(r['symptoms']) if r['symptoms'] else []):
            tally[k] = tally.get(k, 0) + 1
    top = sorted(({'key': k, 'count': c} for k, c in tally.items()),
                 key=lambda x: x['count'], reverse=True)
    return {'has_data': bool(top), 'window_days': days, 'top': top}


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

    # Regularity — the range of recent cycle lengths. Irregular cycles are the
    # hallmark of PCOS, so surfacing the spread honestly (never a diagnosis) is
    # genuinely useful: it's the thing worth raising with a doctor. Only offered
    # with >=3 cycles (2+ gaps) so a single outlier can't cry wolf.
    regularity = None
    recent_gaps = gaps[:_RECENT]
    if len(recent_gaps) >= 2:
        lo, hi = min(recent_gaps), max(recent_gaps)
        spread = hi - lo
        # Clinically, cycles are "regular" when they vary by <= ~9 days, and a
        # very long typical cycle (>35d) is itself worth noting. We only flag,
        # never conclude.
        irregular = spread > 9 or (cycle_length or 0) > 35 or lo < 21
        regularity = {'min': lo, 'max': hi, 'spread': spread,
                      'cycles_compared': len(recent_gaps) + 1, 'irregular': irregular}

    # Estimated fertile window — a planning aid, NEVER contraception. Uses the
    # standard fixed-luteal-phase model: ovulation ≈ next period − 14 days, with
    # the fertile window running 5 days before to 1 day after ovulation (sperm
    # survival + egg viability). It's only as good as the next-start estimate, so
    # it's offered on the same footing (≥2 cycles) and suppressed for very short
    # typical cycles (<21d), where the −14 model puts ovulation implausibly early.
    fertility = None
    if predicted_next_start and cycle_length and cycle_length >= 21:
        nxt_d = _dt.date.fromisoformat(predicted_next_start)
        ovulation = nxt_d - _dt.timedelta(days=14)
        fw_start = ovulation - _dt.timedelta(days=5)
        fw_end = ovulation + _dt.timedelta(days=1)
        fertility = {
            'ovulation': ovulation.isoformat(),
            'window_start': fw_start.isoformat(),
            'window_end': fw_end.isoformat(),
            'days_to_ovulation': (ovulation - today).days,
            'in_window': fw_start <= today <= fw_end,
            'ovulation_passed': today > ovulation,
            'estimate_only': True,     # planning aid, not contraception
        }

    return {'has_data': True, 'history': history[:12],
            'cycle_length': cycle_length, 'period_length': period_length,
            'predicted_next_start': predicted_next_start, 'days_until_next': days_until_next,
            'current_day': current_day, 'ongoing': ongoing, 'ongoing_day': ongoing_day,
            'regularity': regularity, 'fertility': fertility}
