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

from .core import (execute, now_iso, today_iso, user_today, new_id, current_user_id,
                   user_context, to_num, to_int)

CONSENT_FIELDS = ['share_sleep', 'share_vitals', 'share_medicines',
                  'share_food', 'share_symptoms', 'share_emergency']


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
               m.share_food, m.share_symptoms, m.share_emergency,
               m.alert_missed_doses, m.receive_care_alerts,
               u.name, u.email
        FROM family_members m JOIN users u ON u.id = m.user_id
        WHERE m.group_id=? ORDER BY m.joined_at""",
        (me['group_id'],), fetchall=True)
    out = {
        'id': group['id'], 'name': group['name'], 'owner_id': group['owner_id'],
        'my_role': me['role'],
        'my_consent': {f: bool(me[f]) for f in CONSENT_FIELDS},
        'my_alerts': bool(me['alert_missed_doses']),
        'my_receive_alerts': bool(me['receive_care_alerts']),
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
    for f in CONSENT_FIELDS + ['alert_missed_doses', 'receive_care_alerts']:
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
    out['receive_care_alerts'] = bool(me['receive_care_alerts'])
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

    if target['share_emergency']:
        e = execute("SELECT * FROM emergency_info WHERE user_id=? LIMIT 1",
                    (target_uid,), fetchone=True)
        if e:
            e = dict(e)
            out['emergency'] = {k: e.get(k) for k in (
                'blood_type', 'allergies', 'conditions', 'medications',
                'contact1_name', 'contact1_phone', 'contact2_name', 'contact2_phone')}

    return out


def _local_now_hhmm(tz):
    """Current HH:MM in `tz` (server-local fallback)."""
    import datetime as _dt
    if tz:
        try:
            import zoneinfo
            return _dt.datetime.now(zoneinfo.ZoneInfo(tz)).strftime('%H:%M')
        except Exception:
            pass
    return _dt.datetime.now().strftime('%H:%M')


def _mins_between(hhmm, now_hhmm):
    try:
        h1, m1 = map(int, hhmm.split(':'))
        h2, m2 = map(int, now_hhmm.split(':'))
        return (h2 * 60 + m2) - (h1 * 60 + m1)
    except Exception:
        return None


def care_status() -> list:
    """Today's medication status for family-group members who share their
    medicines with the caregiver (the current user). Consent-gated: only
    members with share_medicines=1 appear. A dose is 'overdue' once it is 2+
    hours past its scheduled time (matching the caregiver push alerts)."""
    me = my_membership()
    if not me:
        return []
    uid_self = current_user_id()
    today = user_today()
    members = execute("""
        SELECT m.user_id, u.name, u.email FROM family_members m
        JOIN users u ON u.id = m.user_id
        WHERE m.group_id=? AND m.user_id<>? AND m.share_medicines=1
        ORDER BY u.name""",
        (me['group_id'], uid_self), fetchall=True)
    out = []
    for mem in members:
        muid = mem['user_id']
        doses, low_stock = [], []
        try:
            with user_context(muid):
                from db import get_today_doses, get_low_stock_medicines
                from db.food import get_user_timezone
                doses = get_today_doses()
                hhmm = _local_now_hhmm(get_user_timezone())
                low_stock = [{'name': lm.get('name'), 'days_left': lm.get('days_left')}
                             for lm in get_low_stock_medicines()]
        except Exception:
            hhmm = _local_now_hhmm(None)
        total = len(doses)
        taken = len([d for d in doses if d.get('taken')])
        overdue = [{'med_name': d.get('med_name'), 'time': d.get('time')}
                   for d in doses if not d.get('taken')
                   and (_mins_between(d.get('time') or '', hhmm) or 0) >= 120]
        # Reassurance: how long since their most recent dose, so "no alert"
        # reads as "they're engaging", not ambiguous silence.
        taken_times = [d.get('time') for d in doses if d.get('taken') and d.get('time')]
        last_taken = max(taken_times) if taken_times else None
        last_ago_min = _mins_between(last_taken, hhmm) if last_taken else None
        # Coordination: has a caregiver claimed "I'll check on this" today?
        ack = execute("""SELECT caregiver_user_id, caregiver_name FROM care_acks
                         WHERE group_id=? AND target_user_id=? AND date_key=?
                         ORDER BY created_at DESC LIMIT 1""",
                      (me['group_id'], muid, today), fetchone=True)
        out.append({
            'user_id': muid,
            'name': mem['name'] or mem['email'],
            'total': total,
            'taken': taken,
            'overdue': overdue,
            'low_stock': low_stock,
            'last_taken': last_taken,
            'last_ago_min': last_ago_min,
            'checking_by': (ack['caregiver_name'] if ack else None),
            'checking_is_me': bool(ack and ack['caregiver_user_id'] == uid_self),
        })
    return out


def generate_caregiver_digest() -> dict:
    """Weekly summary of the family members the current caregiver watches
    (those who share their medicines). Adherence is the core; sleep/symptoms
    appear only if that member also shares them. For the caregiver digest email."""
    import datetime as dt
    me = my_membership()
    if not me:
        return {'has_members': False, 'members': []}
    members = execute("""
        SELECT m.user_id, u.name, u.email, m.share_sleep, m.share_symptoms
        FROM family_members m JOIN users u ON u.id = m.user_id
        WHERE m.group_id=? AND m.user_id<>? AND m.share_medicines=1
        ORDER BY u.name""",
        (me['group_id'], current_user_id()), fetchall=True)
    today = dt.date.today()
    start = (today - dt.timedelta(days=6)).isoformat()
    period_label = f"{(today - dt.timedelta(days=6)).strftime('%b')} " \
                   f"{(today - dt.timedelta(days=6)).day} – {today.strftime('%b')} {today.day}"
    out = []
    for mem in members:
        muid = mem['user_id']
        row = {'name': mem['name'] or mem['email'], 'adherence_pct': None,
               'taken': 0, 'total': 0, 'sleep_avg': None, 'symptoms': 0}
        try:
            with user_context(muid):
                from db import get_adherence_stats
                adh = get_adherence_stats(7)
                row['taken'] = adh.get('taken', 0)
                row['total'] = adh.get('total', 0)
                row['adherence_pct'] = adh.get('pct', 0) if adh.get('total') else None
                if mem['share_sleep']:
                    r = execute("SELECT AVG(duration_h) AS a FROM sleep_logs WHERE user_id=? AND date_key>=?",
                                (muid, start), fetchone=True)
                    row['sleep_avg'] = round(r['a'], 1) if r and r['a'] else None
                if mem['share_symptoms']:
                    r = execute("SELECT COUNT(*) AS n FROM symptoms WHERE user_id=? AND date_key>=?",
                                (muid, start), fetchone=True)
                    row['symptoms'] = (r['n'] if r else 0) or 0
        except Exception:
            pass
        out.append(row)
    return {'has_members': bool(out), 'members': out, 'period_label': period_label}


def send_encouragement(to_uid: str, emoji: str = '👏', message: str = '',
                       kind: str = 'kudos') -> dict:
    """A caregiver sends a member a bit of warmth — turns monitoring into
    connection. Group-scoped; you can't encourage yourself. `kind` is 'kudos'
    (one-tap cheer), 'ping' (thinking-of-you, invites a reply), or 'reply'
    (the member's "I'm okay" answer)."""
    me = my_membership()
    if not me:
        raise PermissionError('Not in a family group')
    tgt = _membership_of(to_uid)
    if not tgt or tgt['group_id'] != me['group_id']:
        raise PermissionError('Not in your family group')
    uid = current_user_id()
    if to_uid == uid:
        raise ValueError("You can't send this to yourself")
    u = execute("SELECT name, email FROM users WHERE id=?", (uid,), fetchone=True)
    from_name = (u['name'] if u else '') or (u['email'] if u else '')
    execute("""INSERT INTO encouragements
                 (id,group_id,to_user_id,from_user_id,from_name,emoji,message,kind,read,created_at)
               VALUES (?,?,?,?,?,?,?,?,0,?)""",
            (new_id(), me['group_id'], to_uid, uid, from_name,
             str(emoji or '👏')[:8], str(message or '')[:280], kind, now_iso()), commit=True)
    titles = {'kudos': f"{emoji} {from_name} cheered you on",
              'ping':  f"{emoji} {from_name} is thinking of you",
              'reply': f"{emoji} {from_name} is okay"}
    try:
        import push
        push.push_to_user(to_uid, titles.get(kind, titles['kudos']),
                          message or 'Keep up the great work!', '/')
    except Exception:
        pass
    return {'ok': True}


def reply_okay(enc_id: str) -> dict:
    """The member answers a 'thinking of you' ping with "I'm okay", which pings
    the original sender back. Only the ping's recipient may answer."""
    uid = current_user_id()
    enc = execute("SELECT * FROM encouragements WHERE id=? AND to_user_id=?",
                  (enc_id, uid), fetchone=True)
    if not enc:
        raise PermissionError('Not your message')
    execute("UPDATE encouragements SET read=1 WHERE id=?", (enc_id,), commit=True)
    # Ping the original sender back with an "I'm okay"
    return send_encouragement(enc['from_user_id'], '💛', "I'm okay, thanks for thinking of me",
                              kind='reply')


def get_my_encouragements(unread_only: bool = True) -> list:
    uid = current_user_id()
    q = ("SELECT id, from_name, from_user_id, emoji, message, kind, read, created_at "
         "FROM encouragements WHERE to_user_id=?")
    if unread_only:
        q += " AND read=0"
    q += " ORDER BY created_at DESC LIMIT 20"
    return [dict(r) for r in execute(q, (uid,), fetchall=True)]


def mark_encouragements_read():
    execute("UPDATE encouragements SET read=1 WHERE to_user_id=? AND read=0",
            (current_user_id(),), commit=True)


def ack_care(target_uid: str) -> dict:
    """Record that the current caregiver is checking on `target_uid` today, so
    co-caregivers don't all pile on. One ack per caregiver per member per day."""
    me = my_membership()
    if not me:
        raise PermissionError('Not in a family group')
    tgt = _membership_of(target_uid)
    if not tgt or tgt['group_id'] != me['group_id']:
        raise PermissionError('Not in your family group')
    uid = current_user_id()
    existing = execute("""SELECT id FROM care_acks WHERE group_id=? AND target_user_id=?
                          AND caregiver_user_id=? AND date_key=?""",
                       (me['group_id'], target_uid, uid, today_iso()), fetchone=True)
    if not existing:
        u = execute("SELECT name, email FROM users WHERE id=?", (uid,), fetchone=True)
        name = (u['name'] if u else '') or (u['email'] if u else '')
        execute("""INSERT INTO care_acks
                     (id,group_id,target_user_id,caregiver_user_id,caregiver_name,date_key,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (new_id(), me['group_id'], target_uid, uid, name, today_iso(), now_iso()),
                commit=True)
    return {'ok': True, 'checking_by': None}
