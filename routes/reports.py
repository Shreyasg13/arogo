"""routes/reports.py — Medical reports: upload, list, delete, stats."""
from flask import Blueprint, request, jsonify, send_from_directory, current_app
import os, json as json_mod
from db import *
from config import Config

bp = Blueprint("reports", __name__)

# Replace @bp.route with @bp.route below

# ── Reports ───────────────────────────────────────────────────────────────────

@bp.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename or not allowed_file(f.filename): return jsonify({'error': 'Invalid file'}), 400
    from werkzeug.utils import secure_filename
    filename = secure_filename(f.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    f.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
    report = insert_report({
        'filename': unique_name, 'original_name': filename,
        'patient_name': request.form.get('patient_name', 'Anonymous'),
        'report_type':  request.form.get('report_type', 'General'),
        'report_date':  request.form.get('report_date', today_iso()),
        'tags':         request.form.getlist('tags'),
        'analysis_notes': request.form.get('analysis_notes', ''),
        'severity':     request.form.get('severity', 'normal'),
        'doctor':       request.form.get('doctor', ''),
        'file_ext':     filename.rsplit('.',1)[1].lower()
    })
    return jsonify({'success': True, 'report': report})

@bp.route('/api/reports')
def get_reports():
    return jsonify(list_reports(
        search=request.args.get('search',''),
        tag=request.args.get('tag',''),
        severity=request.args.get('severity','')
    ))

@bp.route('/api/reports/<rid>', methods=['DELETE'])
def del_report(rid):
    r = get_report(rid)
    if r:
        fp = os.path.join(app.config['UPLOAD_FOLDER'], r['filename'])
        if os.path.exists(fp): os.remove(fp)
        delete_report(rid)
        return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404

@bp.route('/api/stats')
def stats():
    return jsonify(report_stats())

@bp.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ── Medicines ─────────────────────────────────────────────────────────────────
