"""
db/dental_vision.py — Dental & vision care, two commonly-neglected areas the
rest of the app doesn't touch.

Two honest, purely-factual record types, both scoped to the authenticated user:

  1. Checkups (dental cleanings, eye exams): a dated log with an optional
     "next due" date the user copies from their dentist/optometrist. get_due()
     echoes that date back with a days-until countdown — it never schedules or
     recommends anything, it only reminds you of a date you entered.

  2. Vision prescription: the optical values from the user's own glasses/
     contacts Rx (sphere / cylinder / axis / add, per eye, plus PD). Stored as
     TEXT exactly as written on the card ("-2.25", "PL", "+1.00", axis "180") —
     never coerced to a number or interpreted. Arogo is a place to keep the Rx,
     not to read vision from it.
"""
import datetime as _dt

from .core import execute, current_user_id, new_id, now_iso, valid_date, user_today

VISIT_KINDS = ('dental', 'eye')
RX_KINDS = ('glasses', 'contacts')

# Optical fields kept verbatim as text; a generous cap guards the column without
# reshaping the value the user copied.
_RX_FIELDS = ('right_sph', 'right_cyl', 'right_axis', 'right_add',
              'left_sph', 'left_cyl', 'left_axis', 'left_add', 'pd')


def _clean(v, limit=120):
    return str(v or '').strip()[:limit]


# ── Checkups ────────────────────────────────────────────────────────────────

def add_visit(data: dict) -> dict:
    kind = str(data.get('kind', '')).strip().lower()
    if kind not in VISIT_KINDS:
        raise ValueError('kind must be dental or eye')
    # `or ''` (not a get-default) so an explicit JSON null coerces to empty
    # rather than the string "None" — the frontend sends next_due: null when
    # the optional field is blank.
    visit_date = str(data.get('visit_date') or '').strip()
    if not valid_date(visit_date):
        raise ValueError('A valid visit date is required')
    next_due = str(data.get('next_due') or '').strip()
    if next_due and not valid_date(next_due):
        raise ValueError('Next-due date is not a valid date')
    vid = new_id()
    execute("""INSERT INTO dental_vision_visits
               (id, kind, visit_date, provider, summary, next_due, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (vid, kind, visit_date, _clean(data.get('provider')), _clean(data.get('summary'), 500),
             next_due or None, now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM dental_vision_visits WHERE id=?", (vid,), fetchone=True))


def list_visits(kind: str = None) -> list:
    uid = current_user_id()
    if kind in VISIT_KINDS:
        rows = execute("""SELECT * FROM dental_vision_visits WHERE user_id=? AND kind=?
                          ORDER BY visit_date DESC, created_at DESC""", (uid, kind), fetchall=True)
    else:
        rows = execute("""SELECT * FROM dental_vision_visits WHERE user_id=?
                          ORDER BY visit_date DESC, created_at DESC""", (uid,), fetchall=True)
    return [dict(r) for r in (rows or [])]


def delete_visit(vid: str) -> bool:
    from .trash import soft_delete
    return soft_delete('dental_vision_visits', vid)
    return True


def get_due(within_days: int = 90) -> list:
    """The next checkup date the user recorded for each kind (the next_due on
    their most recent visit of that kind), with a days-until countdown and an
    overdue / due-soon flag. Only echoes a date the user entered — Arogo never
    schedules or invents a due date."""
    uid = current_user_id()
    within_days = max(1, min(int(within_days or 90), 3650))
    try:
        today = _dt.date.fromisoformat(user_today())
    except ValueError:
        today = _dt.date.today()
    out = []
    for kind in VISIT_KINDS:
        row = execute("""SELECT next_due FROM dental_vision_visits
                         WHERE user_id=? AND kind=? AND next_due IS NOT NULL AND next_due!=''
                         ORDER BY visit_date DESC, created_at DESC LIMIT 1""",
                      (uid, kind), fetchone=True)
        if not row:
            continue
        try:
            due = _dt.date.fromisoformat(row['next_due'])
        except (ValueError, TypeError):
            continue
        days = (due - today).days
        out.append({'kind': kind, 'next_due': row['next_due'], 'days_until': days,
                    'overdue': days < 0, 'due_soon': 0 <= days <= within_days})
    return out


# ── Vision prescription ─────────────────────────────────────────────────────

def add_rx(data: dict) -> dict:
    kind = str(data.get('kind', 'glasses')).strip().lower()
    if kind not in RX_KINDS:
        kind = 'glasses'
    rx_date = str(data.get('rx_date') or '').strip()
    if not valid_date(rx_date):
        raise ValueError('A valid prescription date is required')
    rid = new_id()
    vals = {f: _clean(data.get(f), 40) for f in _RX_FIELDS}
    execute(f"""INSERT INTO vision_prescriptions
                (id, rx_date, kind, {', '.join(_RX_FIELDS)}, notes, created_at, user_id)
                VALUES (?,?,?,{','.join('?' for _ in _RX_FIELDS)},?,?,?)""",
            (rid, rx_date, kind, *[vals[f] for f in _RX_FIELDS],
             _clean(data.get('notes'), 500), now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM vision_prescriptions WHERE id=?", (rid,), fetchone=True))


def list_rx() -> list:
    rows = execute("""SELECT * FROM vision_prescriptions WHERE user_id=?
                      ORDER BY rx_date DESC, created_at DESC""",
                   (current_user_id(),), fetchall=True)
    return [dict(r) for r in (rows or [])]


def latest_rx():
    rows = list_rx()
    return rows[0] if rows else None


def delete_rx(rid: str) -> bool:
    from .trash import soft_delete
    return soft_delete('vision_prescriptions', rid)
