"""
fitness_sync.py — Real OAuth integration for Garmin, Strava, Apple Health & Google Fit

SETUP INSTRUCTIONS (per service):
  Strava:
    1. Create app at https://www.strava.com/settings/api
    2. Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env
    3. Redirect URI: http://localhost:5000/oauth/strava/callback

  Garmin:
    1. Apply at https://developer.garmin.com/gc-developer-program/overview/
    2. Uses OAuth 1.0a. Set GARMIN_CONSUMER_KEY and GARMIN_CONSUMER_SECRET
    3. Redirect URI: http://localhost:5000/oauth/garmin/callback

  Apple Health:
    - Apple Health requires HealthKit on iOS (no direct web OAuth).
    - We implement a local export parser: user exports Health data from iPhone
      (Health app → profile → Export All Health Data → share the ZIP)
    - The /api/fitness/apple/import endpoint parses that XML export.

  Google Fit:
    1. Create project at https://console.cloud.google.com
    2. Enable Fitness API, create OAuth 2.0 credentials
    3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET

All secrets go in .env (never committed). python-dotenv loads them automatically.
"""
from __future__ import annotations


import os, json, time, hashlib, hmac, base64, urllib.parse, datetime, requests, xml.etree.ElementTree as ET
from db import (insert_activity, get_token, save_token, update_last_sync,
                log_sync, list_activities, new_id, now_iso, today_iso)

# ── Config ────────────────────────────────────────────────────────────────────

def _env(key, default=''):
    return os.environ.get(key, default)

STRAVA_CLIENT_ID     = _env('STRAVA_CLIENT_ID')
STRAVA_CLIENT_SECRET = _env('STRAVA_CLIENT_SECRET')
STRAVA_REDIRECT_URI  = _env('STRAVA_REDIRECT_URI', 'http://localhost:5000/oauth/strava/callback')
STRAVA_SCOPE         = 'read,activity:read_all'

GARMIN_CONSUMER_KEY    = _env('GARMIN_CONSUMER_KEY')
GARMIN_CONSUMER_SECRET = _env('GARMIN_CONSUMER_SECRET')
GARMIN_REDIRECT_URI    = _env('GARMIN_REDIRECT_URI', 'http://localhost:5000/oauth/garmin/callback')

