"""
db/family.py — Family sharing with per-category consent (Phase 3).

Model:
  - A user belongs to at most one family group (as owner or member).
  - Every member row carries five consent flags (sleep/vitals/medicines/
    food/symptoms). A member's data is visible to the rest of the group
    ONLY for categories they have switched on — default is share nothing.
  - Invites are by email, marked accepted/revoked in family_invites; the
    emailed link carries a signed 72h token (see auth.make_family_invite_token).
"""
from __future__ import annotations

from .core import execute, now_iso, today_iso, new_id, current_user_id, to_num, to_int

CONSENT_FIELDS = ['share_sleep', 'share_vitals', 'share_medicines',
                  'share_food', 'share_symptoms']


# ── Membership lookups ────────────────────────────────────────────────────────

def my_membership() -> dict | None:
    return execute("SELECT * FROM family_members WHERE user_id=?",
                   (current_user_id(),), fetchone=True)


def _membership_of(uid: str) -> dict | None:
    return execute("SELECT * FROM family_members WHERE user_id=?",
                   (uid,), fetchone=True)


# ── Group lifecycle ───────────────────────────────────────────────────────────

def create_group(name: str) -> dict:
    uid = current_user_id()
    if my_membership():
        raise ValueError('You are already in a family group')
    gid = new_id()
    execute("INSERT INTO family_groups (id,name,owner_id,created_at) VALUES (?,?,?,?)",
            (gid, name or 'My Family', uid, now_iso()), commit=True)
    execute("""INSERT INTO family_members (id,group_id,user_id,role,joined_at)
               VALUES (?,?,?,'owner',?)""",
            (new_id(), gid, uid, now_iso()), commit=True)
    return get_my_group()


def get_my_group() -> dict | None:
    """Group overview: members (with consent flags), own role, pending invites (owner only)."""
    me = my_membership()
    if not me:
        return None
    group = execute("SELECT * FROM family_groups WHERE id=?", (me['group_id'],), fetchone=True)
    if not group:
        return None
    members = execute("""
        SELECT m.user_id, m.role, m.joined_at,
               m.share_sleep, m.share_vitals, m.share_medicines,
               m.share_food, m.share_symptoms, m.alert_missed_doses,
               u.name, u.email
        FROM family_members m JOIN users u ON u.id = m.user_id
        WHERE m.group_id=? ORDER BY m.joined_at""",
        (me['group_id'],), fetchall=True)
    out = {
        'id': group['id'], 'name': group['name'], 'owner_id': group['owner_id'],
        'my_role': me['role'],
        'my_consent': {f: bool(me[f]) for f in CONSENT_FIELDS},
        'my_alerts': bool(me['alert_missed_doses']),
        'members': [{
            'user_id': m['user_id'], 'name': m['name'], 'email': m['email'],
            'role': m['role'], 'joined_at': m['joined_at'],
            'shares': {f: bool(m[f]) for f in CONSENT_FIELDS},
            'alerts_on': bool(m['alert_missed_doses']),
        } for m in members],
    }
    if me['role'] == 'owner':
        out['pending_invites'] = execute(
            "SELECT id, email, created_at FROM family_invites WHERE group_id=? AND status='pending' ORDER BY created_at",
            (me['group_id'],), fetchall=True)
    return out


def leave_group():
    me = my_membership()
    if not me:
        raise ValueError('You are not in a family group')
    if me['role'] == 'owner':
        raise ValueError('The owner cannot leave. Remove all members first, then delete the group.')
    execute("DELETE FROM family_members WHERE id=?", (me['id'],), commit=True)


def remove_member(target_uid: str):
    me = my_membership()
    if not me or me['role'] != 'owner':
        raise ValueError('Only the group owner can remove members')
    if target_uid == current_user_id():
        raise ValueError('Use delete group instead of removing yourself')
    execute("DELETE FROM family_members WHERE group_id=? AND user_id=?",
            (me['group_id'], target_uid), commit=True)


def delete_group():
    """Owner only; group must have no other members."""
    me = my_membership()
    if not me or me['role'] != 'owner':
        raise ValueError('Only the group owner can delete the group')
    others = execute("SELECT COUNT(*) AS n FROM family_members WHERE group_id=? AND user_id<>?",
                     (me['group_id'], current_user_id()), fetchone=True)
    if others and others['n']:
        raise ValueError('Remove all members before deleting the group')
    execute("DELETE FROM family_invites WHERE group_id=?", (me['group_id'],), commit=True)
    execute("DELETE FROM family_members WHERE group_id=?", (me['group_id'],), commit=True)
    execute("DELETE FROM family_groups  WHERE id=?",       (me['group_id'],), commit=True)


# ── Invites ───────────────────────────────────────────────────────────────────

def create_invite(email: str) -> dict:
    me = my_membership()
    if not me or me['role'] != 'owner':
        raise ValueError('Only the group owner can send invites')
    email = email.strip().lower()

    invitee = execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True)
    if invitee and _membership_of(invitee['id']):
        raise ValueError('That person is already in a family group')
    dup = execute("SELECT id FROM family_invites WHERE group_id=? AND email=? AND status='pending'",
                  (me['group_id'], email), fetchone=True)
    if dup:
        raise ValueError('An invite for that email is already pending')

    iid = new_id()
    execute("""INSERT INTO family_invites (id,group_id,email,invited_by,status,created_at)
               VALUES (?,?,?,?,'pending',?)""",
            (iid, me['group_id'], email, current_user_id(), now_iso()), commit=True)
    return {'id': iid, 'email': email}


