"""
routes/storage.py — what this install is using on disk.

GET    /api/storage            — usage, orphaned files, free space
DELETE /api/storage/orphans    — remove files no row points at
GET    /api/storage/integrity  — child rows whose parent is gone
POST   /api/storage/integrity  — remove them (recoverable ones are left alone)
GET    /api/server/readiness   — what this install is and is not configured for

Arogo self-hosts on a Pi, so uploads live on an SD card with a hard limit and
nobody watching it. When it fills, SQLite writes start failing — which in this
app means a logged dose quietly not saving, with the person holding the pill in
their hand none the wiser. This is the one place that says how much room is left.
"""
from flask import Blueprint, jsonify, request, g

from auth import require_auth

bp = Blueprint('storage', __name__)


@bp.route('/api/storage')
@require_auth
def api_storage():
    from db.storage import storage_report
    return jsonify(storage_report())


@bp.route('/api/storage/orphans', methods=['DELETE'])
@require_auth
def api_delete_orphans():
    """Delete files that no row anywhere points at.

    These are the residue of account deletions and restores from before file
    cleanup existed. An orphan is by definition a file the app can no longer
    identify — it cannot tell you whose it was or what it showed — so this is
    never automatic. It runs when a person asks for it, and reports exactly what
    it removed.
    """
    from db.storage import find_orphans, delete_files
    orphans = find_orphans()
    freed = sum(o['bytes'] for o in orphans)
    removed = delete_files(o['name'] for o in orphans)
    return jsonify({'success': True, 'removed': removed,
                    'bytes_freed': freed if removed == len(orphans) else None})


# ── Referential drift ───────────────────────────────────────────────────────
# Files are not the only thing that gets stranded. A medicine purged from the
# trash used to leave its dose logs behind for good, and the weekly adherence
# insight counted every one of them.

@bp.route('/api/storage/integrity')
@require_auth
def api_integrity():
    """Child rows whose parent no longer exists.

    Rows whose parent is merely sitting in the trash are NOT reported: those
    come back on restore, and calling them drift would train people to repair
    something that is working correctly.
    """
    from db.integrity import find_orphans, orphans_in_trash
    orphans = find_orphans(g.user_id)
    return jsonify({
        'orphans': orphans,
        'total': sum(o['count'] for o in orphans),
        'recoverable_parents_in_trash': len(orphans_in_trash(g.user_id)),
        'note': 'These belong to records that were deleted for good. Removing '
                'them changes no number you can still act on — it stops them '
                'counting toward adherence for medicines you no longer have.',
    })


@bp.route('/api/storage/integrity', methods=['POST'])
@require_auth
def api_repair_integrity():
    """Remove the stranded rows. Anything recoverable is deliberately skipped."""
    from db.integrity import repair_orphans
    dry = bool((request.json or {}).get('dry_run')) if request.is_json else False
    return jsonify({'success': True, **repair_orphans(g.user_id, dry_run=dry)})


# ── Is this server set up properly? ─────────────────────────────────────────
# Arogo self-hosts, so the person running it is also the person who has to
# notice it is half-configured — and nothing said so. Verification emails have
# printed to stderr since the first commit, with "check your inbox" on screen.

@bp.route('/api/server/readiness')
@require_auth
def api_readiness():
    """What this install can and cannot actually do.

    Behind require_auth because it names hosts, paths and library versions —
    a precise map of the server, and free reconnaissance if it were public. It
    deliberately reports settings only: no secret, key or password is returned,
    only whether one is present and whether it is still the shipped default.
    """
    from db.readiness import report
    return jsonify(report())
