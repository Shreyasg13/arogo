"""One appointment, everything worth bringing to it, on one page.

Every piece of this is already recorded somewhere in Arogo. What was missing was
the assembly — so people arrive at an appointment and answer "has anything
changed?" and "what are you taking?" from memory, badly, in the ten seconds
before the question moves on. The medicines list lives on one screen, the labs
on another, the questions they wrote down on a third, and nobody opens three
screens in a waiting room.

There is already a "visit pack" on the records page. That one is an index of
uploaded DOCUMENTS, which is a different job, and this deliberately does not
duplicate it — it points at it instead.

What this is not:

  It is not a summary of someone's health. It reports what is recorded, without
  ranking, interpreting or drawing a conclusion from any of it. A lab value is
  printed with its date and unit and nothing else; whether it is good news is a
  question for the person being handed the page.

  It is not complete, and it says so. Anything not logged in Arogo is not here,
  and a tidy one-page handout is exactly the kind of document that invites a
  reader to assume otherwise.

  It is not a diary. Mood, journal entries, cycle and menopause logs are walled
  off from caregivers elsewhere in the app for good reason, and a page designed
  to be printed and handed to someone is the last place they belong. Symptoms
  are included — those are what the appointment is usually about.

The window. Everything time-bounded here runs from the PREVIOUS appointment to
the one being prepared for, because "since we last saw you" is the actual
question. With no previous appointment it falls back to 90 days and says which
of the two it used, so the range on the page is never a mystery.
"""
from __future__ import annotations

import datetime as dt
import json

from .core import execute, current_user_id, user_today, valid_date

# How far back to look when there is no previous appointment to anchor to.
DEFAULT_WINDOW_DAYS = 90

# Labs are capped so the page stays a page. Newest first, so the cap drops the
# oldest — which is the right end to lose.
MAX_LABS = 25
MAX_SYMPTOMS = 40
MAX_VITALS_PER_TYPE = 3

NOT_CAPTURED = (
    "This page shows what is recorded in Arogo. Anything not logged here — "
    "doses taken or missed without being marked, readings taken elsewhere, "
    "visits to other clinicians — does not appear, and its absence does not "
    "mean it did not happen."
)


def _own_appointment(aid):
    return execute("SELECT * FROM appointments WHERE id=? AND user_id=?",
                   (aid, current_user_id()), fetchone=True)


def _previous_appointment(before_date, exclude_id=None):
    """The appointment before this one — the anchor for "since we last met"."""
    uid = current_user_id()
    if exclude_id:
        return execute("""SELECT id, title, date FROM appointments
                          WHERE user_id=? AND date < ? AND id<>?
                          ORDER BY date DESC LIMIT 1""",
                       (uid, before_date, exclude_id), fetchone=True)
    return execute("""SELECT id, title, date FROM appointments
                      WHERE user_id=? AND date < ? ORDER BY date DESC LIMIT 1""",
                   (uid, before_date), fetchone=True)


