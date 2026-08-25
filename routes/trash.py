"""
routes/trash.py — recover a deleted health record.

GET    /api/trash[?q=]         — what's recoverable, and how long is left
POST   /api/trash/<id>/restore — put one back
DELETE /api/trash/<id>         — delete it for good, now
DELETE /api/trash              — empty the trash

Every delete in this app used to be permanent. Some of that data cannot be
recreated — a lab value from three years ago exists on a piece of paper you no
longer have — so a delete now moves the row aside for thirty days instead.
"""
from flask import Blueprint, request, jsonify

from auth import require_auth

bp = Blueprint('trash', __name__)


@bp.route('/api/trash')
@require_auth
def api_list():
    from db.trash import list_trash, RETENTION_DAYS
    items = list_trash(request.args.get('q', ''))
    return jsonify({'items': items, 'retention_days': RETENTION_DAYS})


@bp.route('/api/trash/<item_id>/restore', methods=['POST'])
@require_auth
def api_restore(item_id):
    from db.trash import restore
    res = restore(item_id)
    return (jsonify(res), 200) if res.get('ok') else (jsonify(res), 400)


@bp.route('/api/trash/<item_id>', methods=['DELETE'])
@require_auth
def api_purge(item_id):
    from db.trash import purge
    return jsonify({'success': purge(item_id)})


@bp.route('/api/trash', methods=['DELETE'])
@require_auth
def api_empty():
    """Immediate and real, files included. A trash that doesn't actually empty
    is a second copy of everything the user asked you to destroy."""
    from db.trash import empty_trash
    return jsonify({'success': True, 'removed': empty_trash()})
