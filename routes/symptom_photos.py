"""routes/symptom_photos.py — M3 symptom photo journal.

Upload a photo to track how a rash / wound / swelling LOOKS over time. Images
only; every route @require_auth and user-scoped. The files are served only via
the ownership-checked /uploads/<filename> route (see routes/reports.py).

GET    /api/symptom-photos            — the user's photos, newest first
POST   /api/symptom-photos            — multipart: file + label, taken_date, notes
DELETE /api/symptom-photos/<pid>      — remove row + file
"""
import os
import uuid

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from auth import require_auth
from db.symptom_photos import add_photo, list_photos, delete_photo

bp = Blueprint('symptom_photos', __name__)

_IMG_EXTS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
_MAX = 8 * 1024 * 1024   # 8 MB


def _ext(filename):
    if '.' not in (filename or ''):
        return None
    e = filename.rsplit('.', 1)[1].lower()
    return e if e in _IMG_EXTS else None


@bp.route('/api/symptom-photos')
@require_auth
def api_list():
    return jsonify({'photos': list_photos()})


@bp.route('/api/symptom-photos', methods=['POST'])
@require_auth
def api_add():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file'}), 400
    f = request.files['file']
    ext = _ext(f.filename)
    if not ext:
        return jsonify({'success': False, 'error': 'Please upload an image (jpg, png, webp or gif).'}), 400
    # Size guard without trusting Content-Length.
    f.stream.seek(0, os.SEEK_END)
    size = f.stream.tell()
    f.stream.seek(0)
    if size > _MAX:
        return jsonify({'success': False, 'error': 'Image is too large (max 8 MB).'}), 400

    safe = secure_filename(f.filename)
    if not safe or '.' not in safe:
        safe = f"photo.{ext}"
    unique_name = f"sym_{uuid.uuid4().hex}_{safe}"
    f.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name))
    rec = add_photo(request.form.get('label', ''), unique_name,
                    request.form.get('taken_date', ''), request.form.get('notes', ''))
    return jsonify({'success': True, 'photo': rec})


@bp.route('/api/symptom-photos/<pid>', methods=['DELETE'])
@require_auth
def api_delete(pid):
    filename = delete_photo(pid)
    if filename:
        try:
            fp = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(fp):
                os.remove(fp)
        except OSError:
            pass
    return jsonify({'success': True})
