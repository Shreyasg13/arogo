"""Falls — recorded, counted, and never scored.

The app already builds for elder care. There is a care circle, dependents, a
large-type mode, an emergency card. There was nowhere to write down a fall,
which is the single event that matters most in that setting and the one most
reliably lost: each fall feels minor at the time, nobody writes it down, and
six months later "have you had any falls?" gets answered with "no, not really".

What this module does is keep the list. What it deliberately does not do:

  No risk score. Fall-risk assessment is a clinical instrument — Morse,
  STRATIFY, the Timed Up and Go — administered by someone trained, with
  published validation behind it. A number this app invented would look exactly
  like one of those and mean nothing. There is no score here and there will not
  be one.

  No severity grade. "Minor" and "serious" are judgements about an injury, and
  the person reading this page is not the one qualified to make them. What is
  recorded is what happened: was there an injury, did anyone look at it.

  No cause. A pattern in the data — three falls in the bathroom — is worth
  showing because it is arithmetic. Saying it happened BECAUSE of the bathroom,
  or because of a medicine, is a claim requiring evidence this app does not
  have.

  No advice. Not "install a grab rail", not "review your medicines". Both may be
  excellent ideas and neither is this app's to give.

What it does offer is the thing a person actually needs: the list, in order,
with the dates, ready to hand over — because the failure mode here is not a
wrong answer, it is a blank one.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date

# Where a fall happened. Free text is allowed too; these are the ones common
# enough to be worth a single tap, and they came from what the app's other
# location fields already use rather than from an invented taxonomy.
PLACES = [
    ('home_indoors', 'At home, indoors'),
    ('bathroom', 'Bathroom'),
    ('stairs', 'Stairs'),
    ('bedroom', 'Bedroom'),
    ('kitchen', 'Kitchen'),
    ('garden', 'Garden or yard'),
    ('outdoors', 'Outside'),
    ('other', 'Somewhere else'),
]

TIMES = [
    ('morning', 'Morning'),
    ('afternoon', 'Afternoon'),
    ('evening', 'Evening'),
    ('night', 'Night'),
]

_PLACE_LABEL = dict(PLACES)
_TIME_LABEL = dict(TIMES)

# What the summary covers. A year, because that is the window a clinician asks
# about, not because the app has an opinion about what a year of falls means.
SUMMARY_DAYS = 365


def _to_int_flag(v):
    """0/1, or None when genuinely unanswered.

    `got_up_alone` is three-valued on purpose: "no" and "not recorded" are
    different, and collapsing them would turn every unanswered question into
    "they got up on their own".
    """
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ('1', 'true', 'yes', 'y'):
        return 1
    if s in ('0', 'false', 'no', 'n'):
        return 0
    return None


def add_fall(fell_on=None, time_of_day='', place='', what_happened='',
             injured=None, injury='', got_up_alone=None, saw_someone=None,
             notes='') -> dict:
    uid = current_user_id()
    fell_on = fell_on if valid_date(fell_on) else user_today()
    fid = new_id()
    execute("""INSERT INTO falls (id, user_id, fell_on, time_of_day, place,
                                  what_happened, injured, injury, got_up_alone,
                                  saw_someone, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fid, uid, fell_on, (time_of_day or '').strip(),
             (place or '').strip(), (what_happened or '').strip()[:2000],
             _to_int_flag(injured) or 0, (injury or '').strip()[:500],
             _to_int_flag(got_up_alone), _to_int_flag(saw_someone) or 0,
             (notes or '').strip()[:2000], now_iso()),
            commit=True)
    return get_fall(fid)


def get_fall(fid):
    r = execute("SELECT * FROM falls WHERE id=? AND user_id=?",
                (fid, current_user_id()), fetchone=True)
    return _shape(r) if r else None


