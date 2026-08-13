"""routes/medicines.py — Medicine CRUD, dose logging, stock."""
from flask import Blueprint, request, jsonify, send_from_directory, current_app, Response
from werkzeug.utils import secure_filename
import uuid
from auth import require_auth
from db.calendar_export import build_ics
from db.travel import plan_travel_supply
from db.medicines import set_medicine_photo, clear_medicine_photo

# Pill/pack identification photos are images only — no PDFs or other doc types
# that the generic report uploader allows.
_MED_PHOTO_EXTS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
_MED_PHOTO_MAX = 8 * 1024 * 1024   # 8 MB


def _med_photo_ext(filename):
    if '.' not in (filename or ''):
        return None
    ext = filename.rsplit('.', 1)[1].lower()
    return ext if ext in _MED_PHOTO_EXTS else None
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


@bp.route('/api/calendar.ics', methods=['GET'])
@require_auth
def calendar_ics():
    """A downloadable iCalendar feed of the user's own dose times, upcoming
    appointments, and labs due for a recheck — everything they entered, nothing
    invented. Imports into Google/Apple/Outlook calendars."""
    try:
        days = int(request.args.get('days', 90))
    except (TypeError, ValueError):
        days = 90
    body = build_ics(days_ahead=days)
    return Response(body, mimetype='text/calendar; charset=utf-8', headers={
        'Content-Disposition': 'attachment; filename="arogo-health.ics"'})


@bp.route('/api/medicines/travel-supply', methods=['GET'])
@require_auth
def travel_supply():
    """Pills needed per medicine for a trip, and what to refill before leaving.
    From each med's own schedule + stock; PRN excluded."""
    return jsonify(plan_travel_supply(request.args.get('start', ''),
                                      request.args.get('end', '')))


@bp.route('/api/medicines/<mid>/photo', methods=['POST'])
@require_auth
def upload_medicine_photo(mid):
    """Attach an identification photo (of the pill or pack) to a medicine, so a
    caregiver or an older user can recognise it. Images only; owner-checked."""
    if not get_medicine(mid):          # user-scoped: None for missing/foreign
        return jsonify({'success': False, 'error': 'Medicine not found'}), 404
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file'}), 400
    f = request.files['file']
    ext = _med_photo_ext(f.filename)
    if not ext:
        return jsonify({'success': False, 'error': 'Please upload an image (jpg, png, webp or gif).'}), 400
    # Size guard: read the stream length without trusting Content-Length.
    f.stream.seek(0, os.SEEK_END)
    size = f.stream.tell()
    f.stream.seek(0)
    if size > _MED_PHOTO_MAX:
        return jsonify({'success': False, 'error': 'Image is too large (max 8 MB).'}), 400

    safe = secure_filename(f.filename)
    if not safe or '.' not in safe:
        safe = f"pill.{ext}"
    unique_name = f"medphoto_{uuid.uuid4().hex}_{safe}"
    f.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name))
    prev = set_medicine_photo(mid, unique_name)   # owner already confirmed above
    # Clean up a replaced photo so old files don't accumulate.
    if prev:
        try:
            old = os.path.join(current_app.config['UPLOAD_FOLDER'], prev)
            if os.path.exists(old):
                os.remove(old)
        except OSError:
            pass
    return jsonify({'success': True, 'photo_path': unique_name})


@bp.route('/api/medicines/<mid>/photo', methods=['DELETE'])
@require_auth
def delete_medicine_photo(mid):
    removed = clear_medicine_photo(mid)
    if removed:
        try:
            fp = os.path.join(current_app.config['UPLOAD_FOLDER'], removed)
            if os.path.exists(fp):
                os.remove(fp)
        except OSError:
            pass
    return jsonify({'success': True})


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
    """Snooze a dose reminder — the scheduler re-pushes when the delay elapses.
    If the client doesn't specify a length, use the user's configured default."""
    d = request.json or {}
    if d.get('minutes') is not None:
        minutes = to_int(d.get('minutes'), 15, lo=1, hi=180)
    else:
        from db.core import execute, current_user_id
        row = execute("SELECT default_snooze_min FROM reminder_settings WHERE user_id=? LIMIT 1",
                      (current_user_id(),), fetchone=True)
        minutes = to_int(row['default_snooze_min'], 10, lo=1, hi=180) if row and row['default_snooze_min'] is not None else 10
    res = snooze_dose(mid, str(d.get('time', ''))[:5], minutes)
    if not res:
        return jsonify({'success': False, 'error': 'Unknown medicine'}), 404
    return jsonify({'success': True, **res})

@bp.route('/api/medicines/forecast')
@require_auth
def medicines_forecast():
    """Run-out dates per medicine + monthly/yearly cost projection."""
    return jsonify(get_med_forecast())


@bp.route('/api/medicines/timing-conflicts')
@require_auth
def medicines_timing_conflicts():
    """Same-time meds with conflicting food instructions (timing hygiene only)."""
    return jsonify({'conflicts': get_timing_conflicts()})


@bp.route('/api/medicines/<mid>/reminder-lead', methods=['POST'])
@require_auth
def set_med_reminder_lead(mid):
    """Adjust how many minutes early this medicine's reminder fires."""
    d = request.json or {}
    m = set_reminder_lead(mid, d.get('minutes', 0))
    if not m:
        return jsonify({'success': False, 'error': 'Unknown medicine'}), 404
    return jsonify({'success': True, 'medicine': m})


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
                  taken=data.get('taken', True),
                  reason=data.get('reason'))
    if not ok:
        return jsonify({'success': False, 'error': 'Medicine not found'}), 404
    return jsonify({'success': True})