def _window_for(appt_date, appt_id):
    """(since, until, anchor) for one appointment.

    `until` is the appointment date or today, whichever is later: a pack printed
    for tomorrow's visit must include what was logged this morning.
    """
    today = user_today()
    until = max(str(appt_date or today), today)
    prev = _previous_appointment(appt_date, exclude_id=appt_id)
    if prev:
        return prev['date'], until, {
            'kind': 'appointment',
            'date': prev['date'],
            'title': prev['title'] or 'your last appointment',
        }
    start = (dt.date.fromisoformat(today)
             - dt.timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    return start, until, {'kind': 'default_window', 'date': start, 'title': None}


# ── The sections ────────────────────────────────────────────────────────────

def _medicines():
    """What the person is taking now, as recorded. Doses are printed exactly as
    entered — this page must never restate a dose in a form the prescriber did
    not write."""
    rows = execute("""SELECT name, dosage, unit, frequency, times, purpose,
                             with_food, notes, start_date
                      FROM medicines WHERE user_id=? AND active=1
                      ORDER BY name""", (current_user_id(),), fetchall=True) or []
    out = []
    for r in rows:
        try:
            times = json.loads(r['times'] or '[]')
        except (ValueError, TypeError):
            times = []
        # A unit with no number in front of it is not a dose. "Paracetamol mg"
        # on a page a clinician reads looks like a transcription error, and the
        # honest rendering of "no dose recorded" is to print nothing at all.
        dosage = (r['dosage'] or '').strip()
        unit = (r['unit'] or '').strip()
        out.append({
            'name': r['name'],
            'dose': f'{dosage} {unit}'.strip() if dosage else '',
            'frequency': (r['frequency'] or '').replace('_', ' '),
            'times': [str(x) for x in times if x],
            'purpose': (r['purpose'] or '').strip(),
            'with_food': bool(r['with_food']),
            'started': (r['start_date'] or '').strip(),
        })
    return out


def _changes(since, until):
    """Delegated to the reconciliation module rather than re-derived, so the two
    surfaces can never disagree about what changed."""
    from .reconciliation import changes_between
    got = changes_between(since, until)
    return {'changes': got['changes'], 'counts': got['counts'],
            'not_captured': got['not_captured']}


def _labs(since, until):
    rows = execute("""SELECT name, value, unit, date_key, notes
                      FROM lab_results
                      WHERE user_id=? AND date_key >= ? AND date_key <= ?
                      ORDER BY date_key DESC, name""",
                   (current_user_id(), since, until), fetchall=True) or []
    labs = [{'name': r['name'], 'value': r['value'], 'unit': r['unit'] or '',
             'date': r['date_key'], 'note': (r['notes'] or '').strip()}
            for r in rows]
    return {'items': labs[:MAX_LABS], 'total': len(labs),
            'truncated': len(labs) > MAX_LABS}


def _symptoms(since, until):
    """Grouped by name, because "headache, 6 times, worst 8/10" is the useful
    shape and a list of 40 individual rows is not. The count and the range are
    facts; no average is reported, because averaging a severity scale someone
    self-assigned reads as a measurement and isn't one."""
    rows = execute("""SELECT name, severity, date_key, notes FROM symptoms
                      WHERE user_id=? AND date_key >= ? AND date_key <= ?
                      ORDER BY date_key DESC""",
                   (current_user_id(), since, until), fetchall=True) or []
    groups = {}
    for r in rows:
        g = groups.setdefault(r['name'], {
            'name': r['name'], 'count': 0, 'first': r['date_key'],
            'last': r['date_key'], 'worst': None, 'notes': []})
        g['count'] += 1
        g['first'] = min(g['first'], r['date_key'])
        g['last'] = max(g['last'], r['date_key'])
        sev = r['severity']
        if sev is not None:
            g['worst'] = sev if g['worst'] is None else max(g['worst'], sev)
        note = (r['notes'] or '').strip()
        if note and len(g['notes']) < 3:
            g['notes'].append(note)
    items = sorted(groups.values(), key=lambda g: (-g['count'], g['name']))
    return {'items': items[:MAX_SYMPTOMS], 'total': len(items),
            'truncated': len(items) > MAX_SYMPTOMS}


def _vitals(since, until):
    """The most recent few of each kind, in the units they were stored in.

    Values are NOT converted here. The app stores canonically and converts at
    the display layer, and a printed page that silently reinterpreted a number
    would be the worst possible place to get that wrong — so the unit travels
    with the value and the conversion happens where every other reading in the
    app is converted.
    """
    rows = execute("""SELECT type, value1, value2, unit, date_key FROM vitals
                      WHERE user_id=? AND date_key >= ? AND date_key <= ?
                      ORDER BY date_key DESC""",
                   (current_user_id(), since, until), fetchall=True) or []
    by_type = {}
    for r in rows:
        lst = by_type.setdefault(r['type'], [])
        if len(lst) < MAX_VITALS_PER_TYPE:
            lst.append({'value1': r['value1'], 'value2': r['value2'],
                        'unit': r['unit'] or '', 'date': r['date_key']})
    return [{'type': k, 'readings': v} for k, v in sorted(by_type.items())]


def _allergies():
    """Always included, never windowed, and never abbreviated. This is the one
    section on the page where an omission is dangerous rather than untidy."""
    rows = execute("""SELECT allergen, reaction, severity FROM allergies
                      WHERE user_id=? ORDER BY allergen""",
                   (current_user_id(),), fetchall=True) or []
    return [{'allergen': r['allergen'], 'reaction': (r['reaction'] or '').strip(),
             'severity': r['severity'] or ''} for r in rows]


def _questions(aid):
    """Questions pinned to this appointment, plus unpinned ones still unasked —
    someone who wrote a question down without attaching it to a visit still
    meant to ask it."""
    uid = current_user_id()
    pinned = execute("""SELECT id, question FROM doctor_questions
                        WHERE user_id=? AND appointment_id=? AND asked=0
                        ORDER BY created_at""", (uid, aid), fetchall=True) or []
    loose = execute("""SELECT id, question FROM doctor_questions
                       WHERE user_id=? AND asked=0
                         AND (appointment_id IS NULL OR appointment_id='')
                       ORDER BY created_at""", (uid,), fetchall=True) or []
    return {'for_this_visit': [{'id': r['id'], 'question': r['question']} for r in pinned],
            'unassigned': [{'id': r['id'], 'question': r['question']} for r in loose]}


def _conditions():
    """Free text, from the same place the health ID and the binder read it.

    There is no table of diagnoses in Arogo — conditions are whatever the user
    typed on their health ID. Reading that field rather than inventing a
    structured list keeps the three printable surfaces from ever disagreeing
    about what someone has been told they have.
    """
    try:
        from .health_id import get_health_id
        return (get_health_id() or {}).get('conditions', '') or ''
    except Exception:
        return ''


# ── The pack ────────────────────────────────────────────────────────────────

def build_pack(aid) -> dict:
    """Everything for one appointment, or None if it isn't the caller's."""
    row = _own_appointment(aid)
    if not row:
        return None
    appt = dict(row)
    since, until, anchor = _window_for(appt.get('date'), appt['id'])

    provider = None
    if appt.get('provider_id'):
        p = execute("""SELECT name, specialty, clinic FROM providers
                       WHERE id=? AND user_id=?""",
                    (appt['provider_id'], current_user_id()), fetchone=True)
        provider = dict(p) if p else None

    return {
        'appointment': {
            'id': appt['id'],
            'title': appt['title'],
            'kind': appt.get('kind') or 'doctor',
            'date': appt['date'],
            'time': appt.get('time') or '',
            'location': appt.get('location') or '',
        },
        'provider': provider,
        'window': {'since': since, 'until': until, 'anchor': anchor,
                   'window_days': DEFAULT_WINDOW_DAYS},
        'medicines': _medicines(),
        'changes': _changes(since, until),
        'allergies': _allergies(),
        'conditions': _conditions(),
        'labs': _labs(since, until),
        'symptoms': _symptoms(since, until),
        'vitals': _vitals(since, until),
        'questions': _questions(appt['id']),
        'not_captured': NOT_CAPTURED,
    }


def next_appointment():
    """The soonest upcoming appointment, or the most recent past one when there
    is nothing upcoming — someone opening this the day after a visit is usually
    still working on that visit."""
    uid, today = current_user_id(), user_today()
    row = execute("""SELECT id FROM appointments WHERE user_id=? AND date >= ?
                     ORDER BY date, time LIMIT 1""", (uid, today), fetchone=True)
    if not row:
        row = execute("""SELECT id FROM appointments WHERE user_id=?
                         ORDER BY date DESC LIMIT 1""", (uid,), fetchone=True)
    return row['id'] if row else None


def pack_for_dates(since: str = None, until: str = None) -> dict:
    """The same content for an explicit date range and no appointment.

    Not everyone books through Arogo, and a walk-in still deserves the page.
    """
    # valid_date is a predicate, not a coercer — `valid_date(x) or today` would
    # quietly put the boolean True on the page as a date.
    today = user_today()
    if not valid_date(until):
        until = today
    if not valid_date(since):
        since = (dt.date.fromisoformat(today)
                 - dt.timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    # A backwards range would silently return nothing at all, which reads as
    # "nothing happened" rather than "you asked for an impossible window".
    if since > until:
        since, until = until, since
    return {
        'appointment': None,
        'provider': None,
        'window': {'since': since, 'until': until,
                   'anchor': {'kind': 'chosen_dates', 'date': since, 'title': None},
                   'window_days': DEFAULT_WINDOW_DAYS},
        'medicines': _medicines(),
        'changes': _changes(since, until),
        'allergies': _allergies(),
        'conditions': _conditions(),
        'labs': _labs(since, until),
        'symptoms': _symptoms(since, until),
        'vitals': _vitals(since, until),
        'questions': {'for_this_visit': [], 'unassigned': _questions('')['unassigned']},
        'not_captured': NOT_CAPTURED,
    }
