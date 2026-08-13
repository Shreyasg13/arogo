"""
db/med_effectiveness.py — J5 "is it working?" log. A periodic 1-5 self-rating of
how well each medicine seems to be working, in the patient's own view, with a
simple trend. This captures the patient's read — distinct from G6, which
correlates a target symptom with adherence. Purely self-report; not a clinical
measure of efficacy.
"""
import datetime as _dt

from .core import execute, current_user_id, user_today, valid_date, new_id, now_iso
from .medicines import list_medicines


def log_effectiveness(data: dict) -> dict:
    mid = str(data.get('medicine_id', '')).strip()
    if not mid:
        raise ValueError('A medicine is required')
    # Ownership: only rate a medicine the caller owns.
    owned = execute("SELECT 1 FROM medicines WHERE id=? AND user_id=?",
                    (mid, current_user_id()), fetchone=True)
    if not owned:
        raise ValueError('Medicine not found')
    try:
        rating = int(data.get('rating'))
    except (TypeError, ValueError):
        raise ValueError('A rating from 1 to 5 is required')
    if not (1 <= rating <= 5):
        raise ValueError('A rating from 1 to 5 is required')
    date_key = data.get('date_key')
    if not date_key or not valid_date(date_key):
        date_key = user_today()
    rid = new_id()
    execute("""INSERT INTO med_effectiveness (id, medicine_id, rating, date_key, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (rid, mid, rating, date_key, str(data.get('notes', ''))[:200], now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM med_effectiveness WHERE id=?", (rid,), fetchone=True))


def delete_effectiveness(rid: str) -> bool:
    execute("DELETE FROM med_effectiveness WHERE id=? AND user_id=?",
            (rid, current_user_id()), commit=True)
    return True


def get_effectiveness(days: int = 180) -> dict:
    """Per active medicine: latest rating, average over the window, count, and a
    recent series (oldest→newest). Only medicines that have at least one rating
    appear; direction compares the latest against the earlier average."""
    uid = current_user_id()
    days = max(1, min(int(days or 180), 3650))
    start = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    meds = {m['id']: m for m in list_medicines() if m['active']}

    by_med = {}
    for r in (execute("""SELECT id, medicine_id, rating, date_key FROM med_effectiveness
                         WHERE user_id=? AND date_key>=? ORDER BY date_key, created_at""",
                      (uid, start), fetchall=True) or []):
        by_med.setdefault(r['medicine_id'], []).append(dict(r))

    out = []
    for mid, ratings in by_med.items():
        med = meds.get(mid)
        if not med:
            continue    # inactive/deleted med — skip
        vals = [x['rating'] for x in ratings]
        latest = ratings[-1]
        avg = round(sum(vals) / len(vals), 1)
        # Direction: latest vs the mean of everything before it (needs >=2 ratings).
        direction = 'flat'
        if len(vals) >= 2:
            prior_avg = sum(vals[:-1]) / len(vals[:-1])
            if latest['rating'] > prior_avg + 0.25:
                direction = 'up'
            elif latest['rating'] < prior_avg - 0.25:
                direction = 'down'
        out.append({
            'id': mid, 'name': med.get('name') or 'Medicine',
            'latest': latest['rating'], 'latest_date': latest['date_key'],
            'average': avg, 'count': len(vals),
            'series': [{'rating': x['rating'], 'date': x['date_key'], 'id': x['id']} for x in ratings],
            'direction': direction,
        })

    out.sort(key=lambda x: x['name'].lower())
    return {'has_data': bool(out), 'meds': out}
