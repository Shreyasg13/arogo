"""
db/menopause.py — O3 menopause / perimenopause companion.

A dated symptom log for the menopause transition — hot flashes, night sweats,
sleep disruption and mood — each rated 0–3 (none / mild / moderate / severe),
plus a note. Descriptive only: Arogo shows what the user logged and a simple
frequency summary; it never stages, diagnoses, or advises.
"""
import datetime as _dt

from .core import execute, current_user_id, new_id, now_iso, valid_date, user_today, to_int

SYMPTOMS = ('hot_flashes', 'night_sweats', 'sleep', 'mood')


def _sev(v):
    return to_int(v, 0, lo=0, hi=3)


def add_log(data: dict) -> dict:
    date_key = str(data.get('date_key') or '').strip()
    if not valid_date(date_key):
        date_key = user_today()
    lid = new_id()
    execute("""INSERT INTO menopause_logs
               (id, date_key, hot_flashes, night_sweats, sleep, mood, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (lid, date_key, _sev(data.get('hot_flashes')), _sev(data.get('night_sweats')),
             _sev(data.get('sleep')), _sev(data.get('mood')),
             str(data.get('notes') or '').strip()[:300], now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM menopause_logs WHERE id=?", (lid,), fetchone=True))


def list_logs(days: int = 90) -> list:
    days = max(1, min(int(days or 90), 3650))
    try:
        anchor = _dt.date.fromisoformat(user_today())   # the user's day, matching stored date_keys
    except ValueError:
        anchor = _dt.date.today()
    start = (anchor - _dt.timedelta(days=days)).isoformat()
    rows = execute("""SELECT * FROM menopause_logs WHERE user_id=? AND date_key>=?
                      ORDER BY date_key DESC, created_at DESC""",
                   (current_user_id(), start), fetchall=True)
    return [dict(r) for r in (rows or [])]


def get_summary(days: int = 30) -> dict:
    """How many days in the window had each symptom at moderate-or-worse (>=2),
    and the average severity when present. Purely descriptive; None-safe when
    there's no data (no fabricated zeros presented as a finding)."""
    logs = list_logs(days)
    out = {}
    for s in SYMPTOMS:
        vals = [l[s] for l in logs if isinstance(l.get(s), int)]
        present = [v for v in vals if v >= 1]
        flare_days = sum(1 for v in vals if v >= 2)
        out[s] = {
            'logged': len(vals),
            'flare_days': flare_days,
            'avg_when_present': round(sum(present) / len(present), 1) if present else None,
        }
    return {'days': days, 'log_count': len(logs), 'has_data': bool(logs), 'symptoms': out}


def delete_log(lid: str) -> bool:
    execute("DELETE FROM menopause_logs WHERE id=? AND user_id=?",
            (lid, current_user_id()), commit=True)
    return True
