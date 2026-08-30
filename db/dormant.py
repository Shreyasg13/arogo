"""
db/dormant.py — capability your own data has already earned, still switched off.

Twenty-five blood-pressure readings and no target range set, so nothing in the
app can say whether a single one of them is in range. Twenty-three medicines
and no pill counts, so the run-out forecast has nothing to forecast from. The
features exist, the data exists, and nothing connects the two — the app simply
waits, silently, for a setup step nobody knows is missing.

This is NOT onboarding and NOT a completion score:

  * Nothing appears until the data earns it. A user who has never logged a
    vital is never asked to set a vital target — that would be a nag about a
    feature they have not chosen to use. `earned` is always a fact about what
    they have already done.

  * It never says how often to log. Same rule as db/data_trust.py: report what
    is true, let the person weigh it. There is no "streak", no percentage, and
    no "you should".

  * Each entry names what switching it on would give them, in terms of their
    own numbers — not the feature's name. "Nothing can tell you whether your
    25 blood-pressure readings are in range" is the point; "set up targets" is
    not.

  * It can be dismissed, permanently and per item. Someone who does not want
    target ranges has answered the question, and asking again forever is how a
    helpful list turns into a chore.

Adding a check means adding one CHECKS entry. tests/test_dormant.py fails the
build if an entry lacks any of its fields, or if `earned` and `on` are not both
real queries.
"""
from __future__ import annotations

from .core import current_user_id, execute, new_id, now_iso


def _count(sql, *args) -> int:
    uid = current_user_id()
    row = execute(sql, (uid, *args), fetchone=True)
    return (dict(row).get('n') or 0) if row else 0


# ── The individual checks ───────────────────────────────────────────────────
# Each returns (earned, detail) for `earned` and a bool for `on`. `detail`
# carries the numbers that make the sentence specific — the client formats it,
# so the strings stay in one place with the rest of the UI.

def _vital_targets_earned():
    """A vital type with enough readings to be worth banding, and no band."""
    from .vital_targets import VITAL_TYPES
    uid = current_user_id()
    rows = execute("""SELECT type, COUNT(*) AS n FROM vitals
                      WHERE user_id=? GROUP BY type ORDER BY n DESC""",
                   (uid,), fetchall=True) or []
    have = {r['vtype'] for r in (execute(
        "SELECT vtype FROM vital_targets WHERE user_id=?", (uid,), fetchall=True) or [])}
    for r in rows:
        if r['type'] in VITAL_TYPES and r['type'] not in have and (r['n'] or 0) >= 5:
            return True, {'count': r['n'], 'vital': r['type']}
    return False, {}


def _vital_targets_on():
    return _count("SELECT COUNT(*) AS n FROM vital_targets WHERE user_id=?") > 0


def _pill_counts_earned():
    n = _count("""SELECT COUNT(*) AS n FROM medicines
                  WHERE user_id=? AND active=1
                    AND (pill_count IS NULL OR pill_count=0)""")
    return (n > 0), {'count': n}


def _pill_counts_on():
    return _count("""SELECT COUNT(*) AS n FROM medicines
                     WHERE user_id=? AND active=1 AND pill_count>0""") > 0


def _prescriptions_earned():
    n = _count("SELECT COUNT(*) AS n FROM medicines WHERE user_id=? AND active=1")
    return (n >= 2), {'count': n}


def _prescriptions_on():
    return _count("SELECT COUNT(*) AS n FROM prescriptions WHERE user_id=?") > 0


def _lab_recheck_earned():
    n = _count("SELECT COUNT(*) AS n FROM lab_results WHERE user_id=?")
    return (n > 0), {'count': n}


def _lab_recheck_on():
    return _count("SELECT COUNT(*) AS n FROM lab_rechecks WHERE user_id=?") > 0


def _med_purpose_earned():
    n = _count("""SELECT COUNT(*) AS n FROM medicines
                  WHERE user_id=? AND active=1
                    AND (purpose IS NULL OR TRIM(purpose)='')""")
    return (n >= 2), {'count': n}


def _med_purpose_on():
    return _count("""SELECT COUNT(*) AS n FROM medicines
                     WHERE user_id=? AND active=1
                       AND purpose IS NOT NULL AND TRIM(purpose)!=''""") > 0


def _push_earned():
    """Scheduled doses but no device signed up for reminders.

    Only for medicines with actual times — an as-needed medicine has nothing to
    remind you about, and offering reminders for it would be noise.
    """
    n = _count("""SELECT COUNT(*) AS n FROM medicines
                  WHERE user_id=? AND active=1
                    AND times IS NOT NULL AND times NOT IN ('', '[]')""")
    return (n > 0), {'count': n}


def _push_on():
    return _count("SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id=?") > 0


# ── The registry ────────────────────────────────────────────────────────────
# `unlocks` is the sentence that matters: what the person's own data would do
# that it currently cannot. `step` is the single action, and `view` is where.

