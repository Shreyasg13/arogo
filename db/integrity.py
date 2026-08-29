"""What happens to a child row when its parent goes away.

Deleting a medicine does not delete the doses you logged for it. That is
deliberate and correct — soft_delete lifts the medicine row out into the trash,
and a restore puts it back with the same id, so the history reunites. Losing a
month of dose history to a mis-tap would be far worse than the alternative.

The alternative, though, was never decided. Once a trashed medicine is purged —
by hand, or by the thirty-day expiry — its dose logs stay behind forever,
pointing at an id that will never exist again. On this install 42% of one
account's dose logs were in that state, and the weekly adherence insight counted
every one of them: "Only 55% of doses taken this week" was partly about
medicines that had been gone for months.

So there are two questions, and this module answers both explicitly rather than
by accident.

  When a parent is destroyed for good, what happens to its children? Answered
  per relation below, with a reason. Nothing is left to whichever DELETE
  happened to run.

  Which numbers may count a row whose parent is currently missing? A dose log
  whose medicine sits in the trash is recoverable, not deleted — but it should
  not drag down "how am I doing on my medicines", because the user has said they
  are not on that medicine any more. Aggregates exclude orphans; the raw history
  keeps them.

The registry is the point. Every child-to-parent reference in the schema must
appear here with a policy, and a conventions test fails the build if one does
not — the same shape the search, trash and export registries use, for the same
reason: the failure being prevented is silence.
"""
from __future__ import annotations

from .core import execute, table_columns

# policy is one of:
#   'cascade' — destroying the parent for good destroys these too.
#   'keep'    — the row outlives its parent on purpose. Needs a real reason.
DEPENDENTS = [
    # (child_table, fk_column, parent_table, policy, reason)
    ('dose_logs', 'medicine_id', 'medicines', 'cascade',
     'A dose log is a record of taking THAT medicine. Once the medicine is gone '
     'for good the log can never be reunited with it, and it goes on counting '
     'toward adherence for something the user no longer takes.'),
    ('medicine_events', 'medicine_id', 'medicines', 'cascade',
     'The started/stopped/edited trail for a medicine that no longer exists. '
     'Reconciliation reads this to answer "what changed" — a purged medicine '
     'should not still be reporting changes.'),
    ('med_taper_steps', 'medicine_id', 'medicines', 'cascade',
     'A taper schedule is meaningless without the medicine it steps down.'),
    ('med_effectiveness', 'medicine_id', 'medicines', 'cascade',
     'A 1-5 rating of how well a medicine is working, for a medicine that is '
     'gone.'),
    ('injection_logs', 'medicine_id', 'medicines', 'cascade',
     'Injection-site rotation is per medicine; without it the sites belong to '
     'nothing.'),
    ('habit_logs', 'habit_id', 'habits', 'cascade',
     'A tick against a habit that no longer exists cannot be shown anywhere, '
     'and inflates streak and consistency counts.'),
    ('rehab_logs', 'plan_id', 'rehab_plans', 'cascade',
     'A completed session belongs to one plan; adherence is done-over-scheduled '
     'for that plan.'),
    ('pregnancy_logs', 'pregnancy_id', 'pregnancy', 'cascade',
     'Weekly weights and kick counts belong to one pregnancy record. Kept '
     'without it they are numbers with no week to attach to, in the most '
     'private area the app has.'),
    ('dependent_records', 'dependent_id', 'dependents', 'cascade',
     'Vaccines, medicines and notes kept for one person. Removing the person '
     'and keeping their medical records would be the worst of both.'),
    ('visit_action_items', 'appointment_id', 'appointments', 'cascade',
     'Actions that came out of one visit — "book the scan", "start the new '
     'dose". Unlike a question, which is written before and survives a '
     'rescheduled visit, these only mean anything attached to the visit that '
     'produced them.'),

    # Deliberately kept.
    ('doctor_questions', 'appointment_id', 'appointments', 'keep',
     'A question survives the appointment it was pinned to: people write down '
     'what to ask, the visit gets cancelled or rebooked, and the question still '
     'matters. The visit pack already treats an unattached question as one that '
     'is still to be asked.'),
    ('appointments', 'provider_id', 'providers', 'keep',
     'An appointment that happened, happened. Deleting a doctor from your care '
     'team must not erase the visits you made — the appointment simply stops '
     'naming a provider.'),
]

_BY_PARENT = {}
for _c, _fk, _p, _pol, _why in DEPENDENTS:
    _BY_PARENT.setdefault(_p, []).append((_c, _fk, _pol))


