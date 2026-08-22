"""
db/insurance.py — your health-insurance policies and when they renew.

The app already tracked claims (money you asked back) and spend (money you paid),
but not the policies themselves. This holds the facts you'd otherwise hunt for in
an email: insurer, policy number, cover, premium, who's covered, and — the part
that actually bites — the renewal date.

HONESTY: this stores and counts down what YOU entered. It never rates a policy,
never says your cover is enough or too little, never recommends buying anything,
and never contacts an insurer. "Days until renewal" is arithmetic on your own
date; if you didn't enter one, we say nothing rather than guess.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date, to_num

KINDS = ('health', 'accident', 'critical_illness', 'life', 'travel', 'other')
PERIODS = ('year', 'month', 'quarter')
RENEWAL_SOON_DAYS = 30          # inside this window we surface it as "coming up"


def _clean_kind(k):
    k = str(k or '').strip().lower()
    return k if k in KINDS else 'other'


def _clean_period(p):
    p = str(p or '').strip().lower()
    return p if p in PERIODS else 'year'


def _decorate(row):
    d = dict(row)
    d['days_to_renewal'] = None
    d['renewal_status'] = 'unknown'      # unknown | expired | soon | ok
    rd = d.get('renewal_date')
    if rd and valid_date(rd):
        try:
            days = (dt.date.fromisoformat(rd) - dt.date.fromisoformat(user_today())).days
            d['days_to_renewal'] = days
            d['renewal_status'] = 'expired' if days < 0 else ('soon' if days <= RENEWAL_SOON_DAYS else 'ok')
        except Exception:
            pass
    return d


def create_policy(data):
    insurer = str((data or {}).get('insurer') or '').strip()
    if not insurer:
        raise ValueError('Who is the insurer?')
    renewal = (data or {}).get('renewal_date')
    start = (data or {}).get('start_date')
    pid = new_id()
    execute("""INSERT INTO insurance_policies
               (id, insurer, policy_no, kind, cover_amount, premium, premium_period,
                start_date, renewal_date, members, notes, active, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (pid, insurer[:120], str((data or {}).get('policy_no') or '')[:80],
             _clean_kind((data or {}).get('kind')),
             to_num((data or {}).get('cover_amount'), None),
             to_num((data or {}).get('premium'), None),
             _clean_period((data or {}).get('premium_period')),
             start if valid_date(start) else None,
             renewal if valid_date(renewal) else None,
             str((data or {}).get('members') or '')[:200],
             str((data or {}).get('notes') or '')[:500],
             now_iso(), current_user_id()), commit=True)
    return get_policy(pid)


def get_policy(pid):
    r = execute("SELECT * FROM insurance_policies WHERE id=? AND user_id=?",
                (pid, current_user_id()), fetchone=True)
    return _decorate(r) if r else None


def update_policy(pid, data):
    cur = get_policy(pid)
    if not cur:
        raise ValueError('Policy not found')
    renewal = data.get('renewal_date', cur.get('renewal_date'))
    start = data.get('start_date', cur.get('start_date'))
    execute("""UPDATE insurance_policies SET insurer=?, policy_no=?, kind=?, cover_amount=?,
               premium=?, premium_period=?, start_date=?, renewal_date=?, members=?, notes=?, active=?
               WHERE id=? AND user_id=?""",
            (str(data.get('insurer', cur['insurer']) or cur['insurer'])[:120],
             str(data.get('policy_no', cur.get('policy_no')) or '')[:80],
             _clean_kind(data.get('kind', cur.get('kind'))),
             to_num(data.get('cover_amount', cur.get('cover_amount')), None),
             to_num(data.get('premium', cur.get('premium')), None),
             _clean_period(data.get('premium_period', cur.get('premium_period'))),
             start if valid_date(start) else None,
             renewal if valid_date(renewal) else None,
             str(data.get('members', cur.get('members')) or '')[:200],
             str(data.get('notes', cur.get('notes')) or '')[:500],
             0 if data.get('active') is False else 1,
             pid, current_user_id()), commit=True)
    return get_policy(pid)


def delete_policy(pid):
    execute("DELETE FROM insurance_policies WHERE id=? AND user_id=?",
            (pid, current_user_id()), commit=True)


def list_policies():
    """Active policies first, then soonest renewal. Includes a summary of the
    total premium — a plain sum of what the user entered, per year."""
    rows = execute("SELECT * FROM insurance_policies WHERE user_id=? ORDER BY active DESC, insurer",
                   (current_user_id(),), fetchall=True) or []
    out = [_decorate(r) for r in rows]
    # Soonest renewal first among active ones (unknown dates sink).
    out.sort(key=lambda p: (not p['active'],
                            p['days_to_renewal'] if p['days_to_renewal'] is not None else 10 ** 6))
    yearly = 0.0
    for p in out:
        if not p['active'] or p.get('premium') is None:
            continue
        mult = {'year': 1, 'quarter': 4, 'month': 12}.get(p.get('premium_period') or 'year', 1)
        yearly += float(p['premium']) * mult
    return {
        'policies': out,
        'summary': {
            'active': sum(1 for p in out if p['active']),
            'yearly_premium': round(yearly, 2) if yearly else None,
            'renewing_soon': [
                {'id': p['id'], 'insurer': p['insurer'], 'renewal_date': p['renewal_date'],
                 'days': p['days_to_renewal']}
                for p in out if p['active'] and p['renewal_status'] in ('soon', 'expired')
            ],
        },
    }
