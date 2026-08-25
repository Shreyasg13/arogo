"""Trips: crossing time zones without the schedule quietly lying.

The pill-supply side of a trip lives in db/travel.py — that module answers
"how many do I need to pack"; this one answers "what time is it there".


A dose is stored as a wall-clock time — 08:00 — and the app decides what "now"
and "today" mean from the profile's time zone. Fly to another one and nothing
notices: reminders keep firing on home time, and a dose taken at breakfast in
Tokyo is filed against yesterday's date back home.

A trip makes the change explicit. While one is running, the app's clock is the
trip's clock, and the app says so on screen rather than silently retiming
anything.

The one thing this will not do is tell you how to shift your doses. Whether an
8am tablet becomes 8am local, or is nudged an hour a day, or stays exactly
twelve hours from the last one, is a medical question — and for insulin,
anticoagulants or contraceptives it is a consequential one. So the app shows both
clocks side by side and leaves the decision where it belongs.
"""
import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, valid_date

MAX_TRIP_DAYS = 400


def valid_timezone(name) -> bool:
    """A real IANA zone. Rejecting early matters: an unknown zone stored here
    would make every later 'what time is it' call fall back to the server's
    clock, which is the bug this exists to prevent."""
    name = str(name or '').strip()
    if not name:
        return False
    try:
        import zoneinfo
        zoneinfo.ZoneInfo(name)
        return True
    except Exception:
        return False


def timezone_choices() -> list:
    """Every zone this Python knows, sorted. Offered as a list rather than free
    text so a typo can't silently break the clock."""
    try:
        import zoneinfo
        return sorted(zoneinfo.available_timezones())
    except Exception:
        return []


def _clean(data):
    tz = str((data or {}).get('timezone') or '').strip()
    if not valid_timezone(tz):
        raise ValueError('Pick a time zone from the list.')
    start = str((data or {}).get('start_date') or '').strip()
    end = str((data or {}).get('end_date') or '').strip()
    if not valid_date(start) or not valid_date(end):
        raise ValueError('Enter a start and end date.')
    if end < start:
        raise ValueError('The trip ends before it starts.')
    if (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days > MAX_TRIP_DAYS:
        raise ValueError('That trip is longer than a year — change your home '
                         'time zone in your profile instead.')
    return str((data or {}).get('label') or '').strip()[:80], tz, start, end


def create_trip(data: dict) -> dict:
    label, tz, start, end = _clean(data)
    tid = new_id()
    execute("""INSERT INTO travel_trips
                 (id, label, timezone, start_date, end_date, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (tid, label, tz, start, end, now_iso(), current_user_id()), commit=True)
    return get_trip(tid)


def get_trip(tid):
    r = execute("SELECT * FROM travel_trips WHERE id=? AND user_id=?",
                (tid, current_user_id()), fetchone=True)
    return dict(r) if r else None


def list_trips() -> list:
    rows = execute("SELECT * FROM travel_trips WHERE user_id=? ORDER BY start_date DESC",
                   (current_user_id(),), fetchall=True) or []
    today = dt.date.today().isoformat()
    out = []
    for r in rows:
        d = dict(r)
        d['active'] = d['start_date'] <= today <= d['end_date']
        d['upcoming'] = d['start_date'] > today
        out.append(d)
    return out


def delete_trip(tid) -> bool:
    execute("DELETE FROM travel_trips WHERE id=? AND user_id=?",
            (tid, current_user_id()), commit=True)
    return True


def active_trip(uid=None):
    """The trip covering today, if any.

    Compared against the SERVER's date rather than the trip's own, deliberately:
    working out which trip is active from the trip's time zone would be circular,
    and a day's imprecision at each end of a journey is not worth that.
    """
    uid = uid or current_user_id()
    today = dt.date.today().isoformat()
    try:
        r = execute("""SELECT * FROM travel_trips
                       WHERE user_id=? AND start_date <= ? AND end_date >= ?
                       ORDER BY start_date DESC LIMIT 1""",
                    (uid, today, today), fetchone=True)
    except Exception:
        return None                 # table not in this schema yet
    return dict(r) if r else None


def effective_timezone(uid=None, home_tz=None):
    """The time zone the app should be using right now — the trip's, or home."""
    trip = active_trip(uid)
    return (trip['timezone'] if trip else None) or home_tz


def _now_in(tz):
    try:
        import zoneinfo
        return dt.datetime.now(zoneinfo.ZoneInfo(tz))
    except Exception:
        return dt.datetime.now()


def dose_clock(home_tz: str = None) -> dict:
    """Every scheduled dose in both clocks, so the shift is visible rather than
    inferred. Returns has_trip=False when there is nothing to compare.

    Deliberately offers no recommendation. Which of the two columns you should
    follow is a question for whoever prescribed the medicine.
    """
    trip = active_trip()
    if not trip:
        return {'has_trip': False}
    from .medicines import list_medicines
    home = home_tz or 'UTC'
    away = trip['timezone']
    now_home, now_away = _now_in(home), _now_in(away)
    # Offset between the two clocks, in whole minutes, computed from the same
    # instant so daylight saving is handled by the zone data rather than by us.
    shift_min = int(round(
        (now_away.utcoffset().total_seconds() - now_home.utcoffset().total_seconds()) / 60))

    doses = []
    for m in list_medicines():
        for t in (m.get('times') or []):
            try:
                h, mi = [int(x) for x in str(t).split(':')[:2]]
            except Exception:
                continue
            local = (dt.datetime(2000, 1, 1, h, mi) + dt.timedelta(minutes=shift_min))
            doses.append({
                'medicine': m.get('name'),
                'home_time': f'{h:02d}:{mi:02d}',
                'same_moment_local': local.strftime('%H:%M'),
                'day_shift': (local.date() - dt.date(2000, 1, 1)).days,
            })
    doses.sort(key=lambda d: d['home_time'])
    return {
        'has_trip': True,
        'label': trip['label'],
        'home_timezone': home,
        'trip_timezone': away,
        'shift_minutes': shift_min,
        'home_now': now_home.strftime('%H:%M'),
        'trip_now': now_away.strftime('%H:%M'),
        'ends_on': trip['end_date'],
        'doses': doses,
    }
