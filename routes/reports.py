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
    # Derive the extension from the (already-validated) original name, BEFORE
    # secure_filename() strips non-ASCII characters — a name like "报告.pdf"
    # otherwise collapses to "pdf" with no dot and crashes the .rsplit below.
    file_ext = f.filename.rsplit('.', 1)[1].lower()
    filename = secure_filename(f.filename)
    if not filename or '.' not in filename:
        # Non-ASCII / dotless name: fall back to a safe, extension-only name
        filename = f"upload.{file_ext}"
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
        'file_ext':     file_ext
    })
    return jsonify({'success': True, 'report': report})

@bp.route('/api/reports')
@require_auth
def get_reports():
    return jsonify(list_reports(
        search=request.args.get('search',''),
        tag=request.args.get('tag',''),
        severity=request.args.get('severity',''),
        doc_type=request.args.get('type','')
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

@bp.route('/api/reports/<rid>/readings')
@require_auth
def report_readings(rid):
    """Propose the vitals found in an uploaded report — never writes them.

    The user confirms each reading before it becomes a health record; see
    lab_parse for why we'd rather find nothing than find something wrong.
    """
    import lab_parse

    r = get_report(rid)          # user-scoped: None for someone else's report
    if not r:
        return jsonify({'error': 'Not found'}), 404

    path = os.path.join(current_app.config['UPLOAD_FOLDER'], r['filename'])
    if not os.path.exists(path):
        return jsonify({'readings': [], 'reason': "That file is no longer on the server."})

    text, reason = lab_parse.extract_text(path, r.get('file_ext', ''))
    if text is None:
        return jsonify({'readings': [], 'reason': reason})

    readings = lab_parse.find_readings(text)
    # Date the readings to the day of the test, not the day of the upload.
    return jsonify({'readings': readings,
                    'date_key': r.get('report_date') or today_iso(),
                    'reason': '' if readings else
                              "We read the report but couldn't find any readings we track."})


@bp.route('/api/stats')
@require_auth
def stats():
    return jsonify(report_stats())

@bp.route('/uploads/<filename>')
@require_auth
def uploaded_file(filename):
    # Ownership check: the filename must belong to a report row OR a medicine
    # identification photo (I8) owned by the requester. Without this, any logged-in
    # user could fetch any other user's medical documents.
    from db.core import execute, current_user_id
    uid = current_user_id()
    owned = execute("SELECT 1 FROM reports WHERE filename=? AND user_id=?",
                    (filename, uid), fetchone=True)
    if not owned:
        owned = execute("SELECT 1 FROM medicines WHERE photo_path=? AND user_id=?",
                        (filename, uid), fetchone=True)
    if not owned:
        owned = execute("SELECT 1 FROM symptom_photos WHERE filename=? AND user_id=?",
                        (filename, uid), fetchone=True)
    if not owned:
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

# ── Medicines ─────────────────────────────────────────────────────────────────