def _shape(r) -> dict:
    d = dict(r)
    return {
        'id': d['id'],
        'fell_on': d['fell_on'],
        'time_of_day': d.get('time_of_day') or '',
        'time_label': _TIME_LABEL.get(d.get('time_of_day') or '', ''),
        'place': d.get('place') or '',
        # An unrecognised place is the user's own words, so it is shown as
        # typed rather than dropped into "Other".
        'place_label': _PLACE_LABEL.get(d.get('place') or '', d.get('place') or ''),
        'what_happened': d.get('what_happened') or '',
        'injured': bool(d.get('injured')),
        'injury': d.get('injury') or '',
        'got_up_alone': None if d.get('got_up_alone') is None else bool(d['got_up_alone']),
        'saw_someone': bool(d.get('saw_someone')),
        'notes': d.get('notes') or '',
    }


def list_falls(since: str = None, limit: int = 200) -> list:
    uid = current_user_id()
    if valid_date(since):
        rows = execute("""SELECT * FROM falls WHERE user_id=? AND fell_on >= ?
                          ORDER BY fell_on DESC, created_at DESC LIMIT ?""",
                       (uid, since, limit), fetchall=True) or []
    else:
        rows = execute("""SELECT * FROM falls WHERE user_id=?
                          ORDER BY fell_on DESC, created_at DESC LIMIT ?""",
                       (uid, limit), fetchall=True) or []
    return [_shape(r) for r in rows]


def update_fall(fid, **fields) -> dict:
    """Edit an existing entry. Only the columns this module owns are writable."""
    allowed = ('fell_on', 'time_of_day', 'place', 'what_happened', 'injured',
               'injury', 'got_up_alone', 'saw_someone', 'notes')
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == 'fell_on' and not valid_date(v):
            continue
        if k in ('injured', 'saw_someone'):
            v = _to_int_flag(v) or 0
        elif k == 'got_up_alone':
            v = _to_int_flag(v)
        else:
            v = str(v).strip()[:2000]
        sets.append(f'{k}=?')
        args.append(v)
    if not sets:
        return get_fall(fid)
    args += [fid, current_user_id()]
    execute(f"UPDATE falls SET {', '.join(sets)} WHERE id=? AND user_id=?",
            tuple(args), commit=True)
    return get_fall(fid)


def delete_fall(fid) -> bool:
    from .trash import soft_delete
    return soft_delete('falls', fid)


def summary(days: int = SUMMARY_DAYS) -> dict:
    """Counts and where they happened. Arithmetic only.

    Returns `has_any: False` rather than a page of zeroes — "0 falls" invites
    the reading "you are not falling", and the only thing the app knows is that
    nothing has been written down.
    """
    since = (dt.date.fromisoformat(user_today())
             - dt.timedelta(days=days)).isoformat()
    falls = list_falls(since=since)
    if not falls:
        return {'has_any': False, 'days': days, 'total': 0,
                'note': 'Nothing recorded in this period. That is not the same '
                        'as no falls — it means none were written down here.'}

    by_place, by_time = {}, {}
    injured = with_help = 0
    for f in falls:
        key = f['place_label'] or 'Not recorded'
        by_place[key] = by_place.get(key, 0) + 1
        tkey = f['time_label'] or 'Not recorded'
        by_time[tkey] = by_time.get(tkey, 0) + 1
        if f['injured']:
            injured += 1
        if f['got_up_alone'] is False:
            with_help += 1

    return {
        'has_any': True,
        'days': days,
        'total': len(falls),
        'injured': injured,
        'needed_help_up': with_help,
        'first': falls[-1]['fell_on'],
        'last': falls[0]['fell_on'],
        'by_place': sorted(({'label': k, 'count': v} for k, v in by_place.items()),
                           key=lambda x: (-x['count'], x['label'])),
        'by_time': sorted(({'label': k, 'count': v} for k, v in by_time.items()),
                          key=lambda x: (-x['count'], x['label'])),
        # Said on the page. A count of falls looks like a verdict on someone's
        # independence, and this app is not issuing one.
        'not_a_score': 'This is a count of what was written down, not an '
                       'assessment. Arogo does not rate fall risk — that is a '
                       'clinical assessment, and a number invented here would '
                       'look like one and mean nothing.',
    }
