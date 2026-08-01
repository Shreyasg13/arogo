"""
db/medicines.py — Medicine tracker, dose logging, refill/stock management.

All queries are scoped to the authenticated user via current_user_id().
"""
import re

from .core import (execute, executemany, jdump, jload, now_iso, today_iso, user_today,
                   new_id, current_user_id)

_TIME_RE = re.compile(r'^([01]?\d|2[0-3]):[0-5]\d$')


def _clean_times(raw):
    """Coerce a submitted `times` value into a list of valid HH:MM strings.

    Guards against the class of bugs where a scalar string (e.g. '08:00') is
    stored as JSON and later iterated character-by-character in the today view.
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return ['08:00']
    out = []
    for t in raw:
        if not isinstance(t, str):
            continue
        t = t.strip()
        # Normalise single-digit hour ("8:00" -> "08:00")
        if _TIME_RE.match(t):
            h, m = t.split(':')
            out.append(f'{int(h):02d}:{m}')
    # De-dupe while preserving order; cap to a sane maximum
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:24] or ['08:00']


def insert_medicine(data: dict) -> dict:
    name = str(data.get('name', '')).strip()
    if not name:
        raise ValueError('Medicine name is required')
    mid = new_id()
    execute("""
        INSERT INTO medicines
          (id,name,dosage,unit,frequency,times,with_food,notes,color,icon,start_date,end_date,active,created_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
    """, (mid, name[:120], str(data.get('dosage', '')).strip()[:60], data.get('unit','mg'),
          data.get('frequency','once_daily'), jdump(_clean_times(data.get('times', ['08:00']))),
          1 if data.get('with_food') else 0, data.get('notes',''),
          data.get('color','teal'), data.get('icon','💊'),
          data.get('start_date', today_iso()), data.get('end_date',''), now_iso(),
          current_user_id()),
        commit=True)
    return get_medicine(mid)


def get_medicine(mid):
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?",
                (mid, current_user_id()), fetchone=True)
    return _fmt_med(r) if r else None


def list_medicines():
    rows = execute("SELECT * FROM medicines WHERE user_id=? ORDER BY created_at DESC",
                   (current_user_id(),), fetchall=True)
    return [_fmt_med(r) for r in rows]


def toggle_medicine(mid):
    execute("UPDATE medicines SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=? AND user_id=?",
            (mid, current_user_id()), commit=True)


def delete_medicine(mid):
    execute("DELETE FROM medicines WHERE id=? AND user_id=?",
            (mid, current_user_id()), commit=True)


def _fmt_med(r):
    d = dict(r)
    d['times'] = jload(d.get('times', '["08:00"]'), ['08:00'])
    d['with_food'] = bool(d.get('with_food', 0))
    d['active'] = bool(d.get('active', 1))
    return d


# ── Dose Logs ────────────────────────────────────────────────────────────────

def log_dose(medicine_id, date_key, time_key, taken=True):
    uid = current_user_id()
    # Only log doses against medicines the user owns
    owner = execute("SELECT id FROM medicines WHERE id=? AND user_id=?",
                    (medicine_id, uid), fetchone=True)
    if not owner:
        return False
    lid = new_id()
    # Upsert
    existing = execute(
        "SELECT id, taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
        (medicine_id, date_key, time_key, uid), fetchone=True)
    prev_taken = bool(existing and existing['taken'])
    new_taken  = bool(taken)
    if existing:
        execute("UPDATE dose_logs SET taken=?, taken_at=? WHERE id=?",
                (1 if new_taken else 0, now_iso(), existing['id']), commit=True)
    else:
        execute("""
            INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at,user_id)
            VALUES (?,?,?,?,?,?,?)
        """, (lid, medicine_id, date_key, time_key, 1 if new_taken else 0, now_iso(), uid),
            commit=True)
    # Keep pill stock honest: consume on a fresh "taken", restore on un-take.
    # Guarded on the state *transition* so a double-log never double-counts,
    # and on the recorded ledger so an un-take restores exactly what the take
    # removed — never more. Restoring blind is how the count invented pills.
    row_id = existing['id'] if existing else lid
    if new_taken and not prev_taken:
        applied = _consume_stock(medicine_id)
        execute("UPDATE dose_logs SET pills_applied=? WHERE id=? AND user_id=?",
                (applied, row_id, uid), commit=True)
    elif prev_taken and not new_taken:
        _restore_stock(medicine_id, _pills_applied(row_id, uid))
        execute("UPDATE dose_logs SET pills_applied=0 WHERE id=? AND user_id=?",
                (row_id, uid), commit=True)
    return True


def _in_course(m, day):
    """True if `day` (ISO date) falls within a medicine's active course.

    start_date defaults to the creation day; an empty end_date means ongoing.
    Used so the today view and adherence math ignore days before the medicine
    existed and days after a finished course.
    """
    start = m.get('start_date') or ''
    end = m.get('end_date') or ''
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def get_today_doses():
    uid = current_user_id()
    # The user's day, not the server's — the app and service worker write dose
    # rows keyed to the device's local date, and this is what reads them back.
    today = user_today()
    meds = [m for m in list_medicines() if m['active'] and _in_course(m, today)]
    doses = []
    for m in meds:
        for t in m.get('times', []):
            log = execute(
                "SELECT * FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
                (m['id'], today, t, uid), fetchone=True)
            doses.append({
                'med_id': m['id'], 'med_name': m['name'], 'dosage': m['dosage'],
                'unit': m['unit'], 'time': t, 'icon': m.get('icon', '💊'),
                'color': m.get('color', 'teal'), 'with_food': m.get('with_food', False),
                'taken': bool(log and log.get('taken')),
                'taken_at': log['taken_at'] if log else ''
            })
    doses.sort(key=lambda x: x['time'])
    return doses


def get_adherence_stats(days=30):
    """Compute adherence % over the past N days."""
    from datetime import date, timedelta
    uid = current_user_id()
    total, taken = 0, 0
    meds = list_medicines()
    for i in range(max(0, days)):
        d = (date.today() - timedelta(days=i)).isoformat()
        for m in meds:
            if not m['active']: continue
            if not _in_course(m, d): continue   # don't penalise days outside the course
            for t in m.get('times', []):
                total += 1
                log = execute(
                    "SELECT taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
                    (m['id'], d, t, uid), fetchone=True)
                if log and log.get('taken'): taken += 1
    return {'total': total, 'taken': taken, 'pct': round(taken/total*100, 1) if total else 0}


# ── Refill / stock ────────────────────────────────────────────────────────────

def update_medicine_stock(mid: str, pill_count: int, pills_per_dose: int = 1,
                          refill_threshold: int = 7, pharmacy_note=None) -> dict:
    uid = current_user_id()
    prev = execute("SELECT pill_count FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    prev_count = prev['pill_count'] if prev and prev['pill_count'] is not None else 0
    # Restocking (count went up) means the refill arrived — clear any pending
    # "ordered" flag so it doesn't keep showing as on-the-way.
    clear = pill_count > prev_count
    sets = "pill_count=?, pills_per_dose=?, refill_threshold=?"
    params = [pill_count, pills_per_dose, refill_threshold]
    if pharmacy_note is not None:
        sets += ", pharmacy_note=?"; params.append((pharmacy_note or '')[:200])
    if clear:
        sets += ", refill_status=NULL, refill_ordered_at=NULL"
    params += [mid, uid]
    execute(f"UPDATE medicines SET {sets} WHERE id=? AND user_id=?", tuple(params), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    return _fmt_med(r) if r else {}


def mark_refill_ordered(mid: str) -> dict:
    """Mark a refill as ordered so it stops nagging until it arrives."""
    uid = current_user_id()
    execute("UPDATE medicines SET refill_status='ordered', refill_ordered_at=? WHERE id=? AND user_id=?",
            (now_iso(), mid, uid), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    return _fmt_med(r) if r else {}


def set_pharmacy_note(mid: str, note: str) -> dict:
    """Where/how you refill this one — a free-text reminder to yourself."""
    uid = current_user_id()
    execute("UPDATE medicines SET pharmacy_note=? WHERE id=? AND user_id=?",
            ((note or '')[:200], mid, uid), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
    return _fmt_med(r) if r else {}

def _pills_applied(dose_log_id: str, uid: str) -> int:
    r = execute("SELECT pills_applied FROM dose_logs WHERE id=? AND user_id=?",
                (dose_log_id, uid), fetchone=True)
    try:
        return max(0, int(r['pills_applied'] or 0)) if r else 0
    except (KeyError, TypeError, IndexError):
        return 0        # pre-migration row: restore nothing rather than invent


def _consume_stock(mid: str) -> int:
    """Take one dose's worth of pills out of stock; return how many actually
    came out. Stock can't go below zero, so a user who's out of pills consumes
    0 — and that 0 is what an un-take must give back. Returns 0 when the
    medicine tracks no stock (pill_count IS NULL)."""
    uid = current_user_id()
    r = execute("SELECT pill_count,pills_per_dose FROM medicines WHERE id=? AND user_id=?",
                (mid, uid), fetchone=True)
    if not r or r['pill_count'] is None:
        return 0
    applied = min(r['pills_per_dose'] or 1, r['pill_count'])
    if applied <= 0:
        return 0
    execute("UPDATE medicines SET pill_count=? WHERE id=? AND user_id=?",
            (r['pill_count'] - applied, mid, uid), commit=True)
    return applied


def _restore_stock(mid: str, pills: int):
    """Put back exactly the pills a take removed — no more."""
    if pills <= 0:
        return
    uid = current_user_id()
    r = execute("SELECT pill_count FROM medicines WHERE id=? AND user_id=?",
                (mid, uid), fetchone=True)
    if not r or r['pill_count'] is None:
        return
    execute("UPDATE medicines SET pill_count=? WHERE id=? AND user_id=?",
            (r['pill_count'] + pills, mid, uid), commit=True)


def _apply_stock_delta(mid: str, doses: int):
    """Back-compat shim for callers outside the dose-log ledger."""
    if doses < 0:
        _consume_stock(mid)
    elif doses > 0:
        r = execute("SELECT pills_per_dose FROM medicines WHERE id=? AND user_id=?",
                    (mid, current_user_id()), fetchone=True)
        _restore_stock(mid, (r['pills_per_dose'] or 1) if r else 1)


def decrement_pill_count(mid: str):
    """Call after a dose is taken to reduce stock (one dose's worth)."""
    _apply_stock_delta(mid, -1)

def get_low_stock_medicines():
    """Return medicines where days remaining < refill_threshold."""
    meds = list_medicines()
    low = []
    for m in meds:
        if m.get('pill_count') is None: continue
        freq_doses = {
            'once_daily':1, 'twice_daily':2, 'thrice_daily':3, 'weekly':1/7,
            'once':1, 'twice':2, 'three_times':3   # legacy keys
        }.get(m.get('frequency','once_daily'), 1)
        days_left = m['pill_count'] / max(freq_doses * (m.get('pills_per_dose') or 1), 0.01)
        if days_left < (m.get('refill_threshold') or 7):
            low.append({**m, 'days_left': round(days_left, 1)})
    return low
