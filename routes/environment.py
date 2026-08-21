"""routes/environment.py — air quality / weather import + how-you-feel correlation."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.environment import (parse_environment_csv, commit_environment, list_environment,
                            get_environment_correlation, target_options)

bp = Blueprint('environment', __name__)


@bp.route('/api/environment/import/preview', methods=['POST'])
@require_auth
def api_preview():
    """Parse an AQI/weather CSV — saves nothing, just shows what we'd import."""
    text = (request.json or {}).get('csv', '')
    return jsonify(parse_environment_csv(text))


@bp.route('/api/environment/import/commit', methods=['POST'])
@require_auth
def api_commit():
    cand = (request.json or {}).get('candidates') or []
    return jsonify({'success': True, **commit_environment(cand)})


@bp.route('/api/environment')
@require_auth
def api_list():
    return jsonify({'days': list_environment(int(request.args.get('days', 30) or 30)),
                    'targets': target_options()})


@bp.route('/api/environment/correlation')
@require_auth
def api_correlation():
    return jsonify(get_environment_correlation(
        request.args.get('target', 'symptoms'), request.args.get('days', 90)))
