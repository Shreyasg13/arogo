"""routes/vitals_import.py — Category 1 device CSV import.

POST /api/import/vitals/preview  {csv}          → parse only, nothing saved
POST /api/import/vitals/commit   {rows:[...]}   → save the confirmed rows

Preview never writes. Commit re-validates every row through log_vital (range
checks enforced), so a bad reading is skipped and counted, never fabricated or
force-inserted. All @require_auth and user-scoped (log_vital uses current_user_id).
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.vitals_import import parse_vitals_csv
from db.health import log_vital

bp = Blueprint('vitals_import', __name__)

_ALLOWED_TYPES = {'blood_pressure', 'blood_sugar', 'heart_rate', 'spo2', 'temperature'}


@bp.route('/api/import/vitals/preview', methods=['POST'])
@require_auth
def api_preview():
    csv = str((request.json or {}).get('csv', ''))[:1_000_000]   # 1 MB of text, generous
    return jsonify(parse_vitals_csv(csv))


@bp.route('/api/import/vitals/commit', methods=['POST'])
@require_auth
def api_commit():
    rows = (request.json or {}).get('rows')
    if not isinstance(rows, list):
        return jsonify({'success': False, 'error': 'No rows'}), 400
    saved = 0
    failed = 0
    for row in rows[:2000]:
        if not isinstance(row, dict) or row.get('type') not in _ALLOWED_TYPES:
            failed += 1
            continue
        try:
            log_vital({'type': row.get('type'), 'value1': row.get('value1'),
                       'value2': row.get('value2'), 'unit': row.get('unit'),
                       'date_key': row.get('date_key')})
            saved += 1
        except Exception:      # a bad reading (range/format) is skipped + counted, never forced
            failed += 1
    return jsonify({'success': True, 'saved': saved, 'failed': failed})
