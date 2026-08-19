"""
db/care_circle.py — a caregiver "command center".

Composes the app's EXISTING caregiver views into one at-a-glance board for the
people you help look after: each member's today's-dose status (from care_status)
merged with their week (from generate_caregiver_digest), plus a plain sentence
you can read or hear. It adds no new data access — everything stays behind the
same per-category consent gates (a member appears only if they share medicines,
and sleep only if they share sleep).

Honest & reassurance-framed: it reports what the member logged (doses taken,
what's overdue, running low), never a verdict or medical advice. "No alert"
reads as "they're keeping up", never as ambiguous silence.
"""
from __future__ import annotations


def _summary_line(e):
    """A plain, speakable sentence about one member — facts only."""
    n = e['name']
    td, wk = e['today'], e['week']
    parts = []
    if td['total']:
        parts.append(f"{n} has taken {td['taken']} of {td['total']} doses today.")
    else:
        parts.append(f"{n} has no doses scheduled today.")
    od = len(td.get('overdue') or [])
    if od:
        parts.append(f"{od} {'is' if od == 1 else 'are'} overdue.")
    ls = len(td.get('low_stock') or [])
    if ls:
        parts.append(f"{ls} medicine{'s' if ls != 1 else ''} running low.")
    if not od and not ls and td['total']:
        parts.append("Nothing needs attention right now.")
    if wk.get('adherence_pct') is not None:
        parts.append(f"This week, {wk['adherence_pct']}% of doses taken.")
    if wk.get('sleep_avg'):
        parts.append(f"Sleeping about {wk['sleep_avg']} hours a night.")
    return ' '.join(parts)


def get_care_circle():
    """One board for every member who shares their medicines with you. Empty when
    you're not a caregiver for anyone."""
    from .family import care_status, generate_caregiver_digest

    today_list = care_status() or []
    digest = generate_caregiver_digest() or {}
    week_by_name = {m['name']: m for m in (digest.get('members') or [])}

    members, needs = [], 0
    for m in today_list:
        wk = week_by_name.get(m['name'], {})
        attention = bool(m.get('overdue') or m.get('low_stock'))
        if attention:
            needs += 1
        entry = {
            'user_id': m['user_id'],
            'name': m['name'],
            'attention': attention,
            'checking_by': m.get('checking_by'),
            'checking_is_me': m.get('checking_is_me', False),
            'today': {
                'taken': m.get('taken', 0), 'total': m.get('total', 0),
                'overdue': m.get('overdue') or [], 'low_stock': m.get('low_stock') or [],
                'last_ago_min': m.get('last_ago_min'),
            },
            'week': {
                'adherence_pct': wk.get('adherence_pct'),
                'taken': wk.get('taken', 0), 'total': wk.get('total', 0),
                'sleep_avg': wk.get('sleep_avg'), 'symptoms': wk.get('symptoms', 0),
            },
        }
        entry['summary'] = _summary_line(entry)
        members.append(entry)

    # Sort: anyone needing attention first, then by name.
    members.sort(key=lambda e: (not e['attention'], e['name'].lower()))
    return {
        'members': members,
        'count': len(members),
        'needs_attention': needs,
        'period_label': digest.get('period_label'),
    }
