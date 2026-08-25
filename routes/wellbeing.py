"""
routes/wellbeing.py — questionnaires and blood donations.

GET    /api/questionnaires            — the instruments and their items
POST   /api/questionnaires/<key>      — score and save a completed run
GET    /api/questionnaires/runs       — past scores (moments, not a trend)
DELETE /api/questionnaires/runs/<id>
GET    /api/donations, POST /api/donations, DELETE /api/donations/<id>
GET    /api/donations/eligibility     — earliest date per kind

Questionnaire runs are health data of the most personal kind, so they sit behind
the same acting-as wall as the journal.
"""
from flask import Blueprint, request, jsonify

from auth import require_auth

bp = Blueprint('wellbeing', __name__)


@bp.route('/api/questionnaires')
@require_auth
def api_instruments():
    from db.questionnaires import list_instruments, NOT_A_DIAGNOSIS
    return jsonify({'instruments': list_instruments(),
                    'not_a_diagnosis': NOT_A_DIAGNOSIS})


@bp.route('/api/questionnaires/runs')
@require_auth
def api_runs():
    from db.questionnaires import list_runs
    return jsonify({'runs': list_runs(request.args.get('instrument'))})


@bp.route('/api/questionnaires/runs/<rid>', methods=['DELETE'])
@require_auth
def api_delete_run(rid):
    from db.questionnaires import delete_run
    return jsonify({'success': delete_run(rid)})


@bp.route('/api/questionnaires/<key>', methods=['POST'])
@require_auth
def api_score(key):
    """Score a completed questionnaire.

    A non-zero answer to PHQ-9 item 9 — thoughts of self-harm — is not a number
    to file away, so the response carries the guidance the UI must show, built
    from the emergency numbers the app already ships rather than a helpline
    invented for a country nobody checked.
    """
    from db.questionnaires import save_run, risk_response
    from db.food import get_profile
    d = request.json or {}
    try:
        result = save_run(key, d.get('answers'), d.get('taken_on'))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if result.get('risk_flag'):
        result['risk'] = risk_response((get_profile() or {}).get('country'))
    return jsonify({'success': True, **result})


@bp.route('/api/donations')
@require_auth
def api_donations():
    from db.donations import list_donations, KINDS
    return jsonify({'donations': list_donations(),
                    'kinds': [{'key': k, 'label': v['label'], 'days': v['days']}
                              for k, v in KINDS.items()]})


@bp.route('/api/donations', methods=['POST'])
@require_auth
def api_add_donation():
    from db.donations import add_donation
    try:
        return jsonify({'success': True, 'donation': add_donation(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/donations/<did>', methods=['DELETE'])
@require_auth
def api_delete_donation(did):
    from db.donations import delete_donation
    return jsonify({'success': delete_donation(did)})


@bp.route('/api/donations/eligibility')
@require_auth
def api_eligibility():
    """A date per kind, never a verdict. Illness, medication, travel and iron
    levels all affect whether someone can actually give, and none of that is
    knowable from a donation log."""
    from db.donations import next_eligible
    return jsonify(next_eligible())