def cascading_children(parent_table: str):
    """(child_table, fk_column) pairs that follow this parent to the grave."""
    return [(c, fk) for c, fk, pol in _BY_PARENT.get(parent_table, [])
            if pol == 'cascade']


def purge_children(parent_table: str, parent_id: str, uid: str) -> int:
    """Destroy the children of a parent that is being destroyed for good.

    Called from the trash's purge and expiry paths — never from soft_delete,
    where the parent is recoverable and the children must stay put so a restore
    reunites them.
    """
    removed = 0
    for child, fk in cascading_children(parent_table):
        try:
            if fk not in table_columns(child):
                continue                 # column not on this schema version
            n = execute(f"SELECT COUNT(*) AS n FROM {child} WHERE {fk}=? AND user_id=?",
                        (parent_id, uid), fetchone=True)
            execute(f"DELETE FROM {child} WHERE {fk}=? AND user_id=?",
                    (parent_id, uid), commit=True)
            removed += (n or {}).get('n', 0) or 0
        except Exception:
            # Housekeeping must never break the delete the user asked for.
            continue
    return removed


# ── Reporting and repair ────────────────────────────────────────────────────

def find_orphans(uid: str = None) -> list:
    """Child rows whose parent is missing, per relation.

    Counts only cascade relations: a kept relation being parentless is the
    designed behaviour, not drift, and reporting it as a problem would train
    people to ignore the report.
    """
    out = []
    for child, fk, parent, policy, _why in DEPENDENTS:
        if policy != 'cascade':
            continue
        try:
            if fk not in table_columns(child):
                continue
            where = "c.user_id=?" if uid else "1=1"
            args = (uid,) if uid else ()
            row = execute(
                f"""SELECT COUNT(*) AS n FROM {child} c
                    WHERE {where} AND c.{fk} IS NOT NULL AND c.{fk} <> ''
                      AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = c.{fk})""",
                args, fetchone=True)
            n = (row or {}).get('n', 0) or 0
            if n:
                out.append({'child': child, 'column': fk, 'parent': parent,
                            'count': n})
        except Exception:
            continue
    return out


def orphans_in_trash(uid: str) -> set:
    """Parent ids that are only missing because they are sitting in the trash.

    These are not drift — they come back on restore — so a repair must leave
    them alone or it would quietly destroy the history of a medicine the user
    is about to restore.
    """
    rows = execute("SELECT row_id FROM deleted_items WHERE user_id=?", (uid,),
                   fetchall=True) or []
    return {r['row_id'] for r in rows}


def repair_orphans(uid: str, dry_run: bool = True) -> dict:
    """Remove child rows whose parent is gone for good.

    Skips anything whose parent is in the trash: those are recoverable, and
    deleting them would turn a reversible mistake into an irreversible one.
    """
    recoverable = orphans_in_trash(uid)
    removed, plan = 0, []
    for child, fk, parent, policy, _why in DEPENDENTS:
        if policy != 'cascade':
            continue
        try:
            if fk not in table_columns(child):
                continue
            rows = execute(
                f"""SELECT c.id, c.{fk} AS parent_id FROM {child} c
                    WHERE c.user_id=? AND c.{fk} IS NOT NULL AND c.{fk} <> ''
                      AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = c.{fk})""",
                (uid,), fetchall=True) or []
            doomed = [r['id'] for r in rows if r['parent_id'] not in recoverable]
            if not doomed:
                continue
            plan.append({'child': child, 'parent': parent, 'count': len(doomed)})
            if not dry_run:
                for rid in doomed:
                    execute(f"DELETE FROM {child} WHERE id=? AND user_id=?",
                            (rid, uid), commit=True)
            removed += len(doomed)
        except Exception:
            continue
    return {'removed': removed, 'relations': plan, 'dry_run': dry_run,
            'kept_because_recoverable': len(recoverable)}


# ── The SQL fragment aggregates use ─────────────────────────────────────────

def not_orphaned(child_alias: str, fk: str, parent: str) -> str:
    """A WHERE clause fragment excluding rows whose parent is missing.

    Used by the aggregates that answer "how am I doing" — adherence, streaks,
    weekly counts. A dose logged for a medicine now sitting in the trash is real
    history, and it is not part of how the user is doing on the medicines they
    are actually taking.
    """
    return (f"EXISTS (SELECT 1 FROM {parent} _p WHERE _p.id = {child_alias}.{fk})")
