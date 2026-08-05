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
    # A list/dict lab_key is malformed input — reject cleanly (a bare
    # lab_catalog.get_lab([...]) would otherwise raise TypeError → uncaught 500).
    if lab_key is not None and not isinstance(lab_key, (str, int, float)):
        raise ValueError('A test is required')
    lab_key = str(lab_key or '').strip()
    meta = lab_catalog.get_lab(lab_key)
    if not meta and not lab_key:
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


# ── Recheck reminders ─────────────────────────────────────────────────────────
# The user chooses which tests to keep an eye on and how often. "Due" is derived
# from the date of their OWN latest result for that test plus the interval — we
# never invent a value or issue an order, and the suggested intervals are framed
# as typical guidance the user can change.

SUGGESTED_RECHECK = {          # days — typical, NOT prescriptive
    'hba1c': 90, 'fasting_glucose': 90,
    'ldl': 180, 'hdl': 180, 'total_cholesterol': 180, 'triglycerides': 180,
    'tsh': 180, 't3': 180, 't4': 180,
    'vitamin_d': 180, 'vitamin_b12': 365,
    'creatinine': 180, 'egfr': 180, 'alt': 180, 'ast': 180,
}
DEFAULT_RECHECK_DAYS = 180


def suggested_recheck_days(lab_key) -> int:
    return SUGGESTED_RECHECK.get(str(lab_key or '').lower(), DEFAULT_RECHECK_DAYS)


def set_lab_recheck(lab_key, interval_days) -> dict:
    """Turn on (or update) a recheck reminder for one test. Idempotent per key."""
    uid = current_user_id()
    key = str(lab_key or '').strip().lower()[:40]
    if not key:
        raise ValueError('A test is required')
    try:
        days = max(1, min(int(interval_days), 3650))
    except (TypeError, ValueError):
        days = suggested_recheck_days(key)
    execute("DELETE FROM lab_rechecks WHERE user_id=? AND lab_key=?", (uid, key), commit=True)
    execute("INSERT INTO lab_rechecks (id, lab_key, interval_days, created_at, user_id) VALUES (?,?,?,?,?)",
            (new_id(), key, days, now_iso(), uid), commit=True)
    return {'lab_key': key, 'interval_days': days}


def clear_lab_recheck(lab_key) -> bool:
    execute("DELETE FROM lab_rechecks WHERE user_id=? AND lab_key=?",
            (current_user_id(), str(lab_key or '').strip().lower()[:40]), commit=True)
    return True


def get_lab_rechecks() -> dict:
    """Each configured recheck with its due status, derived from the user's own
    latest result date. status: 'due' | 'soon' (<=14d) | 'ok' | 'no_baseline'."""
    import datetime as _dt
    from .core import user_today
    uid = current_user_id()
    rows = execute("SELECT * FROM lab_rechecks WHERE user_id=?", (uid,), fetchall=True) or []
    try:
        today = _dt.date.fromisoformat(user_today())
    except ValueError:
        today = _dt.date.today()

    out = []
    for r in rows:
        key = r['lab_key']
        last = execute("""SELECT MAX(date_key) d FROM lab_results WHERE user_id=? AND lab_key=?""",
                       (uid, key), fetchone=True)
        last_done = last['d'] if last else None
        meta = lab_catalog.get_lab(key)
        item = {'lab_key': key, 'name': meta['name'] if meta else key,
                'interval_days': r['interval_days'], 'last_done': last_done,
                'next_due': None, 'days_until': None, 'status': 'no_baseline'}
        if last_done and valid_date(last_done):
            nd = _dt.date.fromisoformat(last_done) + _dt.timedelta(days=r['interval_days'])
            days_until = (nd - today).days
            item['next_due'] = nd.isoformat()
            item['days_until'] = days_until
            item['status'] = 'due' if days_until <= 0 else 'soon' if days_until <= 14 else 'ok'
        out.append(item)
    # Due first, then soonest.
    order = {'due': 0, 'soon': 1, 'no_baseline': 2, 'ok': 3}
    out.sort(key=lambda x: (order[x['status']], x['days_until'] if x['days_until'] is not None else 9999))
    return {'rechecks': out, 'due_count': sum(1 for x in out if x['status'] == 'due')}


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
