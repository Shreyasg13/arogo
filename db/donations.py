"""Blood donations, and when you can next give.

The interval between donations is a published rule, not a clinical judgement,
and it is the one thing people actually forget. It is also the one thing here
that varies by country — so the intervals are stated as what they are (the
common minimum in most services), the source of the number is named on screen,
and the app says to check with the centre rather than pretending to know the
local rule.

Eligibility is more than an interval: illness, medication, travel and iron
levels all affect it, and none of that is knowable from this data. So the app
reports a DATE, never a verdict — "you could be eligible from the 4th", not
"you can donate".
"""
import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date

# Common minimum intervals, in days. These are the widely-published figures used
# by most blood services; individual services differ, which is why the UI names
# the number as a typical minimum and points at the donation centre.
KINDS = {
    'whole':    {'label': 'Whole blood', 'days': 90},
    'plasma':   {'label': 'Plasma',      'days': 14},
    'platelets': {'label': 'Platelets',  'days': 14},
    'power_red': {'label': 'Double red cells', 'days': 112},
}


def _clean(data):
    kind = str((data or {}).get('kind') or 'whole').strip().lower()
    if kind not in KINDS:
        kind = 'whole'
    day = str((data or {}).get('donated_on') or '').strip() or user_today()
    if not valid_date(day):
        raise ValueError('Enter a valid date.')
    if day > user_today():
        raise ValueError('That date is in the future.')
    return (kind, day,
            str((data or {}).get('place') or '').strip()[:120],
            str((data or {}).get('notes') or '').strip()[:500])


def add_donation(data: dict) -> dict:
    kind, day, place, notes = _clean(data)
    did = new_id()
    execute("""INSERT INTO blood_donations
                 (id, kind, donated_on, place, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (did, kind, day, place, notes, now_iso(), current_user_id()), commit=True)
    return get_donation(did)


def get_donation(did):
    r = execute("SELECT * FROM blood_donations WHERE id=? AND user_id=?",
                (did, current_user_id()), fetchone=True)
    return dict(r) if r else None


def delete_donation(did) -> bool:
    from .trash import soft_delete
    return soft_delete('blood_donations', did)


def list_donations() -> list:
    rows = execute("""SELECT * FROM blood_donations WHERE user_id=?
                      ORDER BY donated_on DESC""",
                   (current_user_id(),), fetchall=True) or []
    out = []
    for r in rows:
        d = dict(r)
        d['kind_label'] = KINDS.get(d['kind'], {}).get('label', d['kind'])
        out.append(d)
    return out


def next_eligible() -> dict:
    """The earliest date each kind's interval is satisfied.

    A date, never a verdict. Illness, medication, recent travel and iron levels
    all affect whether someone can actually give, and none of that is knowable
    from a donation log — so the app never says "you can donate".
    """
    donations = list_donations()
    today = user_today()
    per_kind = {}
    for kind, meta in KINDS.items():
        last = next((d for d in donations if d['kind'] == kind), None)
        if not last:
            per_kind[kind] = {'kind': kind, 'label': meta['label'],
                              'interval_days': meta['days'],
                              'last_donated': None, 'eligible_from': None,
                              'days_to_go': None}
            continue
        try:
            elig = (dt.date.fromisoformat(last['donated_on'])
                    + dt.timedelta(days=meta['days'])).isoformat()
            togo = (dt.date.fromisoformat(elig) - dt.date.fromisoformat(today)).days
        except ValueError:
            elig, togo = None, None
        per_kind[kind] = {'kind': kind, 'label': meta['label'],
                          'interval_days': meta['days'],
                          'last_donated': last['donated_on'],
                          'eligible_from': elig,
                          'days_to_go': max(0, togo) if togo is not None else None}
    return {
        'kinds': list(per_kind.values()),
        'total_donations': len(donations),
        # Stated on screen, not buried: the number is a typical minimum, and
        # eligibility is decided by the centre, not by this app.
        'note': 'These intervals are the usual minimum wait — your blood service '
                'may differ, and being past the date does not by itself mean you '
                'are eligible. The donation centre decides that.',
    }
