"""Short courses, and medicines that have gone out of date.

Both read what is already stored on a medicine. Neither invents a schema, and
neither gives advice.

A COURSE is a medicine with an end date — a week of antibiotics, a steroid taper,
eye drops for ten days. The app knew the end date and did nothing with it, so
there was no answer to "how far through am I" and no distinction between a course
that finished and one that was abandoned on day three.

What this reports is arithmetic: doses scheduled between the start and end dates,
doses logged, days remaining. It does not tell anyone to keep taking a medicine.
"Finish the course" is a clinical instruction, it is not always the right one,
and it is not this app's to give — so where a course was stopped early the app
says only that it was, which is the fact a doctor would want.

An EXPIRED medicine is likewise a date comparison. Disposal rules are local and
this app does not know them, so it says the one thing that is true nearly
everywhere — a pharmacy will usually take them back — and does not invent a
regulation for a country it has only a currency for.
"""
import datetime as dt

from .core import execute, current_user_id, user_today

# Beyond this, "course" stops meaning anything useful — a year-long prescription
# is ongoing treatment, and showing it as 12% complete would be noise.
MAX_COURSE_DAYS = 180

# Expiring soon, in days. Long enough to reorder before it matters.
EXPIRING_SOON_DAYS = 60


def _doses_per_day(med) -> int:
    times = med.get('times') or []
    return len(times) if times else 0


def _course_window(med):
    """(start, end) if this medicine reads as a course, else None."""
    start = (med.get('start_date') or '').strip()
    end = (med.get('end_date') or '').strip()
    if not start or not end or end < start:
        return None
    try:
        days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
    except ValueError:
        return None
    if days < 1 or days > MAX_COURSE_DAYS:
        return None
    if med.get('frequency') == 'as_needed':
        return None                 # nothing is scheduled, so nothing to be through
    return start, end


def list_courses(include_finished: bool = True) -> list:
    """Every medicine with a course window, with honest progress."""
    from .medicines import list_medicines
    uid = current_user_id()
    today = user_today()
    out = []
    for med in list_medicines():
        window = _course_window(med)
        if not window:
            continue
        start, end = window
        per_day = _doses_per_day(med)
        try:
            total_days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
            days_elapsed = min(
                total_days,
                max(0, (dt.date.fromisoformat(min(today, end))
                        - dt.date.fromisoformat(start)).days + 1))
            days_left = max(0, (dt.date.fromisoformat(end)
                                - dt.date.fromisoformat(today)).days)
        except ValueError:
            continue

        taken = execute("""SELECT COUNT(*) AS n FROM dose_logs
                           WHERE user_id=? AND medicine_id=? AND taken=1
                             AND date_key BETWEEN ? AND ?""",
                        (uid, med['id'], start, end), fetchone=True)
        taken_n = (taken or {}).get('n', 0)
        scheduled_total = per_day * total_days if per_day else None
        scheduled_so_far = per_day * days_elapsed if per_day else None

        finished = today > end
        if finished and not include_finished:
            continue
        out.append({
            'id': med['id'],
            'name': med.get('name'),
            'dosage': med.get('dosage'),
            'start_date': start,
            'end_date': end,
            'total_days': total_days,
            'days_left': days_left,
            'doses_per_day': per_day or None,
            'doses_taken': taken_n,
            'doses_scheduled': scheduled_total,
            # How many *should* have been taken by now, which is the number that
            # makes "8 of 10" mean something on day five of seven.
            'doses_due_so_far': scheduled_so_far,
            'finished': finished,
            'active': bool(med.get('active')),
            # Stated as a fact, never as an instruction. Whether an unfinished
            # course matters is a question for whoever prescribed it.
            'stopped_early': bool(finished and scheduled_total
                                  and taken_n < scheduled_total),
        })
    out.sort(key=lambda c: (c['finished'], c['end_date']))
    return out


def active_course_count() -> int:
    return len([c for c in list_courses(include_finished=False) if c['active']])


def disposal_guidance(country: str = None) -> dict:
    """What to do with a medicine that has expired.

    Deliberately thin. Disposal rules are local and legally specific — some
    places run take-back schemes, some name particular drugs that must be
    flushed, some forbid exactly that — and this app knows a country only well
    enough to pick a currency symbol. Inventing a rule for somewhere it has
    never checked would be worse than saying less.

    So it offers the handful of steps that are true nearly everywhere, and points
    at the one authority that always knows: the pharmacy that dispensed it.
    """
    return {
        'ask_first': 'Your pharmacy can almost always take expired medicines '
                     'back, and will know the rules where you live.',
        'steps': [
            'Keep it in its original box until you hand it over — the label is '
            'what identifies it.',
            'Do not tip tablets down the sink or toilet unless a pharmacist or '
            'the leaflet specifically tells you to.',
            'Scratch out your name and address before throwing away any packet.',
            'Sharps and needles need a proper container — ask your pharmacy or '
            'clinic rather than using household bins.',
        ],
        # Said out loud rather than implied: the app is not the authority here.
        'not_advice': 'Arogo does not know the disposal rules where you live and '
                      'does not guess at them.',
        'country': country,
    }
