"""routes/medicines.py — Medicine CRUD, dose logging, stock."""
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from auth import require_auth
import os, json as json_mod
from db import *
from db.core import user_today
from config import Config

try:
    from drug_data import search_drugs
except ImportError:
    import importlib.util as _ilu
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'drug_data.py')
    _s = _ilu.spec_from_file_location('drug_data', _p)
    _m = _ilu.module_from_spec(_s); _s.loader.exec_module(_m)
    search_drugs = _m.search_drugs

bp = Blueprint("medicines", __name__)


# ── Medicines ─────────────────────────────────────────────────────────────────

@bp.route('/api/medicines', methods=['GET'])
@require_auth
def get_medicines():
    return jsonify(list_medicines())


@bp.route('/api/medicines/drugs', methods=['GET'])
@require_auth
def drug_autocomplete():
    """Name suggestions for the add-medicine field. Identification only — no
    dosing, no interactions (see drug_data.py)."""
    q = request.args.get('q', '')
    return jsonify({'drugs': search_drugs(q, limit=8)})

@bp.route('/api/medicines/<mid>/take-now', methods=['POST'])
@require_auth
def take_now(mid):
    """Log a one-off, unscheduled ('as needed') dose taken right now."""
    res = log_prn_dose(mid)
    if not res:
        return jsonify({'success': False, 'error': 'Unknown medicine'}), 404
    return jsonify({'success': True, **res})

@bp.route('/api/medicines/<mid>/snooze', methods=['POST'])
@require_auth
def snooze(mid):
    """Snooze a dose reminder — the scheduler re-pushes when the delay elapses."""
    d = request.json or {}
    res = snooze_dose(mid, str(d.get('time', ''))[:5],
                      to_int(d.get('minutes', 15), 15, lo=1, hi=180))
    if not res:
        return jsonify({'success': False, 'error': 'Unknown medicine'}), 404
    return jsonify({'success': True, **res})

@bp.route('/api/medicines/parse-rx', methods=['POST'])
@require_auth
def parse_rx():
    """Read a prescription and PROPOSE medicines — never adds them. The user
    confirms every row (see rx_parse). The file is parsed to a temp path and
    deleted immediately; prescriptions aren't stored here."""
    import uuid, rx_parse
    from werkzeug.utils import secure_filename
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename or '.' not in f.filename:
        return jsonify({'error': 'File type not allowed'}), 400
    ext = f.filename.rsplit('.', 1)[1].lower()
    if ext not in Config.ALLOWED_EXTENSIONS:
        return jsonify({'error': 'File type not allowed'}), 400
    tmp = os.path.join(current_app.config['UPLOAD_FOLDER'],
                       f"rx_{uuid.uuid4().hex}.{ext}")
    f.save(tmp)
    try:
        text, reason = rx_parse.extract_text(tmp, ext)
        meds = rx_parse.find_medicines(text) if text else []
    finally:
        try: os.remove(tmp)          # don't keep the prescription around
        except OSError: pass
    return jsonify({
        'medicines': meds,
        'ocr_available': rx_parse.ocr_available(),
        'reason': reason if text is None else
                  ('' if meds else "We read it but couldn't spot any medicines we recognise — add them by hand."),
    })

@bp.route('/api/medicines', methods=['POST'])
@require_auth
def add_medicine():
    data = request.json or {}
    try:
        med = insert_medicine(data)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'medicine': med})

@bp.route('/api/medicines/<mid>', methods=['DELETE'])
@require_auth
def del_medicine(mid):
    if not get_medicine(mid):          # user-scoped: None for missing/foreign
        return jsonify({'success': False, 'error': 'Medicine not found'}), 404
    delete_medicine(mid)
    return jsonify({'success': True})

@bp.route('/api/medicines/<mid>/toggle', methods=['POST'])
@require_auth
def toggle_med(mid):
    if not get_medicine(mid):
        return jsonify({'success': False, 'error': 'Medicine not found'}), 404
    toggle_medicine(mid)
    return jsonify({'success': True})

@bp.route('/api/medicines/<mid>/log', methods=['POST'])
@require_auth
def log_dose_route(mid):
    data = request.json or {}
    # Default to the USER's day, not the server's, so a client that omits the
    # date lands on the same day get_today_doses() will read it back from.
    ok = log_dose(mid,
                  data.get('date', user_today()),
                  data.get('time', ''),
                  taken=data.get('taken', True))
    if not ok:
        return jsonify({'success': False, 'error': 'Medicine not found'}), 404
    return jsonify({'success': True})

@bp.route('/api/medicines/today')
@require_auth
def today_doses():
    return jsonify(get_today_doses())

@bp.route('/api/medicines/adherence')
@require_auth
def adherence():
    days = to_int(request.args.get('days', 30), 30, lo=0, hi=3650)
    return jsonify(get_adherence_stats(days))

# ── Fitness ───────────────────────────────────────────────────────────────────