GOOGLE_CLIENT_ID     = _env('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = _env('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI  = _env('GOOGLE_REDIRECT_URI', 'http://localhost:5000/oauth/google/callback')


# ══════════════════════════════════════════════════════════════════════════════
# STRAVA  (OAuth 2.0)
# ══════════════════════════════════════════════════════════════════════════════

class StravaClient:
    AUTH_URL    = "https://www.strava.com/oauth/authorize"
    TOKEN_URL   = "https://www.strava.com/oauth/token"
    API_BASE    = "https://www.strava.com/api/v3"

    def get_auth_url(self, state='strava'):
        params = {
            'client_id': STRAVA_CLIENT_ID,
            'redirect_uri': STRAVA_REDIRECT_URI,
            'response_type': 'code',
            'approval_prompt': 'auto',
            'scope': STRAVA_SCOPE,
            'state': state
        }
        return self.AUTH_URL + '?' + urllib.parse.urlencode(params)

    def exchange_code(self, code: str) -> dict:
        """Exchange auth code for tokens. Call from callback route."""
        resp = requests.post(self.TOKEN_URL, data={
            'client_id': STRAVA_CLIENT_ID,
            'client_secret': STRAVA_CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code'
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        athlete = data.get('athlete', {})
        token = {
            'access_token':  data['access_token'],
            'refresh_token': data['refresh_token'],
            'token_type':    data.get('token_type', 'Bearer'),
            'expires_at':    datetime.datetime.fromtimestamp(data['expires_at']).isoformat(),
            'scope':         STRAVA_SCOPE,
            'athlete_id':    str(athlete.get('id', '')),
            'athlete_name':  f"{athlete.get('firstname','')} {athlete.get('lastname','')}".strip()
        }
        save_token('strava', token)
        return token

    def _refresh_if_needed(self, tok: dict) -> str:
        """Return a valid access token, refreshing if expired."""
        expires = tok.get('expires_at', '')
        if expires:
            exp_dt = datetime.datetime.fromisoformat(expires)
            if datetime.datetime.now() >= exp_dt - datetime.timedelta(minutes=5):
                resp = requests.post(self.TOKEN_URL, data={
                    'client_id': STRAVA_CLIENT_ID,
                    'client_secret': STRAVA_CLIENT_SECRET,
                    'refresh_token': tok['refresh_token'],
                    'grant_type': 'refresh_token'
                }, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                tok['access_token']  = data['access_token']
                tok['refresh_token'] = data.get('refresh_token', tok['refresh_token'])
                tok['expires_at']    = datetime.datetime.fromtimestamp(data['expires_at']).isoformat()
                save_token('strava', tok)
        return tok['access_token']

    def _headers(self) -> dict:
        tok = get_token('strava')
        if not tok: raise ValueError("Strava not connected")
        return {'Authorization': f"Bearer {self._refresh_if_needed(tok)}"}

    def sync_activities(self, days_back=30) -> int:
        """Fetch recent activities and store them. Returns count of new items."""
        after_ts = int((datetime.datetime.now() - datetime.timedelta(days=days_back)).timestamp())
        headers = self._headers()
        page, imported = 1, 0
        while True:
            resp = requests.get(f"{self.API_BASE}/athlete/activities",
                                headers=headers,
                                params={'after': after_ts, 'per_page': 50, 'page': page},
                                timeout=15)
            resp.raise_for_status()
            activities = resp.json()
            if not activities: break
            for a in activities:
                act = _strava_to_activity(a)
                result = insert_activity(act, check_duplicate=True)
                if result: imported += 1
            if len(activities) < 50: break
            page += 1
        update_last_sync('strava')
        log_sync('strava', 'success', imported, f"Fetched {imported} new activities")
        return imported

    def get_athlete(self) -> dict:
        resp = requests.get(f"{self.API_BASE}/athlete", headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_athlete_stats(self) -> dict:
        tok = get_token('strava')
        athlete_id = tok.get('athlete_id', '')
        if not athlete_id: return {}
        resp = requests.get(f"{self.API_BASE}/athletes/{athlete_id}/stats",
                            headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()


def _strava_to_activity(a: dict) -> dict:
    """Map a Strava API activity object to our schema."""
    sport_map = {
        'Run': 'running', 'Ride': 'cycling', 'Swim': 'swimming',
        'Walk': 'walking', 'Hike': 'hiking', 'Yoga': 'yoga',
        'WeightTraining': 'gym', 'Workout': 'gym', 'VirtualRide': 'cycling_indoor',
        'VirtualRun': 'running', 'Rowing': 'rowing', 'StairStepper': 'gym',
        'Tennis': 'tennis', 'Pickleball': 'pickleball', 'Badminton': 'badminton',
        'Soccer': 'football', 'Basketball': 'basketball', 'Volleyball': 'volleyball',
        'Baseball': 'baseball', 'Cricket': 'cricket', 'Golf': 'golf',
        'Boxing': 'boxing', 'MartialArts': 'martial_arts', 'Dance': 'dancing',
        'Pilates': 'pilates', 'Crossfit': 'crossfit', 'RockClimbing': 'climbing',
        'AlpineSki': 'skiing', 'Snowboard': 'snowboarding', 'IceSkate': 'skating',
        'Elliptical': 'cycling_indoor', 'HandCycle': 'cycling'
    }
    sport_type = a.get('sport_type') or a.get('type', 'Workout')
    start = a.get('start_date_local', '')[:10] if a.get('start_date_local') else today_iso()
    return {
        'type':           sport_map.get(sport_type, 'other'),
        'name':           a.get('name', sport_type),
        'date':           start,
        'duration':       int(a.get('moving_time', 0) // 60),
        'distance':       round(a.get('distance', 0) / 1000, 2),   # m → km
        'calories':       int(a.get('calories', 0) or a.get('kilojoules', 0) or 0),
        'heart_rate_avg': int(a.get('average_heartrate', 0) or 0),
        'heart_rate_max': int(a.get('max_heartrate', 0) or 0),
        'steps':          0,
        'elevation':      round(a.get('total_elevation_gain', 0), 1),
        'notes':          a.get('description', '') or '',
        'source':         'strava',
        'external_id':    f"strava_{a['id']}"
    }


# ══════════════════════════════════════════════════════════════════════════════
# GARMIN  (OAuth 1.0a — Connect IQ / Health API)
# ══════════════════════════════════════════════════════════════════════════════

class GarminClient:
    """
    Garmin uses OAuth 1.0a for the Connect API.
    Full access requires approval from Garmin Developer Program.
    
    Endpoints:
      Request token: https://connectapi.garmin.com/oauth-service/oauth/request_token
      Authorize:     https://connect.garmin.com/oauthConfirm
      Access token:  https://connectapi.garmin.com/oauth-service/oauth/access_token
      Activities:    https://healthapi.garmin.com/wellness-api/rest/activities
      Daily summary: https://healthapi.garmin.com/wellness-api/rest/dailies
    """
    REQUEST_TOKEN_URL = "https://connectapi.garmin.com/oauth-service/oauth/request_token"
    AUTHORIZE_URL     = "https://connect.garmin.com/oauthConfirm"
    ACCESS_TOKEN_URL  = "https://connectapi.garmin.com/oauth-service/oauth/access_token"
    ACTIVITIES_URL    = "https://healthapi.garmin.com/wellness-api/rest/activities"
    DAILIES_URL       = "https://healthapi.garmin.com/wellness-api/rest/dailies"

    def _oauth1_header(self, method, url, oauth_token='', oauth_token_secret='',
                        extra_params=None) -> str:
        """Build OAuth 1.0a Authorization header."""
        params = {
            'oauth_consumer_key':     GARMIN_CONSUMER_KEY,
            'oauth_nonce':            base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip('='),
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp':        str(int(time.time())),
            'oauth_version':          '1.0',
        }
        if oauth_token:
            params['oauth_token'] = oauth_token
        if extra_params:
            params.update(extra_params)

        # Build signature base string
        sorted_params = '&'.join(f"{urllib.parse.quote(k,'')}"
                                 f"={urllib.parse.quote(str(v),'')}"
                                 for k, v in sorted(params.items()))
        base = '&'.join([
            method.upper(),
            urllib.parse.quote(url, ''),
            urllib.parse.quote(sorted_params, '')
        ])
        signing_key = (urllib.parse.quote(GARMIN_CONSUMER_SECRET, '') + '&' +
                       urllib.parse.quote(oauth_token_secret, ''))
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()
        ).decode()
        params['oauth_signature'] = signature

        header = 'OAuth ' + ', '.join(
            f'{urllib.parse.quote(k,"")}'
            f'="{urllib.parse.quote(str(v),"")}"'
            for k, v in sorted(params.items())
        )
        return header

    def get_request_token(self) -> dict:
        header = self._oauth1_header('POST', self.REQUEST_TOKEN_URL,
                                      extra_params={'oauth_callback': GARMIN_REDIRECT_URI})
        resp = requests.post(self.REQUEST_TOKEN_URL,
                             headers={'Authorization': header}, timeout=10)
        resp.raise_for_status()
        parsed = dict(urllib.parse.parse_qsl(resp.text))
        return parsed   # contains oauth_token, oauth_token_secret

    def get_auth_url(self, request_token: str) -> str:
        return f"{self.AUTHORIZE_URL}?oauth_token={request_token}"

    def exchange_token(self, oauth_token, oauth_token_secret, oauth_verifier) -> dict:
        header = self._oauth1_header('POST', self.ACCESS_TOKEN_URL,
                                      oauth_token=oauth_token,
                                      oauth_token_secret=oauth_token_secret,
                                      extra_params={'oauth_verifier': oauth_verifier})
        resp = requests.post(self.ACCESS_TOKEN_URL,
                             headers={'Authorization': header}, timeout=10)
        resp.raise_for_status()
        parsed = dict(urllib.parse.parse_qsl(resp.text))
        token = {
            'access_token':  parsed.get('oauth_token', ''),
            'refresh_token': parsed.get('oauth_token_secret', ''),
            'token_type':    'OAuth1',
            'expires_at':    '',
            'scope':         'activities,dailies',
            'athlete_id':    parsed.get('user_id', ''),
            'athlete_name':  parsed.get('display_name', 'Garmin User')
        }
        save_token('garmin', token)
        return token

    def _auth_header(self, method, url) -> str:
        tok = get_token('garmin')
        if not tok: raise ValueError("Garmin not connected")
        return self._oauth1_header(method, url,
                                    oauth_token=tok['access_token'],
                                    oauth_token_secret=tok.get('refresh_token',''))

    def sync_activities(self, days_back=7) -> int:
        """Fetch Garmin Health API activity summaries."""
        start_ts = int((datetime.datetime.now() - datetime.timedelta(days=days_back)).timestamp())
        end_ts   = int(datetime.datetime.now().timestamp())
        url = self.ACTIVITIES_URL
        header = self._auth_header('GET', url)
        resp = requests.get(url, headers={'Authorization': header},
                            params={'uploadStartTimeInSeconds': start_ts,
                                    'uploadEndTimeInSeconds': end_ts},
                            timeout=15)
        resp.raise_for_status()
        data = resp.json()
        activities = data.get('activityList', data if isinstance(data, list) else [])
        imported = 0
        for a in activities:
            act = _garmin_to_activity(a)
            if insert_activity(act, check_duplicate=True): imported += 1
        update_last_sync('garmin')
        log_sync('garmin', 'success', imported, f"Fetched {imported} new activities")
        return imported

    def sync_daily_summary(self, days_back=7) -> int:
        """Fetch daily wellness summaries (steps, calories, stress)."""
        imported = 0
        for i in range(days_back):
            d = datetime.date.today() - datetime.timedelta(days=i)
            cal_date = d.strftime('%Y-%m-%d')
            start_ts = int(datetime.datetime.combine(d, datetime.time.min).timestamp())
            end_ts   = int(datetime.datetime.combine(d, datetime.time.max).timestamp())
            url = self.DAILIES_URL
            header = self._auth_header('GET', url)
            try:
                resp = requests.get(url, headers={'Authorization': header},
                                    params={'startTimeInSeconds': start_ts,
                                            'endTimeInSeconds': end_ts}, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                summaries = data.get('dailies', data if isinstance(data, list) else [])
                for s in summaries:
                    act = _garmin_daily_to_activity(s, cal_date)
                    if act and insert_activity(act, check_duplicate=True): imported += 1
            except Exception as e:
                log_sync('garmin', 'error', 0, f"Daily {cal_date}: {e}")
        return imported


def _garmin_to_activity(a: dict) -> dict:
    activity_type_map = {
        'RUNNING': 'running', 'CYCLING': 'cycling', 'SWIMMING': 'swimming',
        'WALKING': 'walking', 'HIKING': 'hiking', 'YOGA': 'yoga',
        'STRENGTH_TRAINING': 'gym', 'CARDIO': 'gym', 'FITNESS_EQUIPMENT': 'gym',
        'INDOOR_CYCLING': 'cycling_indoor', 'TRAIL_RUNNING': 'running',
        'TENNIS': 'tennis', 'PICKLEBALL': 'pickleball', 'BADMINTON': 'badminton',
        'SOCCER': 'football', 'BASKETBALL': 'basketball', 'VOLLEYBALL': 'volleyball',
        'BASEBALL': 'baseball', 'CRICKET': 'cricket', 'GOLF': 'golf',
        'BOXING': 'boxing', 'MARTIAL_ARTS': 'martial_arts', 'DANCE': 'dancing',
        'PILATES': 'pilates', 'BOULDERING': 'climbing', 'MOUNTAIN_BIKING': 'cycling',
        'SKIING': 'skiing', 'SNOWBOARDING': 'snowboarding', 'ICE_SKATING': 'skating',
        'ROWING': 'rowing', 'CROSS_TRAINING': 'crossfit'
    }
    raw_type = a.get('activityType', {})
    if isinstance(raw_type, dict): raw_type = raw_type.get('typeKey', 'UNKNOWN').upper()
    mapped = activity_type_map.get(raw_type, 'other')
    start = a.get('startTimeLocal', a.get('startTimeGMT', ''))[:10] if a.get('startTimeLocal') else today_iso()
    return {
        'type':           mapped,
        'name':           a.get('activityName', raw_type.title()),
        'date':           start,
        'duration':       int(a.get('duration', a.get('movingDuration', 0)) // 60),
        'distance':       round(a.get('distance', 0) / 1000, 2),
        'calories':       int(a.get('calories', 0)),
        'heart_rate_avg': int(a.get('averageHR', 0) or 0),
        'heart_rate_max': int(a.get('maxHR', 0) or 0),
        'steps':          int(a.get('steps', 0) or 0),
        'elevation':      round(a.get('elevationGain', 0) or 0, 1),
        'notes':          a.get('description', '') or '',
        'source':         'garmin',
        'external_id':    f"garmin_{a.get('activityId', a.get('summaryId', new_id()))}"
    }


def _garmin_daily_to_activity(s: dict, date_str: str) -> dict | None:
    steps = int(s.get('totalSteps', 0) or 0)
    if steps < 500: return None   # skip near-zero days
    return {
        'type':           'walking',
        'name':           f"Daily Steps — {date_str}",
        'date':           date_str,
        'duration':       int(s.get('activeSeconds', 0) // 60),
        'distance':       round(steps * 0.000762, 2),   # ~76.2 cm avg stride
        'calories':       int(s.get('activeKilocalories', 0) or s.get('totalKilocalories', 0)),
        'heart_rate_avg': int(s.get('averageHeartRateInBeatsPerMinute', 0) or 0),
        'heart_rate_max': int(s.get('maxHeartRateInBeatsPerMinute', 0) or 0),
        'steps':          steps,
        'elevation':      0,
        'notes':          '',
        'source':         'garmin',
        'external_id':    f"garmin_daily_{date_str}_{s.get('userId','')}"
    }


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE FIT  (OAuth 2.0 + REST API)
# ══════════════════════════════════════════════════════════════════════════════

class GoogleFitClient:
    AUTH_URL    = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL   = "https://oauth2.googleapis.com/token"
    DATASET_URL = "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate"
    SESSIONS_URL = "https://www.googleapis.com/fitness/v1/users/me/sessions"
    SCOPES = [
        "https://www.googleapis.com/auth/fitness.activity.read",
        "https://www.googleapis.com/auth/fitness.heart_rate.read",
        "https://www.googleapis.com/auth/fitness.body.read",
        "https://www.googleapis.com/auth/userinfo.profile"
    ]

    def get_auth_url(self, state='google') -> str:
        params = {
            'client_id':     GOOGLE_CLIENT_ID,
            'redirect_uri':  GOOGLE_REDIRECT_URI,
            'response_type': 'code',
            'scope':         ' '.join(self.SCOPES),
            'access_type':   'offline',
            'prompt':        'consent',
            'state':         state
        }
        return self.AUTH_URL + '?' + urllib.parse.urlencode(params)

    def exchange_code(self, code: str) -> dict:
        resp = requests.post(self.TOKEN_URL, data={
            'client_id':     GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'code':          code,
            'redirect_uri':  GOOGLE_REDIRECT_URI,
            'grant_type':    'authorization_code'
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        expires_at = (datetime.datetime.now() +
                      datetime.timedelta(seconds=data.get('expires_in', 3600))).isoformat()
        # Get user info
        name = ''
        try:
            ui = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                              headers={'Authorization': f"Bearer {data['access_token']}"}, timeout=5)
            name = ui.json().get('name', '')
        except: pass
        token = {
            'access_token':  data['access_token'],
            'refresh_token': data.get('refresh_token', ''),
            'token_type':    data.get('token_type', 'Bearer'),
            'expires_at':    expires_at,
            'scope':         data.get('scope', ''),
            'athlete_id':    '',
            'athlete_name':  name
        }
        save_token('google_fit', token)
        return token

    def _refresh_if_needed(self, tok: dict) -> str:
        expires = tok.get('expires_at', '')
        if expires:
            exp_dt = datetime.datetime.fromisoformat(expires)
            if datetime.datetime.now() >= exp_dt - datetime.timedelta(minutes=5):
                resp = requests.post(self.TOKEN_URL, data={
                    'client_id':     GOOGLE_CLIENT_ID,
                    'client_secret': GOOGLE_CLIENT_SECRET,
                    'refresh_token': tok['refresh_token'],
                    'grant_type':    'refresh_token'
                }, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                tok['access_token'] = data['access_token']
                tok['expires_at']   = (datetime.datetime.now() +
                                       datetime.timedelta(seconds=data.get('expires_in',3600))).isoformat()
                save_token('google_fit', tok)
        return tok['access_token']

    def _headers(self) -> dict:
        tok = get_token('google_fit')
        if not tok: raise ValueError("Google Fit not connected")
        return {'Authorization': f"Bearer {self._refresh_if_needed(tok)}"}

    def sync_activities(self, days_back=30) -> int:
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        start_ms = int((datetime.datetime.now() - datetime.timedelta(days=days_back)).timestamp() * 1000)
        headers = self._headers()

        # 1. Get sessions (workout records)
        resp = requests.get(self.SESSIONS_URL, headers=headers,
                            params={'startTime': f"{start_ms}000000",
                                    'endTime':   f"{now_ms}000000"},
                            timeout=15)
        resp.raise_for_status()
        sessions = resp.json().get('session', [])

        # 2. For each session, fetch aggregated metrics
        imported = 0
        for s in sessions:
            act = _google_session_to_activity(s)
            # Enrich with calories + heart rate from Fitness API
            try:
                payload = {
                    "aggregateBy": [
                        {"dataTypeName": "com.google.calories.expended"},
                        {"dataTypeName": "com.google.heart_rate.bpm"}
                    ],
                    "startTimeMillis": str(int(s['startTimeMillis'])),
                    "endTimeMillis":   str(int(s['endTimeMillis']))
                }
                dr = requests.post(self.DATASET_URL, headers={**headers, 'Content-Type':'application/json'},
                                   json=payload, timeout=10)
                if dr.status_code == 200:
                    buckets = dr.json().get('bucket', [])
                    for b in buckets:
                        for ds in b.get('dataset', []):
                            dtype = ds.get('dataSourceId', '')
                            for pt in ds.get('point', []):
                                val = pt.get('value', [{}])[0]
                                if 'calories' in dtype:
                                    act['calories'] = int(val.get('fpVal', act['calories']))
                                elif 'heart_rate' in dtype:
                                    act['heart_rate_avg'] = int(val.get('fpVal', act['heart_rate_avg']))
            except: pass

            if insert_activity(act, check_duplicate=True): imported += 1

        update_last_sync('google_fit')
        log_sync('google_fit', 'success', imported, f"{imported} new activities")
        return imported


def _google_session_to_activity(s: dict) -> dict:
    ACTIVITY_TYPE_MAP = {
        7: 'cycling', 8: 'cycling', 9: 'cycling',
        56: 'running', 37: 'walking', 16: 'gym',
        82: 'yoga', 17: 'swimming', 19: 'hiking', 15: 'gym'
    }
    at = s.get('activityType', 0)
    mapped = ACTIVITY_TYPE_MAP.get(at, 'other')
    start_ms = int(s.get('startTimeMillis', 0))
    end_ms   = int(s.get('endTimeMillis', 0))
    duration_min = (end_ms - start_ms) // 60000
    date_str = datetime.datetime.fromtimestamp(start_ms/1000).strftime('%Y-%m-%d')
    return {
        'type':           mapped,
        'name':           s.get('name', mapped.title()),
        'date':           date_str,
        'duration':       max(1, duration_min),
        'distance':       0,
        'calories':       0,
        'heart_rate_avg': 0,
        'heart_rate_max': 0,
        'steps':          0,
        'elevation':      0,
        'notes':          s.get('description', '') or '',
        'source':         'google_fit',
        'external_id':    f"gfit_{s['id']}"
    }


# ══════════════════════════════════════════════════════════════════════════════
# APPLE HEALTH  (Local XML export parser)
# ══════════════════════════════════════════════════════════════════════════════

class AppleHealthParser:
    """
    Parse Apple Health XML export.
    User: iPhone → Health App → Profile icon → Export All Health Data → share ZIP.
    Extract the ZIP, find 'export.xml', upload via /api/fitness/apple/import.
    
    Parses: HKWorkout records (actual workouts), HKQuantityTypeIdentifierStepCount,
            HKQuantityTypeIdentifierActiveEnergyBurned, HKQuantityTypeIdentifierHeartRate
    """

    WORKOUT_TYPE_MAP = {
        'HKWorkoutActivityTypeRunning':          'running',
        'HKWorkoutActivityTypeCycling':          'cycling',
        'HKWorkoutActivityTypeWalking':          'walking',
        'HKWorkoutActivityTypeSwimming':         'swimming',
        'HKWorkoutActivityTypeYoga':             'yoga',
        'HKWorkoutActivityTypeTraditionalStrengthTraining': 'gym',
        'HKWorkoutActivityTypeFunctionalStrengthTraining':  'gym',
        'HKWorkoutActivityTypeHighIntensityIntervalTraining': 'gym',
        'HKWorkoutActivityTypeHiking':           'hiking',
        'HKWorkoutActivityTypePilates':          'stretching',
        'HKWorkoutActivityTypeElliptical':       'gym',
        'HKWorkoutActivityTypeStairClimbing':    'gym',
        'HKWorkoutActivityTypeRowing':           'other',
    }

    def parse_file(self, xml_path: str) -> tuple[int, int]:
        """Parse export.xml, insert activities. Returns (total, new)."""
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Index heart rate and energy data by date for enrichment
        hr_by_date: dict[str, list[float]] = {}
        cal_by_date: dict[str, list[float]] = {}
        steps_by_date: dict[str, int] = {}

        for rec in root.iter('Record'):
            rt = rec.get('type', '')
            date = rec.get('startDate', '')[:10]
            if rt == 'HKQuantityTypeIdentifierHeartRate':
                val = float(rec.get('value', 0))
                hr_by_date.setdefault(date, []).append(val)
            elif rt == 'HKQuantityTypeIdentifierActiveEnergyBurned':
                val = float(rec.get('value', 0))
                cal_by_date.setdefault(date, []).append(val)
            elif rt == 'HKQuantityTypeIdentifierStepCount':
                steps_by_date[date] = steps_by_date.get(date, 0) + int(float(rec.get('value', 0)))

        total, new_count = 0, 0
        for workout in root.iter('Workout'):
            total += 1
            wtype = workout.get('workoutActivityType', '')
            mapped = self.WORKOUT_TYPE_MAP.get(wtype, 'other')
            start = workout.get('startDate', '')[:10]
            dur_s = float(workout.get('duration', 0))
            dist_m = float(workout.get('totalDistance', 0) or 0)
            cal = float(workout.get('totalEnergyBurned', 0) or 0)
            # Enrich from indexed data
            if not cal and start in cal_by_date:
                cal = sum(cal_by_date[start])
            hr_list = hr_by_date.get(start, [])
            avg_hr = int(sum(hr_list) / len(hr_list)) if hr_list else 0
            steps = steps_by_date.get(start, 0)
            unit = workout.get('totalDistanceUnit', 'km')
            dist_km = dist_m / 1000 if unit in ('m', 'meter') else dist_m

            act = {
                'type':           mapped,
                'name':           wtype.replace('HKWorkoutActivityType', '').replace('Traditional','').title(),
                'date':           start,
                'duration':       max(1, int(dur_s // 60)),
                'distance':       round(dist_km, 2),
                'calories':       int(cal),
                'heart_rate_avg': avg_hr,
                'heart_rate_max': max(hr_list, default=0),
                'steps':          steps,
                'elevation':      0,
                'notes':          '',
                'source':         'apple_health',
                'external_id':    f"apple_{start}_{wtype}_{int(dur_s)}"
            }
            result = insert_activity(act, check_duplicate=True)
            if result: new_count += 1

        log_sync('apple_health', 'success', new_count, f"Parsed {total} workouts, {new_count} new")
        return total, new_count


# ══════════════════════════════════════════════════════════════════════════════
# Daily Background Sync  (call from APScheduler or a cron job)
# ══════════════════════════════════════════════════════════════════════════════

def sync_all_connected():
    """Sync all connected services. Call daily from scheduler."""
    results = {}
    clients = {
        'strava':     StravaClient(),
        'garmin':     GarminClient(),
        'google_fit': GoogleFitClient()
    }
    for service, client in clients.items():
        tok = get_token(service)
        if not tok: continue
        try:
            count = client.sync_activities(days_back=2)   # daily: last 2 days
            results[service] = {'status': 'ok', 'count': count}
            print(f"[sync] {service}: +{count}")
        except Exception as e:
            log_sync(service, 'error', 0, str(e))
            results[service] = {'status': 'error', 'message': str(e)}
            print(f"[sync] {service} error: {e}")
    return results


# ── Singleton clients ─────────────────────────────────────────────────────────
strava     = StravaClient()
garmin     = GarminClient()
google_fit = GoogleFitClient()
apple      = AppleHealthParser()
