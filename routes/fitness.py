"""routes/fitness.py — Fitness activities, calendar, consistency, sync."""
from flask import Blueprint, request, jsonify, send_from_directory, current_app
import os, json as json_mod
from db import *
from config import Config

bp = Blueprint("fitness", __name__)


# ── Fitness ───────────────────────────────────────────────────────────────────

@bp.route('/api/fitness/activities', methods=['GET'])
def get_activities():
    return jsonify(list_activities())

@bp.route('/api/fitness/activities', methods=['POST'])
def add_activity():
    data = request.json or {}
    data['source'] = data.get('source', 'manual')
    act = insert_activity(data, check_duplicate=False)
    return jsonify({'success': True, 'activity': act})

@bp.route('/api/fitness/activities/<aid>', methods=['DELETE'])
def del_activity(aid):
    delete_activity(aid)
    return jsonify({'success': True})

@bp.route('/api/fitness/stats')
def fit_stats():
    return jsonify(fitness_stats())

@bp.route('/api/fitness/sync-log')
def sync_log():
    service = request.args.get('service')
    return jsonify(get_sync_history(service=service, limit=20))

@bp.route('/api/fitness/connected')
def connected_services():
    tokens = list_tokens()
    return jsonify(tokens)

@bp.route('/api/fitness/disconnect', methods=['POST'])
def disconnect_service():
    service = (request.json or {}).get('service')
    if service: delete_token(service)
    return jsonify({'success': True})

@bp.route('/api/fitness/calendar')
def fitness_calendar():
    """Return all activity dates + metadata for calendar rendering."""
    import datetime as dt
    activities = list_activities()
    # Build a map: date -> { count, types, calories, duration }
    cal = {}
    for a in activities:
        d = a.get('date', '')
        if not d: continue
        if d not in cal:
            cal[d] = {'count': 0, 'types': [], 'calories': 0, 'duration': 0, 'activities': []}
        cal[d]['count'] += 1
        t = a.get('type', 'other')
        if t not in cal[d]['types']: cal[d]['types'].append(t)
        cal[d]['calories'] += a.get('calories', 0)
        cal[d]['duration'] += a.get('duration', 0)
        cal[d]['activities'].append({
            'id': a['id'], 'name': a.get('name', t), 'type': t,
            'duration': a.get('duration', 0), 'calories': a.get('calories', 0),
            'distance': a.get('distance', 0), 'source': a.get('source', 'manual')
        })
    return jsonify(cal)

@bp.route('/api/fitness/consistency')
def fitness_consistency():
    """Streak, active days, best week, monthly breakdown."""
    import datetime as dt
    activities = list_activities()
    if not activities:
        return jsonify({'current_streak': 0, 'longest_streak': 0, 'active_days_month': 0,
                        'active_days_total': 0, 'total_activities': 0, 'monthly': [], 'best_month': ''})

    # All unique active dates sorted ascending
    active_dates = sorted(set(a['date'] for a in activities if a.get('date')))

    # Current streak
    today = dt.date.today()
    streak, d = 0, today
    while d.isoformat() in active_dates or (d == today and streak == 0):
        if d.isoformat() in active_dates:
            streak += 1
            d -= dt.timedelta(days=1)
        elif d == today:
            d -= dt.timedelta(days=1)  # allow gap on today
        else:
            break

    # Longest streak
    longest, cur = 0, 0
    prev = None
    for ds in active_dates:
        dd = dt.date.fromisoformat(ds)
        if prev and (dd - prev).days == 1:
            cur += 1
        else:
            cur = 1
        longest = max(longest, cur)
        prev = dd

    # Monthly breakdown (last 12 months)
    monthly = {}
    for a in activities:
        month = a.get('date', '')[:7]
        if not month: continue
        if month not in monthly:
            monthly[month] = {'days': set(), 'count': 0, 'calories': 0, 'duration': 0}
        monthly[month]['days'].add(a['date'])
        monthly[month]['count'] += 1
        monthly[month]['calories'] += a.get('calories', 0)
        monthly[month]['duration'] += a.get('duration', 0)

    monthly_list = sorted([
        {'month': m, 'active_days': len(v['days']), 'count': v['count'],
         'calories': v['calories'], 'duration': v['duration']}
        for m, v in monthly.items()
    ], key=lambda x: x['month'])[-12:]

    best_month = max(monthly_list, key=lambda x: x['active_days'])['month'] if monthly_list else ''
    this_month = today.strftime('%Y-%m')
    active_this_month = len(monthly.get(this_month, {}).get('days', set()))

    return jsonify({
        'current_streak':   streak,
        'longest_streak':   longest,
        'active_days_month': active_this_month,
        'active_days_total': len(active_dates),
        'total_activities':  len(activities),
        'monthly':           monthly_list,
        'best_month':        best_month
    })

@bp.route('/api/fitness/service-status')
def service_status():
    """Returns which services have credentials configured and which are connected."""
    configured = {
        'strava':     bool(os.environ.get('STRAVA_CLIENT_ID')),
        'garmin':     bool(os.environ.get('GARMIN_CONSUMER_KEY')),
        'google_fit': bool(os.environ.get('GOOGLE_CLIENT_ID')),
        'apple_health': True   # always available (file-based)
    }
    tokens = list_tokens()
    connected = {t['service']: t for t in tokens}
    return jsonify({
        svc: {
            'configured': configured.get(svc, False),
            'connected':  svc in connected,
            'athlete_name': connected.get(svc, {}).get('athlete_name', ''),
            'last_sync':    connected.get(svc, {}).get('last_sync', '')
        }
        for svc in ['strava', 'garmin', 'google_fit', 'apple_health']
    })

@bp.route('/api/fitness/sync', methods=['POST'])
def manual_sync():
    """Trigger an immediate sync for one or all services."""
    service = (request.json or {}).get('service', 'all')
    try:
        from fitness_sync import strava, garmin, google_fit
        results = {}
        clients = {'strava': strava, 'garmin': garmin, 'google_fit': google_fit}
        targets = clients if service == 'all' else {service: clients[service]}
        for svc, client in targets.items():
            tok = get_token(svc)
            if not tok:
                results[svc] = {'status': 'not_connected'}
                continue
            count = client.sync_activities(days_back=7)
            results[svc] = {'status': 'ok', 'count': count}
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ── Apple Health import ───────────────────────────────────────────────────────

@bp.route('/api/fitness/apple/import', methods=['POST'])
def apple_import():
    """
    Upload the export.xml (or a ZIP containing it) from iPhone.
    iPhone: Health → Profile → Export All Health Data → share to browser.
    """
    import zipfile, tempfile
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    tmpdir = tempfile.mkdtemp()
    xml_path = None

    if f.filename.endswith('.zip'):
        zpath = os.path.join(tmpdir, 'export.zip')
        f.save(zpath)
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if 'export.xml' in name:
                    z.extract(name, tmpdir)
                    xml_path = os.path.join(tmpdir, name)
                    break
    elif f.filename.endswith('.xml'):
        xml_path = os.path.join(tmpdir, 'export.xml')
        f.save(xml_path)

    if not xml_path or not os.path.exists(xml_path):
        return jsonify({'error': 'Could not find export.xml'}), 400

    from fitness_sync import apple
    total, new_count = apple.parse_file(xml_path)
    return jsonify({'success': True, 'total': total, 'imported': new_count})

# ══════════════════════════════════════════════════════════════════════════════
# OAuth Callback Routes
# ══════════════════════════════════════════════════════════════════════════════

# ── Strava ────────────────────────────────────────────────────────────────────
