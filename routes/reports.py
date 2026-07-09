"""routes/reports.py — Medical reports: upload, list, delete, stats.

Uploaded files contain medical data: downloads require authentication
AND ownership of the report row that references the filename.
"""
import os
import uuid

from flask import Blueprint, request, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename

from auth import require_auth
from db import *
from config import Config

bp = Blueprint("reports", __name__)


def allowed_file(filename: str) -> bool:
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS)


# ── Reports ───────────────────────────────────────────────────────────────────

@bp.route('/api/upload', methods=['POST'])
@require_auth
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename or not allowed_file(f.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    filename = secure_filename(f.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    f.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name))
    report = insert_report({
        'filename': unique_name, 'original_name': filename,
        'patient_name': request.form.get('patient_name', 'Anonymous'),
        'report_type':  request.form.get('report_type', 'General'),
        'report_date':  request.form.get('report_date', today_iso()),
        'tags':         request.form.getlist('tags'),
        'analysis_notes': request.form.get('analysis_notes', ''),
        'severity':     request.form.get('severity', 'normal'),
        'doctor':       request.form.get('doctor', ''),
        'file_ext':     filename.rsplit('.', 1)[1].lower()
    })
    return jsonify({'success': True, 'report': report})

@bp.route('/api/reports')
@require_auth
def get_reports():
    return jsonify(list_reports(
        search=request.args.get('search',''),
        tag=request.args.get('tag',''),
        severity=request.args.get('severity','')
    ))

@bp.route('/api/reports/<rid>', methods=['DELETE'])
@require_auth
def del_report(rid):
    r = get_report(rid)   # user-scoped: returns None for other users' reports
    if r:
        fp = os.path.join(current_app.config['UPLOAD_FOLDER'], r['filename'])
        if os.path.exists(fp):
            os.remove(fp)
        delete_report(rid)
        return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404

@bp.route('/api/stats')
@require_auth
def stats():
    return jsonify(report_stats())

@bp.route('/uploads/<filename>')
@require_auth
def uploaded_file(filename):
    # Ownership check: the filename must belong to a report row owned by
    # the requester. Without this, any logged-in user could fetch any
    # other user's medical documents.
    from db.core import execute, current_user_id
    owned = execute("SELECT 1 FROM reports WHERE filename=? AND user_id=?",
                    (filename, current_user_id()), fetchone=True)
    if not owned:
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

# ── Medicines ─────────────────────────────────────────────────────────────────