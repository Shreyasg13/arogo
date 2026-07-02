"""
db/medicines.py — Medicine tracker, dose logging, refill/stock management.

All queries are scoped to the authenticated user via current_user_id().
"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id


def insert_medicine(data: dict) -> dict:
    mid = new_id()
    execute("""
        INSERT INTO medicines
          (id,name,dosage,unit,frequency,times,with_food,notes,color,icon,start_date,end_date,active,created_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
    """, (mid, data['name'], data['dosage'], data.get('unit','mg'),
          data.get('frequency','once_daily'), jdump(data.get('times',['08:00'])),
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
        return
    lid = new_id()
    # Upsert
    existing = execute(
        "SELECT id FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
        (medicine_id, date_key, time_key, uid), fetchone=True)
    if existing:
        execute("UPDATE dose_logs SET taken=?, taken_at=? WHERE id=?",
                (1 if taken else 0, now_iso(), existing['id']), commit=True)
    else:
        execute("""
            INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at,user_id)
            VALUES (?,?,?,?,?,?,?)
        """, (lid, medicine_id, date_key, time_key, 1 if taken else 0, now_iso(), uid),
            commit=True)


def get_today_doses():
    uid = current_user_id()
    today = today_iso()
    meds = [m for m in list_medicines() if m['active']]
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
    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        for m in meds:
            if not m['active']: continue
            for t in m.get('times', []):
                total += 1
                log = execute(
                    "SELECT taken FROM dose_logs WHERE medicine_id=? AND date_key=? AND time_key=? AND user_id=?",
                    (m['id'], d, t, uid), fetchone=True)
                if log and log.get('taken'): taken += 1
    return {'total': total, 'taken': taken, 'pct': round(taken/total*100, 1) if total else 0}


# ── Refill / stock ────────────────────────────────────────────────────────────

def update_medicine_stock(mid: str, pill_count: int, pills_per_dose: int = 1, refill_threshold: int = 7) -> dict:
    execute("UPDATE medicines SET pill_count=?,pills_per_dose=?,refill_threshold=? WHERE id=? AND user_id=?",
            (pill_count, pills_per_dose, refill_threshold, mid, current_user_id()), commit=True)
    r = execute("SELECT * FROM medicines WHERE id=? AND user_id=?",
                (mid, current_user_id()), fetchone=True)
    return dict(r) if r else {}

def decrement_pill_count(mid: str):
    """Call after a dose is taken to reduce stock."""
    uid = current_user_id()
    r = execute("SELECT pill_count,pills_per_dose FROM medicines WHERE id=? AND user_id=?",
                (mid, uid), fetchone=True)
    if r and r['pill_count'] is not None:
        new_count = max(0, r['pill_count'] - (r['pills_per_dose'] or 1))
        execute("UPDATE medicines SET pill_count=? WHERE id=? AND user_id=?",
                (new_count, mid, uid), commit=True)

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
