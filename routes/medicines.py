"""routes/medicines.py — Medicine CRUD, dose logging, stock."""
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from auth import require_auth
import os, json as json_mod
from db import *
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
    med = insert_medicine(data)
    return jsonify({'success': True, 'medicine': med})

@bp.route('/api/medicines/<mid>', methods=['DELETE'])
@require_auth
def del_medicine(mid):
    delete_medicine(mid)
    return jsonify({'success': True})

@bp.route('/api/medicines/<mid>/toggle', methods=['POST'])
@require_auth
def toggle_med(mid):
    toggle_medicine(mid)
    return jsonify({'success': True})

@bp.route('/api/medicines/<mid>/log', methods=['POST'])
@require_auth
def log_dose_route(mid):
    data = request.json or {}
    log_dose(mid,
             data.get('date', today_iso()),
             data.get('time', ''),
             taken=data.get('taken', True))
    return jsonify({'success': True})

@bp.route('/api/medicines/today')
@require_auth
def today_doses():
    return jsonify(get_today_doses())

@bp.route('/api/medicines/adherence')
@require_auth
def adherence():
    days = int(request.args.get('days', 30))
    return jsonify(get_adherence_stats(days))

# ── Fitness ───────────────────────────────────────────────────────────────────