"""
routes/push.py — Web Push subscription endpoints.

GET  /api/push/vapid-public-key — key + availability for the browser
POST /api/push/subscribe        — store this browser's PushSubscription
POST /api/push/unsubscribe      — remove it
"""
from flask import Blueprint, request, jsonify, g

from auth import require_auth
from db.core import execute, new_id, now_iso
import push

bp = Blueprint('push', __name__)


@bp.route('/api/push/vapid-public-key')
@require_auth
def vapid_public_key():
    if not push.PUSH_AVAILABLE:
        return jsonify({'enabled': False, 'key': None})
    return jsonify({'enabled': True, 'key': push.get_public_key()})


@bp.route('/api/push/subscribe', methods=['POST'])
@require_auth
def subscribe():
    d = request.json or {}
    sub = d.get('subscription') or {}
    endpoint = sub.get('endpoint')
    if not endpoint or not isinstance(sub.get('keys'), dict):
        return jsonify({'error': 'Invalid subscription'}), 400
    # Upsert by endpoint — a browser re-subscribing (or a different account
    # logging in on the same browser) replaces the old row
    execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,), commit=True)
    import json as json_mod
    execute("""INSERT INTO push_subscriptions (id, endpoint, sub_json, created_at, user_id)
               VALUES (?,?,?,?,?)""",
            (new_id(), endpoint, json_mod.dumps(sub), now_iso(), g.user_id), commit=True)
    return jsonify({'success': True})


@bp.route('/api/push/unsubscribe', methods=['POST'])
@require_auth
def unsubscribe():
    d = request.json or {}
    endpoint = d.get('endpoint') or ''
    execute("DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?",
            (endpoint, g.user_id), commit=True)
    return jsonify({'success': True})
