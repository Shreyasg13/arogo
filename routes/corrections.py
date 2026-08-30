"""
routes/corrections.py — correcting an entry, and the setup it never had.

PATCH  /api/entries/<table>/<row_id>       — apply a correction
GET    /api/entries/<table>/fields         — what the correction form offers
GET    /api/entries/<table>/edits          — what was corrected, for a set of rows
GET    /api/dormant                        — capability the data earned, still off
POST   /api/dormant/<key>/dismiss          — stop offering one
DELETE /api/dormant/<key>/dismiss          — offer it again

One blueprint rather than a PATCH bolted onto each feature's routes. The rule
about what a person may rewrite in their own health record is a single decision
(db/corrections.EDITABLE), and splitting it across three files is how the three
copies drift apart — which is the bug this codebase keeps finding.

PATCH, not PUT: the client sends only the fields it is changing, and a PUT that
silently blanked everything absent would be a very bad way to fix a typo.
"""
from flask import Blueprint, jsonify, request

from auth import require_auth

bp = Blueprint('corrections', __name__)


@bp.route('/api/entries/<table>/<row_id>', methods=['PATCH'])
@require_auth
def api_correct_entry(table, row_id):
    from db.corrections import apply_correction
    try:
        result = apply_correction(table, row_id, request.json or {})
    except ValueError as e:
        # An un-correctable table. 400 rather than 404: the row may well exist,
        # and saying "not found" would send someone hunting for the wrong thing.
        return jsonify({'success': False, 'error': str(e)}), 400
    except LookupError:
        return jsonify({'success': False, 'error': 'no such entry'}), 404
    return jsonify({'success': True, **result})


@bp.route('/api/dormant')
@require_auth
def api_dormant():
    """Capability this account's own data has earned but never switched on."""
    from db.dormant import report
    return jsonify(report(include_dismissed=bool(request.args.get('all'))))


@bp.route('/api/dormant/<key>/dismiss', methods=['POST'])
@require_auth
def api_dormant_dismiss(key):
    from db.dormant import dismiss
    if not dismiss(key):
        return jsonify({'success': False, 'error': 'unknown suggestion'}), 400
    return jsonify({'success': True})


@bp.route('/api/dormant/<key>/dismiss', methods=['DELETE'])
@require_auth
def api_dormant_restore(key):
    """Undo a dismissal. A one-way "never show me this" with no way back is a
    setting the user cannot find again."""
    from db.dormant import restore
    restore(key)
    return jsonify({'success': True})


@bp.route('/api/entries/<table>/fields')
@require_auth
def api_entry_fields(table):
    """What the correction form should offer. Served rather than restated in
    JS so there is one answer to "which fields may be changed" — the same
    declaration the server validates against."""
    from db.corrections import EDITABLE, field_spec
    if table not in EDITABLE:
        return jsonify({'success': False, 'error': f'{table} is not correctable'}), 400
    return jsonify({'fields': field_spec(table)})


@bp.route('/api/entries/<table>/edits')
@require_auth
def api_entry_edits(table):
    """Corrections for the rows named in ?ids=a,b,c — batched, because a list
    view would otherwise ask once per row for a marker most rows lack."""
    from db.corrections import EDITABLE, corrections_for
    if table not in EDITABLE:
        return jsonify({'success': False, 'error': f'{table} is not correctable'}), 400
    ids = [s for s in (request.args.get('ids') or '').split(',') if s][:200]
    return jsonify({'edits': corrections_for(table, ids)})
