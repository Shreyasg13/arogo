"""
db/nav_prefs.py — which of the app's fifty-five sections appear in your menu.

Arogo shows every feature to everyone: pregnancy, menopause, rehab, quitting
smoking, dialysis, blood donation, fasting. Someone tracking blood pressure and
two medicines scrolls past all of it, every time, and the length of the list is
itself the reason a useful section never gets found.

The obvious way to fix that is the dangerous one. This codebase has a whole
test file about features that shipped with no route to them, so hiding things
needs two guarantees, both enforced here rather than promised:

  * Essential sections cannot be hidden. Hiding the dashboard, your medicines
    or your records would leave someone with an app they cannot use and no
    obvious way back. The list is short and it is checked against the
    data-essential markers in the template, so the two cannot drift.

  * Nothing hidden becomes unreachable. Every section stays in global search
    whether or not it is in the menu — verified by a test that compares the
    sidebar against NAV_TARGETS, not by assertion. Hiding changes what you
    scroll past, never what exists.

Stored as a comma-separated list on user_profile for the same reason the
dormant dismissals are: it is one short string per user, and a table would be a
table to migrate, export, restore, search and trash.
"""
from __future__ import annotations

from .core import current_user_id, execute, new_id, now_iso

# Sections that stay in the menu whatever the user chooses. Mirrors the
# data-essential markers in templates/index.html; tests/test_nav_prefs.py fails
# if the two disagree, because a section essential in one place and hideable in
# the other is exactly how someone loses their medicines list.
ESSENTIAL = ('dashboard', 'medicines', 'reports', 'food', 'family')


def _profile_value() -> str:
    row = execute("SELECT nav_hidden FROM user_profile WHERE user_id=? LIMIT 1",
                  (current_user_id(),), fetchone=True)
    return (dict(row).get('nav_hidden') if row else '') or ''


def hidden() -> set:
    """Sections this user has taken out of the menu.

    ESSENTIAL is filtered on the way OUT as well as in. A section can become
    essential after someone has already hidden it, and the stored string should
    not be able to reach back and hide it retroactively.
    """
    raw = {k for k in (s.strip() for s in _profile_value().split(',')) if k}
    return raw - set(ESSENTIAL)


def set_hidden(keys) -> set:
    """Replace the hidden set. Returns what was actually stored.

    Essential sections are dropped rather than rejected: a client sending the
    whole checkbox state should not fail because one box cannot be unticked.
    """
    keep = sorted({str(k).strip() for k in (keys or []) if str(k).strip()}
                  - set(ESSENTIAL))
    uid = current_user_id()
    value = ','.join(keep)
    execute("UPDATE user_profile SET nav_hidden=? WHERE user_id=?",
            (value, uid), commit=True)
    if not execute("SELECT 1 AS n FROM user_profile WHERE user_id=? LIMIT 1",
                   (uid,), fetchone=True):
        # No profile row yet — a user who has never opened the profile form.
        execute("""INSERT INTO user_profile (id, user_id, nav_hidden, updated_at)
                   VALUES (?,?,?,?)""",
                (new_id(), uid, value, now_iso()), commit=True)
    return set(keep)


# ── "Hide what I don't use" ─────────────────────────────────────────────────
# What a section is FOR, so the app can tell whether this person uses it. Only
# sections with an obvious backing table are listed: a suggestion to hide
# something the app cannot check is a guess, and guessing wrong hides a section
# someone wanted.

# Keys must be sections that are actually IN the menu. Four were not — falls,
# rehab, hearing and blood donations have views but reach them from elsewhere —
# so "you have never used this, hide it" would have offered to hide four things
# that were never there. A test compares this against the sidebar.
BACKED_BY = {
    'pregnancy':     ('pregnancy', 'pregnancy_logs'),
    'menopause':     ('menopause_logs',),
    'quit':          ('quit_plans',),
    'fasting':       ('fasting_sessions',),
    'dentalvision':  ('dental_vision_visits', 'vision_prescriptions'),
    'dependents':    ('dependents', 'dependent_records'),
    'immunizations': ('immunizations',),
    'insurance':     ('insurance_policies',),
    'claims':        ('claims',),
    'procedures':    ('procedures',),
    'experiments':   ('experiments',),
    'meal-plan':     ('meal_plans',),
    'strength':      ('workout_sets',),
    'supplies':      ('home_supplies',),
    'symptomphotos': ('symptom_photos',),
    'environment':   ('environment_days',),
    'familyhistory': ('family_history',),
    'allergies':     ('allergies',),
    'taper':         ('med_taper_steps',),
}


def unused() -> list:
    """Sections whose tables this user has never written a row to.

    A suggestion, never applied on its own: the app offering to tidy the menu
    is different from the app deciding what someone needs. Someone who has not
    logged a pregnancy yet may be about to.
    """
    uid = current_user_id()
    out = []
    for view, tables in BACKED_BY.items():
        if view in ESSENTIAL:
            continue
        used = False
        for t in tables:
            try:
                r = execute(f"SELECT 1 AS n FROM {t} WHERE user_id=? LIMIT 1",
                            (uid,), fetchone=True)
                if r:
                    used = True
                    break
            except Exception:
                used = True          # cannot tell → never suggest hiding it
                break
        if not used:
            out.append(view)
    return sorted(out)


def report() -> dict:
    return {'hidden': sorted(hidden()),
            'essential': list(ESSENTIAL),
            'unused': unused()}
