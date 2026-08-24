"""
routes/storage.py — what this install is using on disk.

GET    /api/storage            — usage, orphaned files, free space
DELETE /api/storage/orphans    — remove files no row points at

Arogo self-hosts on a Pi, so uploads live on an SD card with a hard limit and
nobody watching it. When it fills, SQLite writes start failing — which in this
app means a logged dose quietly not saving, with the person holding the pill in
their hand none the wiser. This is the one place that says how much room is left.
"""
from flask import Blueprint, jsonify

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
