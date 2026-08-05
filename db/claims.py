"""
db/claims.py — insurance-claims tracker.

Track a claim through its real lifecycle: submitted → under review → approved →
paid (or rejected). The reimbursed amount is what has ACTUALLY been paid, kept
separate from the amount claimed — a submitted claim is not money in hand, and
the status never overstates that. Sits alongside the health-spending tracker.
"""
import math

from .core import execute, now_iso, new_id, current_user_id, valid_date, user_today

# The lifecycle. 'paid'/'partially_paid'/'rejected' are terminal (not pending).
STATUSES = ('submitted', 'under_review', 'approved', 'partially_paid', 'paid', 'rejected')
_PENDING = {'submitted', 'under_review', 'approved'}


def _num(v, default=0.0):
    try:
        n = float(v)
        return n if math.isfinite(n) and n >= 0 else default
    except (TypeError, ValueError):
        return default


def _s(v, n=200):
    return str(v or '').strip()[:n]


def _clean_status(v, default='submitted'):
    v = _s(v, 30).lower().replace(' ', '_')
    return v if v in STATUSES else default


def create_claim(data) -> dict:
    insurer = _s(data.get('insurer'), 120)
    if not insurer:
        raise ValueError('An insurer is required')
    amount = _num(data.get('amount'))
    if amount <= 0:
        raise ValueError('A claim amount is required')
    date_submitted = data.get('date_submitted')
    if not valid_date(date_submitted):
        date_submitted = user_today()
    cid = new_id()
    execute("""INSERT INTO claims (id, insurer, amount, date_submitted, status, reimbursed, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (cid, insurer, amount, date_submitted, _clean_status(data.get('status')),
             _num(data.get('reimbursed')), _s(data.get('notes'), 500), now_iso(), current_user_id()),
            commit=True)
    return _decorate(execute("SELECT * FROM claims WHERE id=?", (cid,), fetchone=True))


def update_claim(cid, data) -> dict:
    uid = current_user_id()
    row = execute("SELECT * FROM claims WHERE id=? AND user_id=?", (cid, uid), fetchone=True)
    if not row:
        raise ValueError('Claim not found')
    row = dict(row)
    insurer = _s(data.get('insurer', row['insurer']), 120) or row['insurer']
    amount = _num(data.get('amount', row['amount']), row['amount']) if 'amount' in data else row['amount']
    date_submitted = data.get('date_submitted', row['date_submitted'])
    if not valid_date(date_submitted):
        date_submitted = row['date_submitted']
    status = _clean_status(data.get('status'), row['status']) if 'status' in data else row['status']
    reimbursed = _num(data.get('reimbursed'), row['reimbursed']) if 'reimbursed' in data else row['reimbursed']
    execute("""UPDATE claims SET insurer=?, amount=?, date_submitted=?, status=?, reimbursed=?, notes=?
               WHERE id=? AND user_id=?""",
            (insurer, amount, date_submitted, status, reimbursed,
             _s(data.get('notes', row['notes']), 500), cid, uid), commit=True)
    return _decorate(execute("SELECT * FROM claims WHERE id=? AND user_id=?", (cid, uid), fetchone=True))


def delete_claim(cid) -> bool:
    execute("DELETE FROM claims WHERE id=? AND user_id=?", (cid, current_user_id()), commit=True)
    return True


def _decorate(row):
    d = dict(row)
    d['pending'] = d['status'] in _PENDING
    # What's still outstanding on this claim (never negative).
    d['outstanding'] = round(max(0.0, (d['amount'] or 0) - (d['reimbursed'] or 0)), 2)
    return d


def list_claims() -> dict:
    uid = current_user_id()
    rows = execute("SELECT * FROM claims WHERE user_id=? ORDER BY date_submitted DESC, created_at DESC",
                   (uid,), fetchall=True) or []
    items = [_decorate(r) for r in rows]
    total_claimed = round(sum(i['amount'] or 0 for i in items), 2)
    total_reimbursed = round(sum(i['reimbursed'] or 0 for i in items), 2)
    return {
        'claims': items,
        'summary': {
            'total_claimed': total_claimed,
            'total_reimbursed': total_reimbursed,
            # Honest: only what's paid on still-open claims is "awaiting" — a
            # rejected claim's gap isn't money that's coming.
            'awaiting': round(sum(i['outstanding'] for i in items if i['pending']), 2),
            'pending_count': sum(1 for i in items if i['pending']),
        },
        'statuses': list(STATUSES),
    }
