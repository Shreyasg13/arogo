"""What changed between two dates.

"Has anything changed with your medicines since we last saw you?" is asked at
the start of most appointments, and it is answered from memory — usually badly,
because the changes that matter (a dose halved, something stopped by a different
doctor) are exactly the ones that blur together.

Everything needed to answer it properly is already recorded. medicine_events
carries started / stopped / resumed / edited / deleted with a timestamp, and this
reads it back as a list of changes between two dates.

Three rules, all of them about not overstepping:

  It reports changes, not consequences. "Metformin: dose changed" is a fact.
  Whether that matters is a clinical question, and the app has no view on it.

  It never guesses at a change it has no record of. A medicine edited before the
  event log existed shows up as "no change recorded", which is honest, rather
  than being quietly omitted — an absence in a reconciliation list reads as
  "nothing happened", and that is the one thing it must not imply falsely.

  It says what it cannot see. Doses taken, missed or self-adjusted without being
  logged are invisible here, and the summary says so rather than letting a tidy
  list imply completeness.
"""
import datetime as dt

from .core import execute, current_user_id, user_today, valid_date

# Event kinds, in the order a clinician would want to read them: what is new,
# what has gone, then adjustments.
_ORDER = {'started': 0, 'resumed': 1, 'stopped': 2, 'deleted': 3, 'edited': 4,
          'restocked': 5}

_LABEL = {
    'started': 'Started',
    'resumed': 'Restarted',
    'stopped': 'Stopped',
    'deleted': 'Removed from the list',
    'edited': 'Changed',
    'restocked': 'Restocked',
}

# Restocking is inventory, not a change of treatment. It stays out of a
# reconciliation list, which a doctor reads in about fifteen seconds.
_CLINICALLY_RELEVANT = {'started', 'resumed', 'stopped', 'deleted', 'edited'}


def _window(since=None, until=None):
    today = user_today()
    until = until if (until and valid_date(until)) else today
    if not (since and valid_date(since)):
        try:
            since = (dt.date.fromisoformat(until) - dt.timedelta(days=90)).isoformat()
        except ValueError:
            since = today
    if since > until:
        since, until = until, since
    return since, until


def changes_between(since: str = None, until: str = None,
                    include_inventory: bool = False) -> dict:
    """Medicine changes in a window, newest first.

    `since`/`until` are dates; events are timestamps, so the window runs from the
    start of `since` to the end of `until` — an appointment on the 3rd should
    include a change made that afternoon.
    """
    uid = current_user_id()
    since, until = _window(since, until)
    kinds = _CLINICALLY_RELEVANT | ({'restocked'} if include_inventory else set())

    rows = execute("""SELECT * FROM medicine_events
                      WHERE user_id=? AND at >= ? AND at <= ?
                      ORDER BY at DESC""",
                   (uid, since, until + 'T23:59:59.999999'), fetchall=True) or []

    changes = []
    for r in rows:
        if r['kind'] not in kinds:
            continue
        changes.append({
            'medicine_id': r['medicine_id'],
            'name': r['med_name'] or 'Medicine',
            'kind': r['kind'],
            'label': _LABEL.get(r['kind'], r['kind']),
            # The detail line is written at the time of the change (e.g.
            # "times 08:00 → 09:00"), so it is a record rather than a
            # reconstruction.
            'detail': r['detail'] or '',
            'at': r['at'],
            'date': str(r['at'] or '')[:10],
        })
    changes.sort(key=lambda c: (c['at'], _ORDER.get(c['kind'], 9)), reverse=True)

    # Medicines currently on the list that have no recorded change in the window.
    # Listed explicitly: "unchanged" is a genuine answer to the question being
    # asked, and leaving them out entirely would make the list look shorter than
    # the person's actual regimen.
    changed_ids = {c['medicine_id'] for c in changes}
    unchanged = []
    for m in execute("""SELECT id, name, dosage, unit FROM medicines
                        WHERE user_id=? AND active=1 ORDER BY name""",
                     (uid,), fetchall=True) or []:
        if m['id'] not in changed_ids:
            unchanged.append({'id': m['id'], 'name': m['name'],
                              'dosage': m['dosage'], 'unit': m['unit']})

    return {
        'since': since,
        'until': until,
        'changes': changes,
        'unchanged': unchanged,
        'counts': _counts(changes),
        # Said on the page, not buried. A tidy list invites the reader to treat
        # it as the whole picture, and it isn't.
        'not_captured': 'This lists changes recorded in Arogo. Doses taken, '
                        'missed, or adjusted without being logged here do not '
                        'appear, and neither do changes made before you started '
                        'tracking a medicine.',
    }


def _counts(changes):
    out = {k: 0 for k in _LABEL}
    for c in changes:
        out[c['kind']] = out.get(c['kind'], 0) + 1
    return {k: v for k, v in out.items() if v}


def since_last_appointment() -> dict:
    """Changes since the most recent past appointment — the default question.

    Falls back to a 90-day window when there is no past appointment to anchor
    to, and says which of the two it used so the range on screen is never a
    mystery.
    """
    uid = current_user_id()
    today = user_today()
    row = execute("""SELECT date, title FROM appointments
                     WHERE user_id=? AND date <= ? ORDER BY date DESC LIMIT 1""",
                  (uid, today), fetchone=True)
    if row:
        out = changes_between(row['date'], today)
        out['anchor'] = {'kind': 'appointment', 'date': row['date'],
                         'title': row['title'] or 'your last appointment'}
    else:
        out = changes_between(None, today)
        out['anchor'] = {'kind': 'default_window', 'date': out['since'],
                         'title': None}
    return out
