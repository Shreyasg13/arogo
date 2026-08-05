"""
db/prescriptions.py — a prescription library.

Store the prescriptions behind the medicines: who prescribed them, when, how many
refills are left, and how long they're valid. Each prescription links to the
medicines it covers (by id, resolved to live names at read time). A renewal nudge
is derived from valid_until — never invented, and framed as a reminder to renew,
not a clinical instruction.

This is separate from the prescription-photo OCR (which only proposes medicines
and stores nothing) and from generic file uploads.
"""
import datetime as _dt

from .core import execute, now_iso, new_id, current_user_id, valid_date, jdump, jload, user_today

EXPIRING_WINDOW = 14      # days before valid_until to start nudging


def _s(v, n=200):
    return str(v or '').strip()[:n]


def _clean_med_ids(ids):
    """Keep only medicine ids the user actually owns (drops stale/foreign ids)."""
    uid = current_user_id()
    if not isinstance(ids, (list, tuple)):
        return []
    owned = {r['id'] for r in (execute("SELECT id FROM medicines WHERE user_id=?", (uid,), fetchall=True) or [])}
    return [str(i) for i in ids if str(i) in owned]


def create_prescription(data) -> dict:
    uid = current_user_id()
    prescriber = _s(data.get('prescriber'), 120)
    med_ids = _clean_med_ids(data.get('medicine_ids') or [])
    if not prescriber and not med_ids:
        raise ValueError('Add a prescriber or link at least one medicine')
    date_issued = data.get('date_issued')
    if not valid_date(date_issued):
        date_issued = user_today()
    valid_until = data.get('valid_until')
    valid_until = valid_until if (valid_until and valid_date(valid_until)) else None
    refills = data.get('refills_left')
    try:
        refills = None if refills in (None, '') else max(0, min(int(refills), 99))
    except (TypeError, ValueError):
        refills = None
    pid = new_id()
    execute("""INSERT INTO prescriptions
                 (id, prescriber, date_issued, valid_until, refills_left, medicine_ids, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, prescriber, date_issued, valid_until, refills, jdump(med_ids),
             _s(data.get('notes'), 500), now_iso(), uid), commit=True)
    return _decorate(execute("SELECT * FROM prescriptions WHERE id=?", (pid,), fetchone=True))


def update_prescription(pid, data) -> dict:
    uid = current_user_id()
    row = execute("SELECT * FROM prescriptions WHERE id=? AND user_id=?", (pid, uid), fetchone=True)
    if not row:
        raise ValueError('Prescription not found')
    row = dict(row)
    prescriber = _s(data.get('prescriber', row['prescriber']), 120)
    date_issued = data.get('date_issued', row['date_issued'])
    if not valid_date(date_issued):
        date_issued = row['date_issued']
    if 'valid_until' in data:
        vu = data.get('valid_until')
        valid_until = vu if (vu and valid_date(vu)) else None
    else:
        valid_until = row['valid_until']
    if 'refills_left' in data:
        rf = data.get('refills_left')
        try:
            refills = None if rf in (None, '') else max(0, min(int(rf), 99))
        except (TypeError, ValueError):
            refills = None
    else:
        refills = row['refills_left']
    med_ids = _clean_med_ids(data['medicine_ids']) if 'medicine_ids' in data else jload(row['medicine_ids'], [])
    if not prescriber and not med_ids:
        raise ValueError('Add a prescriber or link at least one medicine')
    execute("""UPDATE prescriptions SET prescriber=?, date_issued=?, valid_until=?, refills_left=?,
                 medicine_ids=?, notes=? WHERE id=? AND user_id=?""",
            (prescriber, date_issued, valid_until, refills, jdump(med_ids),
             _s(data.get('notes', row['notes']), 500), pid, uid), commit=True)
    return _decorate(execute("SELECT * FROM prescriptions WHERE id=? AND user_id=?", (pid, uid), fetchone=True))


def delete_prescription(pid) -> bool:
    execute("DELETE FROM prescriptions WHERE id=? AND user_id=?", (pid, current_user_id()), commit=True)
    return True


def _status(valid_until):
    """None (no expiry set) | 'expired' | 'expiring' (<=14d) | 'valid'."""
    if not valid_until or not valid_date(valid_until):
        return None, None
    try:
        days = (_dt.date.fromisoformat(valid_until) - _dt.date.fromisoformat(user_today())).days
    except ValueError:
        return None, None
    if days < 0:
        return 'expired', days
    if days <= EXPIRING_WINDOW:
        return 'expiring', days
    return 'valid', days


def _decorate(row):
    uid = current_user_id()
    d = dict(row)
    ids = jload(d.get('medicine_ids'), [])
    meds = []
    if ids:
        rows = execute("SELECT id, name, icon FROM medicines WHERE user_id=?", (uid,), fetchall=True) or []
        by_id = {r['id']: r for r in rows}
        meds = [{'id': i, 'name': by_id[i]['name'], 'icon': by_id[i]['icon']} for i in ids if i in by_id]
    d['medicines'] = meds
    d['medicine_ids'] = ids
    status, days = _status(d.get('valid_until'))
    d['status'] = status
    d['days_until_expiry'] = days
    return d


def list_prescriptions() -> dict:
    uid = current_user_id()
    rows = execute("SELECT * FROM prescriptions WHERE user_id=? ORDER BY date_issued DESC, created_at DESC",
                   (uid,), fetchall=True) or []
    items = [_decorate(r) for r in rows]
    attention = sum(1 for i in items if i['status'] in ('expired', 'expiring')
                    or (i['refills_left'] is not None and i['refills_left'] == 0))
    return {'prescriptions': items, 'attention_count': attention}
