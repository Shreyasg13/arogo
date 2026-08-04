"""
db/labs.py — lab-panel results (HbA1c, lipids, thyroid, vitamins, CBC…).

Distinct from `vitals` (point-in-time BP/sugar/HR readings): labs are periodic
panel values the user gets from a report. Each row is one test on one date.
Reference ranges + the in/low/high status come from lab_catalog (never stored,
so a range correction can't strand old rows), and the status is always framed
for the user as "worth discussing with a doctor," never a diagnosis.
"""
import math

from .core import execute, now_iso, new_id, current_user_id, valid_date
import lab_catalog


def _gender():
    r = execute("SELECT gender FROM user_profile WHERE user_id=? LIMIT 1",
                (current_user_id(),), fetchone=True)
    return (r['gender'] if r else None)


def _decorate(row, gender=None):
    """Attach the reference range + status to a stored result at read time."""
    d = dict(row)
    lo, hi = lab_catalog.ref_range(d['lab_key'], gender)
    d['ref_low'] = lo
    d['ref_high'] = hi
    d['status'] = lab_catalog.status_for(d['lab_key'], d['value'], gender)
    return d


def log_lab_result(lab_key, value, date_key, notes='') -> dict:
    """Record one lab value. Accepts any catalog test; a free-form key is allowed
    too (stored with no range) so nothing the user has is un-loggable."""
    meta = lab_catalog.get_lab(lab_key)
    if not meta and not str(lab_key or '').strip():
        raise ValueError('A test is required')
    try:
        val = float(value)
        if not math.isfinite(val):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('A numeric value is required')
    if not valid_date(date_key):
        from .core import today_iso
        date_key = today_iso()
    name = meta['name'] if meta else str(lab_key).strip()[:60]
    unit = meta['unit'] if meta else ''
    key = meta['key'] if meta else str(lab_key).strip().lower()[:40]
    lid = new_id()
    execute("""INSERT INTO lab_results (id, lab_key, name, value, unit, date_key, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (lid, key, name, val, unit, date_key, str(notes or '')[:300], now_iso(), current_user_id()),
            commit=True)
    return _decorate(execute("SELECT * FROM lab_results WHERE id=?", (lid,), fetchone=True), _gender())


def delete_lab_result(lid) -> bool:
    execute("DELETE FROM lab_results WHERE id=? AND user_id=?", (lid, current_user_id()), commit=True)
    return True


def get_latest_by_test() -> list:
    """Most-recent value per test, decorated with range/status — the Labs
    landing view. Grouped-ready: each item carries its catalog category."""
    rows = execute("""SELECT * FROM lab_results WHERE user_id=?
                      ORDER BY date_key DESC, created_at DESC""",
                   (current_user_id(),), fetchall=True) or []
    gender = _gender()
    seen, out = set(), []
    for r in rows:
        if r['lab_key'] in seen:
            continue
        seen.add(r['lab_key'])
        d = _decorate(r, gender)
        meta = lab_catalog.get_lab(d['lab_key'])
        d['category'] = meta['category'] if meta else 'Other'
        out.append(d)
    return out


def get_lab_trend(lab_key) -> dict:
    """All values for one test over time (oldest→newest) for a trend chart,
    plus the reference band and the newest status."""
    rows = execute("""SELECT * FROM lab_results WHERE user_id=? AND lab_key=?
                      ORDER BY date_key, created_at""",
                   (current_user_id(), lab_key), fetchall=True) or []
    gender = _gender()
    points = [{'date': r['date_key'], 'value': r['value'], 'id': r['id'],
               'status': lab_catalog.status_for(lab_key, r['value'], gender),
               'notes': r['notes']} for r in rows]
    lo, hi = lab_catalog.ref_range(lab_key, gender)
    meta = lab_catalog.get_lab(lab_key)
    return {'lab_key': lab_key,
            'name': meta['name'] if meta else lab_key,
            'unit': meta['unit'] if meta else (rows[0]['unit'] if rows else ''),
            'ref_low': lo, 'ref_high': hi,
            'points': points,
            'latest': points[-1] if points else None}


def get_catalog() -> dict:
    """Catalog for the add-a-lab picker, grouped by category, with per-test range
    resolved for this user's sex."""
    gender = _gender()
    grouped = {}
    for t in lab_catalog.CATALOG:
        lo, hi = lab_catalog.ref_range(t['key'], gender)
        grouped.setdefault(t['category'], []).append(
            {'key': t['key'], 'name': t['name'], 'unit': t['unit'],
             'ref_low': lo, 'ref_high': hi})
    return {'categories': lab_catalog.categories(), 'tests': grouped}
