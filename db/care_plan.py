"""
db/care_plan.py — a shared care plan.

A care plan is the set of agreements between a person, their caregiver and their
doctor: what to do, who's responsible, and when to review it. Each item has a
category, an owner (me / caregiver / doctor), a status, and an optional review
date.

"Shared" reuses the existing caregiver acting-as model — a caregiver acting for
a member reads and edits the member's plan through the same current_user_id
chokepoint, so there's no separate sharing surface to secure. Everything here is
user/caregiver/doctor-authored: no AI-generated medical advice is ever written.
"""
from .core import execute, now_iso, new_id, current_user_id, valid_date

CATEGORIES = ('medication', 'lifestyle', 'monitoring', 'appointment', 'other')
OWNERS = ('me', 'caregiver', 'doctor')


def _clean(v, allowed, default):
    v = (v or '').strip().lower()
    return v if v in allowed else default


def create_item(title, detail='', category='other', owner='me', review_date=None) -> dict:
    title = (title or '').strip()
    if not title:
        raise ValueError('A title is required')
    rd = review_date if (review_date and valid_date(review_date)) else None
    iid = new_id()
    execute("""INSERT INTO care_plan_items
                 (id, title, detail, category, owner, status, review_date, created_at, user_id)
               VALUES (?,?,?,?,?, 'active', ?, ?, ?)""",
            (iid, title[:160], str(detail or '')[:1000],
             _clean(category, CATEGORIES, 'other'), _clean(owner, OWNERS, 'me'),
             rd, now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM care_plan_items WHERE id=?", (iid,), fetchone=True))


def update_item(iid, data) -> dict:
    uid = current_user_id()
    row = execute("SELECT * FROM care_plan_items WHERE id=? AND user_id=?", (iid, uid), fetchone=True)
    if not row:
        raise ValueError('Item not found')
    row = dict(row)
    title = data.get('title', row['title'])
    title = (title or '').strip() or row['title']
    detail = data.get('detail', row['detail'])
    category = _clean(data.get('category', row['category']), CATEGORIES, row['category'])
    owner = _clean(data.get('owner', row['owner']), OWNERS, row['owner'])
    status = data.get('status', row['status'])
    status = status if status in ('active', 'done') else row['status']
    rd = data.get('review_date', row['review_date'])
    rd = rd if (rd and valid_date(rd)) else (None if 'review_date' in data else row['review_date'])
    execute("""UPDATE care_plan_items SET title=?, detail=?, category=?, owner=?, status=?, review_date=?
               WHERE id=? AND user_id=?""",
            (title[:160], str(detail or '')[:1000], category, owner, status, rd, iid, uid),
            commit=True)
    return dict(execute("SELECT * FROM care_plan_items WHERE id=? AND user_id=?", (iid, uid), fetchone=True))


def delete_item(iid) -> bool:
    from .trash import soft_delete
    return soft_delete('care_plan_items', iid)
    return True


def list_plan(include_done=True) -> dict:
    uid = current_user_id()
    rows = execute("""SELECT * FROM care_plan_items WHERE user_id=?
                      ORDER BY (status='done'), created_at DESC""", (uid,), fetchall=True) or []
    items = [dict(r) for r in rows]
    if not include_done:
        items = [i for i in items if i['status'] == 'active']
    active = [i for i in items if i['status'] == 'active']
    return {
        'items': items,
        'summary': {'total': len(items), 'active': len(active), 'done': len(items) - len(active)},
        'categories': list(CATEGORIES),
        'owners': list(OWNERS),
    }
