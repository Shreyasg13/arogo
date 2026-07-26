"""
db/account.py — full personal-data export and hard account deletion.

Two rights users are entitled to (GDPR Art. 15/17, India DPDP): download
everything we hold about them, and delete their account and all associated
data for good. Both operate strictly on the calling user's own rows.
"""
from __future__ import annotations

from .core import execute, DATA_TABLES

# User-owned tables that aren't in DATA_TABLES, with the column that owns them.
_EXTRA_OWNED = [
    ("push_subscriptions", "user_id"),
    ("caregiver_contacts", "user_id"),
    ("family_members", "user_id"),
]

# Never write live secrets into an export file — the user owns their data, not
# their raw OAuth tokens or push keys, and an export could be mishandled.
_SECRET_KEYS = {"sub_json", "access_token", "refresh_token", "password_hash", "token"}


def _redact(row: dict) -> dict:
    for k in list(row):
        if k in _SECRET_KEYS and row[k]:
            row[k] = "[redacted]"
    return row


def export_all_data(uid: str) -> dict:
    """Every row this user owns, across every table, plus account basics."""
    out = {}
    for t in DATA_TABLES:
        try:
            rows = execute(f"SELECT * FROM {t} WHERE user_id=?", (uid,), fetchall=True) or []
            out[t] = [_redact(dict(r)) for r in rows]
        except Exception:
            out[t] = []
    for t, col in _EXTRA_OWNED:
        try:
            rows = execute(f"SELECT * FROM {t} WHERE {col}=?", (uid,), fetchall=True) or []
            out[t] = [_redact(dict(r)) for r in rows]
        except Exception:
            out[t] = []
    u = execute(
        "SELECT id, email, name, created_at, verified FROM users WHERE id=?",
        (uid,), fetchone=True)
    out["account"] = dict(u) if u else {}
    return out


def delete_account(uid: str) -> None:
    """Hard-delete the account and everything associated with it.

    A group the user OWNS is removed entirely (its other members lose the shared
    group but keep all their own data); the user is also removed from any group
    they merely joined.
    """
    owned = execute("SELECT id FROM family_groups WHERE owner_id=?", (uid,), fetchall=True) or []
    for grp in owned:
        gid = grp["id"]
        for stmt in (
            "DELETE FROM family_members WHERE group_id=?",
            "DELETE FROM family_invites WHERE group_id=?",
            "DELETE FROM care_acks WHERE group_id=?",
            "DELETE FROM encouragements WHERE group_id=?",
            "DELETE FROM family_groups WHERE id=?",
        ):
            try:
                execute(stmt, (gid,), commit=True)
            except Exception:
                pass

    # References to this user in tables keyed by other columns
    for stmt, params in (
        ("DELETE FROM family_members WHERE user_id=?", (uid,)),
        ("DELETE FROM family_invites WHERE invited_by=?", (uid,)),
        ("DELETE FROM care_acks WHERE caregiver_user_id=? OR target_user_id=?", (uid, uid)),
        ("DELETE FROM encouragements WHERE to_user_id=? OR from_user_id=?", (uid, uid)),
        ("DELETE FROM push_subscriptions WHERE user_id=?", (uid,)),
        ("DELETE FROM caregiver_contacts WHERE user_id=?", (uid,)),
    ):
        try:
            execute(stmt, params, commit=True)
        except Exception:
            pass

    for t in DATA_TABLES:
        try:
            execute(f"DELETE FROM {t} WHERE user_id=?", (uid,), commit=True)
        except Exception:
            pass

    execute("DELETE FROM users WHERE id=?", (uid,), commit=True)
