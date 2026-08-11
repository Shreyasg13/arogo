"""
db/calendar_export.py — build an iCalendar (.ics) feed of the user's own
schedule: medication dose times, upcoming appointments, and labs due for a
recheck. Everything here comes from what the user entered — no invented events.

Times are emitted as *floating* local times (no TZID / no Z): a phone calendar
shows them in whatever timezone the phone is in, which for a personal reminder
is exactly what you want and avoids shipping a full VTIMEZONE block. All-day
events (appointments without a time, recheck-due dates) use VALUE=DATE.
"""
import datetime as _dt

from .core import execute, current_user_id, user_today, valid_date
from .medicines import list_medicines
from .health import list_appointments
from .labs import get_lab_rechecks

# RFC 5545 weekday codes, Monday=0 to match Python's weekday()/schedule_days.
_BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _esc(text) -> str:
    """Escape a TEXT value per RFC 5545 (backslash, comma, semicolon, newline)."""
    s = str(text or "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return s


def _fold(line: str) -> str:
    """Fold a content line to <=75 octets with CRLF + single leading space, so
    long SUMMARY/DESCRIPTION values stay spec-compliant."""
    out = []
    raw = line.encode("utf-8")
    while len(raw) > 75:
        # Don't split a multi-byte char: back off to a UTF-8 boundary.
        cut = 75
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def _hm(t: str):
    """Parse 'HH:MM' → (h, m) or None."""
    try:
        parts = str(t).split(":")
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, IndexError):
        pass
    return None


def _stamp():
    """A single DTSTAMP for the whole file. now_iso() has microseconds; the ics
    spec wants UTC basic format, so build it plainly."""
    return _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def build_ics(days_ahead: int = 90) -> str:
    """Assemble the .ics text. days_ahead bounds recurring dose events so the
    calendar doesn't claim a schedule will hold forever (meds change)."""
    try:
        days_ahead = max(7, min(int(days_ahead), 730))
    except (TypeError, ValueError):
        days_ahead = 90

    try:
        today = _dt.date.fromisoformat(user_today())
    except ValueError:
        today = _dt.date.today()
    until = today + _dt.timedelta(days=days_ahead)
    until_str = until.strftime("%Y%m%d") + "T235959"
    stamp = _stamp()
    uid = current_user_id()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Arogo//Health Reminders//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Arogo — Health",
    ]

    def event(uid_suffix, summary, description, dtstart, all_day=False, rrule=None):
        ev = ["BEGIN:VEVENT",
              f"UID:{uid_suffix}-{uid}@arogo",
              f"DTSTAMP:{stamp}"]
        if all_day:
            ev.append(f"DTSTART;VALUE=DATE:{dtstart}")
        else:
            ev.append(f"DTSTART:{dtstart}")
        if rrule:
            ev.append(f"RRULE:{rrule}")
        ev.append(_fold("SUMMARY:" + _esc(summary)))
        if description:
            ev.append(_fold("DESCRIPTION:" + _esc(description)))
        ev.append("END:VEVENT")
        return ev

    n = 0

    # ── Medication dose times ──────────────────────────────────────────────
    for med in list_medicines():
        if not med.get("active", True):
            continue
        freq = med.get("frequency")
        times = med.get("times") or []
        if freq == "as_needed" or not times:
            continue  # PRN has no fixed clock time — nothing to put on a calendar

        # Recurrence rule shared by all of this med's daily times.
        sched_days = med.get("schedule_days")   # None or list[int] Mon=0
        interval = med.get("interval_days")     # None or int
        if interval and interval > 1:
            rrule = f"FREQ=DAILY;INTERVAL={int(interval)};UNTIL={until_str}"
        elif sched_days:
            byday = ",".join(_BYDAY[d] for d in sched_days if 0 <= d < 7)
            rrule = f"FREQ=WEEKLY;BYDAY={byday};UNTIL={until_str}" if byday else \
                    f"FREQ=DAILY;UNTIL={until_str}"
        else:
            rrule = f"FREQ=DAILY;UNTIL={until_str}"

        # Anchor the first occurrence at the med's start date if it's in range,
        # else today — a start far in the past would make some clients expand
        # the whole history.
        start = today
        sd = med.get("start_date")
        if sd and valid_date(sd):
            try:
                sd_d = _dt.date.fromisoformat(sd)
                if sd_d > today:
                    start = sd_d
            except ValueError:
                pass

        dose = (str(med.get("dosage", "")).strip() + " " + str(med.get("unit", "")).strip()).strip()
        summary_base = "💊 " + (med.get("name") or "Medicine")
        if dose:
            summary_base += f" ({dose})"
        desc = med.get("timing_text") or ""
        if med.get("with_food"):
            desc = (desc + " · take with food").strip(" ·")

        for i, t in enumerate(times):
            hm = _hm(t)
            if not hm:
                continue
            dtstart = f"{start.strftime('%Y%m%d')}T{hm[0]:02d}{hm[1]:02d}00"
            lines += event(f"med-{med['id']}-{i}", summary_base, desc, dtstart, rrule=rrule)
            n += 1

    # ── Upcoming appointments ──────────────────────────────────────────────
    for appt in list_appointments(upcoming_only=True):
        title = appt.get("title") or "Appointment"
        date = appt.get("date")
        if not date or not valid_date(date):
            continue
        loc = appt.get("location") or ""
        hm = _hm(appt.get("time") or "")
        summary = "🩺 " + title
        if hm:
            dtstart = f"{date.replace('-', '')}T{hm[0]:02d}{hm[1]:02d}00"
            lines += event(f"appt-{appt['id']}", summary, loc, dtstart)
        else:
            lines += event(f"appt-{appt['id']}", summary, loc, date.replace("-", ""), all_day=True)
        n += 1

    # ── Labs due for a recheck ─────────────────────────────────────────────
    for rc in get_lab_rechecks().get("rechecks", []):
        nd = rc.get("next_due")
        if not nd or not valid_date(nd):
            continue
        summary = "🧪 " + (rc.get("name") or rc.get("lab_key") or "Lab") + " recheck due"
        lines += event(f"labrc-{rc.get('lab_key')}", summary,
                       "Based on your last result and chosen interval.",
                       nd.replace("-", ""), all_day=True)
        n += 1

    lines.append("END:VCALENDAR")
    # RFC 5545 mandates CRLF line breaks.
    return "\r\n".join(lines) + "\r\n"
