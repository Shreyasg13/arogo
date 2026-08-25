"""A bout of illness, with a beginning and an end.

"When did this start?" is the first question in every consultation, and the app
had no way to answer it. Symptoms were a flat stream: a fever on Tuesday and a
cough on Thursday were unrelated rows, so the shape of an illness — how long it
ran, when it peaked, what was taken for it — had to be reconstructed from memory
in the waiting room.

An episode is a window with a name. Nothing is copied into it: symptoms,
temperatures and doses stay where they are, and the summary reads them back by
date. Deleting an episode therefore loses the grouping and none of the data.

The summary reports only what was recorded. It does not name an illness, suggest
a cause, or say whether someone is getting better — a gap in the log means
nothing was written down, which is not the same as nothing happening, and the
distinction is why "days logged" is reported next to "days long".
"""
import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date

MAX_EPISODE_DAYS = 365


def _clean(data):
    name = str((data or {}).get('name') or '').strip()[:80]
    if not name:
        raise ValueError('Give this episode a name — "flu", "chest infection".')
    started = str((data or {}).get('started_on') or '').strip() or user_today()
    if not valid_date(started):
        raise ValueError('Enter a valid start date.')
    ended = str((data or {}).get('ended_on') or '').strip() or None
    if ended and not valid_date(ended):
        raise ValueError('Enter a valid end date.')
    if ended and ended < started:
        raise ValueError('The episode ends before it starts.')
    return name, started, ended, str((data or {}).get('notes') or '').strip()[:2000]


def create_episode(data: dict) -> dict:
    name, started, ended, notes = _clean(data)
    eid = new_id()
    execute("""INSERT INTO illness_episodes
                 (id, name, started_on, ended_on, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (eid, name, started, ended, notes, now_iso(), current_user_id()),
            commit=True)
    return get_episode(eid)


def update_episode(eid: str, data: dict) -> dict:
    if not get_episode(eid):
        return None
    name, started, ended, notes = _clean(data)
    execute("""UPDATE illness_episodes SET name=?, started_on=?, ended_on=?, notes=?
               WHERE id=? AND user_id=?""",
            (name, started, ended, notes, eid, current_user_id()), commit=True)
    return get_episode(eid)


def end_episode(eid: str, on: str = None) -> dict:
    ep = get_episode(eid)
    if not ep:
        return None
    on = on if (on and valid_date(on)) else user_today()
    if on < ep['started_on']:
        on = ep['started_on']
    execute("UPDATE illness_episodes SET ended_on=? WHERE id=? AND user_id=?",
            (on, eid, current_user_id()), commit=True)
    return get_episode(eid)


def get_episode(eid):
    r = execute("SELECT * FROM illness_episodes WHERE id=? AND user_id=?",
                (eid, current_user_id()), fetchone=True)
    return dict(r) if r else None


def delete_episode(eid) -> bool:
    """Only the grouping goes. Every symptom and reading it covered stays
    exactly where it is."""
    execute("DELETE FROM illness_episodes WHERE id=? AND user_id=?",
            (eid, current_user_id()), commit=True)
    return True


def list_episodes() -> list:
    rows = execute("""SELECT * FROM illness_episodes WHERE user_id=?
                      ORDER BY started_on DESC""",
                   (current_user_id(),), fetchall=True) or []
    today = user_today()
    out = []
    for r in rows:
        d = dict(r)
        end = d['ended_on'] or today
        try:
            d['days'] = (dt.date.fromisoformat(end)
                         - dt.date.fromisoformat(d['started_on'])).days + 1
        except Exception:
            d['days'] = None
        d['ongoing'] = not d['ended_on']
        out.append(d)
    return out


def episode_summary(eid: str) -> dict:
    """What was recorded during the window — read back, never copied in."""
    ep = get_episode(eid)
    if not ep:
        return None
    uid = current_user_id()
    start = ep['started_on']
    end = ep['ended_on'] or user_today()

    symptoms = execute("""SELECT name, severity, date_key FROM symptoms
                          WHERE user_id=? AND date_key BETWEEN ? AND ?
                          ORDER BY date_key""",
                       (uid, start, end), fetchall=True) or []
    # Highest severity per symptom name, plus when it was first and last seen —
    # the three things someone actually gets asked.
    by_name = {}
    for s in symptoms:
        n = (s['name'] or '').strip() or 'Symptom'
        e = by_name.setdefault(n, {'name': n, 'worst': None, 'first': s['date_key'],
                                   'last': s['date_key'], 'times': 0})
        e['times'] += 1
        e['last'] = s['date_key']
        if s['severity'] is not None:
            e['worst'] = max(e['worst'] or 0, s['severity'])

    temps = execute("""SELECT value1, date_key FROM vitals
                       WHERE user_id=? AND type='temperature'
                         AND date_key BETWEEN ? AND ? AND value1 IS NOT NULL
                       ORDER BY value1 DESC LIMIT 1""",
                    (uid, start, end), fetchall=True) or []

    meds = execute("""SELECT DISTINCT m.name AS name FROM dose_logs d
                      JOIN medicines m ON m.id = d.medicine_id
                      WHERE d.user_id=? AND d.taken=1 AND d.date_key BETWEEN ? AND ?
                      ORDER BY m.name""",
                   (uid, start, end), fetchall=True) or []

    logged_days = execute("""SELECT COUNT(DISTINCT date_key) AS n FROM symptoms
                             WHERE user_id=? AND date_key BETWEEN ? AND ?""",
                          (uid, start, end), fetchone=True)
    try:
        days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1
    except Exception:
        days = None

    return {
        'episode': ep,
        'days': days,
        # Reported alongside `days` on purpose: a quiet day means nothing was
        # written down, which is not the same as nothing happening.
        'days_logged': (logged_days or {}).get('n', 0),
        'ongoing': not ep['ended_on'],
        'symptoms': sorted(by_name.values(), key=lambda e: (-(e['worst'] or 0), e['name'])),
        # Stored canonically in °C; the page converts to the user's unit.
        'peak_temperature_c': temps[0]['value1'] if temps else None,
        'medicines_taken': [m['name'] for m in meds],
    }