@bp.route('/api/medicines/skip-reasons')
@require_auth
def skip_reasons():
    from db.medicines import get_skip_reasons
    days = to_int(request.args.get('days', 30), 30, lo=1, hi=366)
    return jsonify(get_skip_reasons(days))

@bp.route('/api/medicines/today')
@require_auth
def today_doses():
    return jsonify(get_today_doses())

@bp.route('/api/medicines/adherence')
@require_auth
def adherence():
    days = to_int(request.args.get('days', 30), 30, lo=0, hi=3650)
    return jsonify(get_adherence_stats(days))

@bp.route('/api/medicines/adherence/timeofday')
@require_auth
def adherence_timeofday():
    days = to_int(request.args.get('days', 30), 30, lo=1, hi=366)
    return jsonify(get_adherence_by_timeofday(days))

@bp.route('/api/medicines/adherence/weekday')
@require_auth
def adherence_weekday():
    days = to_int(request.args.get('days', 90), 90, lo=1, hi=366)
    return jsonify(get_adherence_by_weekday(days))

@bp.route('/api/medicines/new-med-watch')
@require_auth
def new_med_watch():
    days = to_int(request.args.get('days', 45), 45, lo=1, hi=180)
    return jsonify(get_new_med_watch(days))

@bp.route('/api/medicines/at-risk')
@require_auth
def at_risk_dose():
    return jsonify({'at_risk': get_at_risk_dose_today()})

@bp.route('/api/medicines/adherence/forecast')
@require_auth
def adherence_forecast():
    return jsonify(get_adherence_forecast())

@bp.route('/api/medicines/adherence/responsiveness')
@require_auth
def adherence_responsiveness():
    days = to_int(request.args.get('days', 30), 30, lo=1, hi=366)
    return jsonify(get_reminder_responsiveness(days))

@bp.route('/api/medicines/adherence/goal', methods=['GET', 'POST'])
@require_auth
def adherence_goal():
    if request.method == 'POST':
        try:
            g = set_adherence_goal((request.json or {}).get('pct'))
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        return jsonify({'success': True, 'goal_pct': g})
    return jsonify({'goal_pct': get_adherence_goal()})

@bp.route('/api/medicines/calendar')
@require_auth
def dose_calendar():
    from db.medicines import get_adherence_streak
    days = to_int(request.args.get('days', 35), 35, lo=1, hi=366)
    return jsonify({'days': get_dose_calendar(days), 'streak': get_adherence_streak()})

@bp.route('/api/medicines/refill-list')
@require_auth
def refill_list():
    """Everything to pick up on a pharmacy run — low, out, or on the way."""
    from db.pharmacy import get_pharmacy, refill_message
    return jsonify({'items': get_refill_list(),
                    'pharmacy': get_pharmacy(), 'refill_message': refill_message()})

@bp.route('/api/pharmacy', methods=['GET', 'POST'])
@require_auth
def pharmacy():
    from db.pharmacy import get_pharmacy, set_pharmacy
    if request.method == 'POST':
        data = request.json or {}
        return jsonify({'success': True, 'pharmacy': set_pharmacy(data.get('name', ''), data.get('phone', ''))})
    return jsonify(get_pharmacy())

@bp.route('/api/medicines/cost')
@require_auth
def monthly_cost():
    """Total monthly medicine spend + per-medicine breakdown."""
    return jsonify(get_monthly_med_cost())

@bp.route('/api/medicines/spend-timeline')
@require_auth
def spend_timeline():
    months = to_int(request.args.get('months', 12), 12, lo=1, hi=36)
    return jsonify(get_med_spend_timeline(months))

@bp.route('/api/medicines/history')
@require_auth
def medicine_history():
    """A dated record of medicine changes — started, stopped, resumed, etc."""
    days = to_int(request.args.get('days', 365), 365, lo=1, hi=3650)
    return jsonify({'events': get_medicine_events(days)})

@bp.route('/api/medicines/adherence-breakdown')
@require_auth
def adherence_breakdown():
    """Per-slot adherence, worst first — 'which doses do I miss most?'. Also
    carries a recent-trend nudge (last 7 days) for the same panel to surface."""
    from db.medicines import get_adherence_nudge
    days = to_int(request.args.get('days', 30), 30, lo=1, hi=365)
    out = get_adherence_breakdown(days)
    out['nudge'] = get_adherence_nudge()
    return jsonify(out)

@bp.route('/api/medicines/planner')
@require_auth
def pill_planner():
    """Upcoming days×times grid for the weekly pill planner."""
    days = to_int(request.args.get('days', 7), 7, lo=1, hi=14)
    return jsonify(get_pill_planner(days))

@bp.route('/api/medicines/card')
@require_auth
def medication_card():
    """Data for the printable medication card — schedule grouped by time of day
    plus emergency contacts. Read-only; nothing here is fabricated."""
    import datetime as dt
    from db.core import execute, current_user_id
    card = get_medication_card()
    urow = execute("SELECT name, email FROM users WHERE id=?",
                   (current_user_id(),), fetchone=True)
    card['person'] = {'name': (urow['name'] if urow else '') or (urow['email'] if urow else '')}
    card['generated'] = dt.date.today().isoformat()
    return jsonify(card)

# ── Fitness ───────────────────────────────────────────────────────────────────