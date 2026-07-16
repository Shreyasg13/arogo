"""routes/medicines.py — Medicine CRUD, dose logging, stock."""
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from auth import require_auth
import os, json as json_mod
from db import *
from db.core import user_today
from config import Config

bp = Blueprint("medicines", __name__)


# ── Medicines ─────────────────────────────────────────────────────────────────

@bp.route('/api/medicines', methods=['GET'])
@require_auth
def get_medicines():
    return jsonify(list_medicines())

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