def revoke_invite(invite_id: str):
    me = my_membership()
    if not me or me['role'] != 'owner':
        raise ValueError('Only the group owner can revoke invites')
    execute("UPDATE family_invites SET status='revoked' WHERE id=? AND group_id=? AND status='pending'",
            (invite_id, me['group_id']), commit=True)


def accept_invite(invite_id: str) -> dict:
    """Called by the logged-in invitee after their token was verified."""
    uid = current_user_id()
    inv = execute("SELECT * FROM family_invites WHERE id=?", (invite_id,), fetchone=True)
    if not inv or inv['status'] != 'pending':
        raise ValueError('This invite is no longer valid')

    user = execute("SELECT email FROM users WHERE id=?", (uid,), fetchone=True)
    if not user or user['email'].lower() != inv['email'].lower():
        raise ValueError('This invite was sent to a different email address')
    if my_membership():
        raise ValueError('You are already in a family group')

    execute("""INSERT INTO family_members (id,group_id,user_id,role,joined_at)
               VALUES (?,?,?,'member',?)""",
            (new_id(), inv['group_id'], uid, now_iso()), commit=True)
    execute("UPDATE family_invites SET status='accepted' WHERE id=?", (invite_id,), commit=True)
    return get_my_group()


# ── Consent ───────────────────────────────────────────────────────────────────

def update_consent(flags: dict) -> dict:
    me = my_membership()
    if not me:
        raise ValueError('You are not in a family group')

    # Caregiver alerts only make sense while medicines are shared
    if flags.get('alert_missed_doses'):
        sharing_meds = flags.get('share_medicines', bool(me['share_medicines']))
        if not sharing_meds:
            raise ValueError('Turn on medicine sharing first — alerts tell your '
                             'family about missed doses')

    sets, params = [], []
    for f in CONSENT_FIELDS + ['alert_missed_doses']:
        if f in flags:
            sets.append(f"{f}=?")
            params.append(1 if flags[f] else 0)
    # Withdrawing medicine sharing also silences the alerts
    if flags.get('share_medicines') is False and 'alert_missed_doses' not in flags:
        sets.append("alert_missed_doses=0")
    if sets:
        params.append(me['id'])
        execute(f"UPDATE family_members SET {', '.join(sets)} WHERE id=?",
                tuple(params), commit=True)
    me = my_membership()
    out = {f: bool(me[f]) for f in CONSENT_FIELDS}
    out['alert_missed_doses'] = bool(me['alert_missed_doses'])
    return out


# ── Shared data (consent-gated) ───────────────────────────────────────────────

def member_summary(target_uid: str) -> dict:
    """Compact health summary of a fellow group member.

    The requester must be in the same group; each category appears only
    if the TARGET member has consented to share it.
    """
    import datetime as dt
    me = my_membership()
    target = _membership_of(target_uid)
    if not me or not target or me['group_id'] != target['group_id']:
        raise PermissionError('Not in your family group')

    user = execute("SELECT id, name, email FROM users WHERE id=?", (target_uid,), fetchone=True)
    if not user:
        # Membership row outlived the user account (deleted user)
        raise PermissionError('Member not found')
    prof = execute("SELECT timezone FROM user_profile WHERE user_id=?", (target_uid,), fetchone=True)
    today = today_iso(prof['timezone'] if prof else None)
    week_ago = (dt.date.fromisoformat(today) - dt.timedelta(days=6)).isoformat()

    out = {
        'user': {'id': user['id'], 'name': user['name'], 'email': user['email']},
        'shares': {f: bool(target[f]) for f in CONSENT_FIELDS},
    }

    if target['share_sleep']:
        rows = execute("""SELECT date_key, duration_h, quality FROM sleep_logs
                          WHERE user_id=? AND date_key>=? ORDER BY date_key""",
                       (target_uid, week_ago), fetchall=True)
        out['sleep'] = {
            'nights': len(rows),
            'avg_hours': round(sum(to_num(r['duration_h'], 0) for r in rows)/len(rows), 1) if rows else None,
            'daily': rows,
        }

    if target['share_vitals']:
        latest = {}
        for vtype in ['blood_pressure', 'blood_sugar', 'heart_rate', 'temperature', 'spo2']:
            r = execute("""SELECT type, value1, value2, unit, date_key FROM vitals
                           WHERE user_id=? AND type=? ORDER BY logged_at DESC LIMIT 1""",
                        (target_uid, vtype), fetchone=True)
            if r:
                latest[vtype] = r
        out['vitals'] = latest

    if target['share_medicines']:
        meds = execute("""SELECT id, name, dosage, unit, frequency FROM medicines
                          WHERE user_id=? AND active=1 ORDER BY name""",
                       (target_uid,), fetchall=True)
        doses = execute("""SELECT COUNT(*) AS total,
                                  SUM(CASE WHEN taken=1 THEN 1 ELSE 0 END) AS taken
                           FROM dose_logs WHERE user_id=? AND date_key=?""",
                        (target_uid, today), fetchone=True)
        out['medicines'] = {
            'active': meds,
            'today': {'total': doses['total'] or 0, 'taken': doses['taken'] or 0},
        }

    if target['share_food']:
        food = execute("""SELECT COUNT(*) AS logs, COALESCE(SUM(calories),0) AS calories
                          FROM food_logs WHERE user_id=? AND date_key=?""",
                       (target_uid, today), fetchone=True)
        out['food'] = {'today_calories': round(food['calories'] or 0),
                       'today_logs': food['logs'] or 0}

    if target['share_symptoms']:
        rows = execute("""SELECT name, severity, date_key FROM symptoms
                          WHERE user_id=? AND date_key>=? ORDER BY date_key DESC LIMIT 20""",
                       (target_uid, week_ago), fetchall=True)
        out['symptoms'] = rows

    return out