CHECKS = [
    {
        'key': 'vital_targets',
        'name': 'Target ranges for your vitals',
        'earned': _vital_targets_earned, 'on': _vital_targets_on,
        'unlocks': 'Nothing can currently tell you whether any of your %1 '
                   'readings are inside the range your doctor wants. A target '
                   'turns every past and future reading into in-range or not.',
        'step': 'Set a target range',
        # Vitals live under Body & Vitals; there is no view-vitals. Caught by
        # the test that checks every destination is a view that exists —
        # sending someone to a blank page is worse than not offering at all.
        'view': 'body',
    },
    {
        'key': 'pill_counts',
        'name': 'How many pills you have left',
        'earned': _pill_counts_earned, 'on': _pill_counts_on,
        'unlocks': '%1 of your medicines have no pill count, so the app cannot '
                   'work out when any of them runs out or warn you before it '
                   'does. The refill list stays empty until it knows.',
        'step': 'Add a pill count',
        'view': 'medicines',
    },
    {
        'key': 'med_purpose',
        'name': 'What each medicine is for',
        'earned': _med_purpose_earned, 'on': _med_purpose_on,
        'unlocks': '%1 of your medicines have no purpose recorded. It is the '
                   'first thing a new doctor asks, it is what groups a '
                   'medicine under a condition, and it is what a symptom is '
                   'compared against.',
        'step': 'Add a purpose',
        'view': 'medicines',
    },
    {
        'key': 'push',
        'name': 'Reminders that reach you with the app closed',
        'earned': _push_earned, 'on': _push_on,
        'unlocks': 'You have %1 medicines with set times, but no device is '
                   'signed up for reminders — so a dose time passes with '
                   'nothing to notice it unless the app is already open.',
        'step': 'Turn on reminders',
        'view': 'reminders',
    },
    {
        'key': 'prescriptions',
        'name': 'Prescriptions behind your medicines',
        'earned': _prescriptions_earned, 'on': _prescriptions_on,
        'unlocks': 'Your %1 medicines are not linked to a prescription, so '
                   'nothing tracks a renewal date or how many refills are '
                   'left — the two things that run out without warning.',
        'step': 'Record a prescription',
        'view': 'prescriptions',
    },
    {
        'key': 'lab_recheck',
        'name': 'A reminder to repeat a lab test',
        'earned': _lab_recheck_earned, 'on': _lab_recheck_on,
        'unlocks': 'You have %1 lab results and no recheck set. A test worth '
                   'doing once is usually worth repeating, and the date is the '
                   'part everyone forgets.',
        'step': 'Set a recheck',
        'view': 'labs',
    },
]


# ── Dismissal ───────────────────────────────────────────────────────────────
# A comma-separated list on user_profile rather than a table of its own: one
# short string per user, where a table would be a table to migrate, export,
# restore, search and trash. NOT app_config — that is global, and one person
# dismissing a suggestion must not silence it for everyone on the server.

def _dismissed() -> set:
    row = execute("SELECT dormant_dismissed FROM user_profile WHERE user_id=? LIMIT 1",
                  (current_user_id(),), fetchone=True)
    raw = (dict(row).get('dormant_dismissed') if row else '') or ''
    return {k for k in (s.strip() for s in raw.split(',')) if k}


def _save_dismissed(keys) -> None:
    uid = current_user_id()
    value = ','.join(sorted(keys))
    n = execute("UPDATE user_profile SET dormant_dismissed=? WHERE user_id=?",
                (value, uid), commit=True)
    # A user who has never opened the profile form has no row yet, and an
    # UPDATE that matches nothing would silently drop the dismissal.
    if not execute("SELECT 1 AS n FROM user_profile WHERE user_id=? LIMIT 1",
                   (uid,), fetchone=True):
        execute("""INSERT INTO user_profile (id, user_id, dormant_dismissed, updated_at)
                   VALUES (?,?,?,?)""",
                (new_id(), uid, value, now_iso()), commit=True)
    return n


def dismiss(key: str) -> bool:
    if key not in {c['key'] for c in CHECKS}:
        return False
    _save_dismissed(_dismissed() | {key})
    return True


def restore(key: str) -> bool:
    _save_dismissed(_dismissed() - {key})
    return True


def report(include_dismissed: bool = False) -> dict:
    """What this person's data would light up that is currently off.

    A check that raises is skipped rather than fatal: one bad query should not
    take the panel down, and the panel is advisory in the first place.
    """
    dismissed = _dismissed()
    items, hidden = [], 0
    for c in CHECKS:
        try:
            if c['on']():
                continue                       # already switched on
            earned, detail = c['earned']()
            if not earned:
                continue                       # the data has not asked for it
        except Exception:
            continue
        if c['key'] in dismissed and not include_dismissed:
            hidden += 1
            continue
        items.append({
            'key': c['key'], 'name': c['name'], 'unlocks': c['unlocks'],
            'step': c['step'], 'view': c['view'], 'detail': detail,
            'dismissed': c['key'] in dismissed,
        })
    return {'items': items, 'dismissed_count': hidden, 'total': len(CHECKS)}
