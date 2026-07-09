"""routes/oauth.py — OAuth flows: Strava, Garmin, Google Fit."""
from flask import (Blueprint, request, jsonify, send_from_directory,
                   current_app, redirect, render_template)
import os, json as json_mod
from auth import require_auth
from db import *
from config import Config

import requests
bp = Blueprint("oauth", __name__)

@bp.route('/oauth/strava/start')
@require_auth
def strava_start():
    from fitness_sync import strava
    if not os.environ.get('STRAVA_CLIENT_ID'):
        return jsonify({'error': 'STRAVA_CLIENT_ID not set in environment'}), 501
    return redirect(strava.get_auth_url())

@bp.route('/oauth/strava/callback')
@require_auth
def strava_callback():
    from fitness_sync import strava
    code = request.args.get('code')
    error = request.args.get('error')
    if error or not code:
        return render_template('oauth_result.html',
            service='Strava', success=False,
            message=f"Authorization denied: {error or 'no code'}")
    try:
        token = strava.exchange_code(code)
        count = strava.sync_activities(days_back=30)
        return render_template('oauth_result.html',
            service='Strava', success=True,
            message=f"Connected as {token.get('athlete_name','Athlete')}. Imported {count} activities.")
    except Exception as e:
        log_sync('strava', 'error', 0, str(e))
        return render_template('oauth_result.html',
            service='Strava', success=False, message=str(e))

# ── Garmin ────────────────────────────────────────────────────────────────────

@bp.route('/oauth/garmin/start')
@require_auth
def garmin_start():
    from fitness_sync import garmin
    if not os.environ.get('GARMIN_CONSUMER_KEY'):
        return jsonify({'error': 'GARMIN_CONSUMER_KEY not set in environment'}), 501
    try:
        req_token = garmin.get_request_token()
        session['garmin_token_secret'] = req_token.get('oauth_token_secret', '')
        return redirect(garmin.get_auth_url(req_token['oauth_token']))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/oauth/garmin/callback')
@require_auth
def garmin_callback():
    from fitness_sync import garmin
    oauth_token    = request.args.get('oauth_token', '')
    oauth_verifier = request.args.get('oauth_verifier', '')
    token_secret   = session.pop('garmin_token_secret', '')
    try:
        token = garmin.exchange_token(oauth_token, token_secret, oauth_verifier)
        count = garmin.sync_activities(days_back=30)
        return render_template('oauth_result.html',
            service='Garmin', success=True,
            message=f"Connected as {token.get('athlete_name','Athlete')}. Imported {count} activities.")
    except Exception as e:
        log_sync('garmin', 'error', 0, str(e))
        return render_template('oauth_result.html',
            service='Garmin', success=False, message=str(e))

# ── Google Fit ────────────────────────────────────────────────────────────────

@bp.route('/oauth/google/start')
@require_auth
def google_start():
    from fitness_sync import google_fit
    if not os.environ.get('GOOGLE_CLIENT_ID'):
        return jsonify({'error': 'GOOGLE_CLIENT_ID not set in environment'}), 501
    return redirect(google_fit.get_auth_url())

@bp.route('/oauth/google/callback')
@require_auth
def google_callback():
    from fitness_sync import google_fit
    code = request.args.get('code')
    error = request.args.get('error')
    if error or not code:
        return render_template('oauth_result.html',
            service='Google Fit', success=False,
            message=f"Authorization denied: {error or 'no code'}")
    try:
        token = google_fit.exchange_code(code)
        count = google_fit.sync_activities(days_back=30)
        return render_template('oauth_result.html',
            service='Google Fit', success=True,
            message=f"Connected as {token.get('athlete_name','User')}. Imported {count} activities.")
    except Exception as e:
        log_sync('google_fit', 'error', 0, str(e))
        return render_template('oauth_result.html',
            service='Google Fit', success=False, message=str(e))

# ── Apple Health (no OAuth — file upload based) ───────────────────────────────
# See /api/fitness/apple/import above

# ══════════════════════════════════════════════════════════════════════════════
# Food Tracker Routes
# ══════════════════════════════════════════════════════════════════════════════

