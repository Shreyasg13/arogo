"""
app.py — Arogo.

Usage:
    python app.py
"""
import os
from flask import Flask, render_template, send_from_directory
from config import Config

from db.core import init_db


def create_app(config=Config):
    # Error tracking first, so failures during app setup are also captured.
    # No-op unless SENTRY_DSN is set (see observability.py).
    try:
        from observability import init_error_tracking
        init_error_tracking("web")
    except Exception:
        pass

    app = Flask(__name__)
    app.config.from_object(config)

    # Refuse to run in production mode with the dev secret — session and
    # email tokens are all signed with SECRET_KEY
    if not app.config.get('DEBUG') and \
            app.config.get('SECRET_KEY') == 'dev-secret-change-in-production':
        raise RuntimeError(
            'SECRET_KEY is not set. Generate one with '
            '"python -c \"import secrets; print(secrets.token_hex(32))\"" '
            'and set it in the environment before running with FLASK_DEBUG=0.')
    app.config['UPLOAD_FOLDER']      = config.UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)


    # ── Register blueprints ───────────────────────────────────────────────────
    # No fallback: a broken import must kill the app, not degrade it.
    # (The old inline-route fallback contained queries that were not scoped
    # per user — failing open would have meant cross-user data exposure.)
    from routes.auth      import bp as auth_bp
    from routes.reports   import bp as reports_bp
    from routes.medicines import bp as medicines_bp
    from routes.fitness   import bp as fitness_bp
    from routes.oauth     import bp as oauth_bp
    from routes.food      import bp as food_bp
    from routes.wellness  import bp as wellness_bp
    from routes.insights  import bp as insights_bp
    from routes.family    import bp as family_bp
    from routes.push      import bp as push_bp
    from routes.labs      import bp as labs_bp
    from routes.expenses  import bp as expenses_bp
    from routes.dependents import bp as dependents_bp
    from routes.goals     import bp as goals_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(medicines_bp)
    app.register_blueprint(fitness_bp)
    app.register_blueprint(oauth_bp)
    app.register_blueprint(food_bp)
    app.register_blueprint(wellness_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(family_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(labs_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(dependents_bp)
    app.register_blueprint(goals_bp)

    @app.before_request
    def _reject_non_object_json():
        # Every route reads a JSON body as `request.json or {}` then `.get(...)`.
        # A top-level JSON array/scalar (e.g. `[1,2]`) is truthy, so it slips past
        # the `or {}` fallback and `.get` raises AttributeError → an unhandled 500.
        # No endpoint accepts a non-object body, so reject it once, centrally.
        from flask import request, jsonify
        if request.is_json:
            body = request.get_json(silent=True)
            if body is not None and not isinstance(body, dict):
                return jsonify({'error': 'Request body must be a JSON object'}), 400

    # ── /api/v1/* aliases ────────────────────────────────────────────────────
    # Mobile clients get a versioned surface without duplicating any code:
    # every /api/ and /auth/ route is also reachable under /api/v1/.
    for rule in list(app.url_map.iter_rules()):
        if rule.rule.startswith('/api/v1/'):
            continue
        if rule.rule.startswith('/api/'):
            alias = '/api/v1' + rule.rule[len('/api'):]
        elif rule.rule.startswith('/auth/'):
            alias = '/api/v1' + rule.rule
        else:
            continue
        app.add_url_rule(alias, endpoint='v1_' + rule.endpoint,
                         view_func=app.view_functions[rule.endpoint],
                         methods=rule.methods - {'HEAD', 'OPTIONS'})

    @app.errorhandler(500)
    def server_error(e):
        from flask import jsonify, request
        if request.path.startswith(('/api/', '/auth/')):
            return jsonify({'error': 'Internal server error'}), 500
        return e

    # ── security.txt (RFC 9116) — where to report a vulnerability ─────────────
    @app.route('/.well-known/security.txt')
    def security_txt():
        import datetime as _dt
        from flask import Response
        contact = os.environ.get('SECURITY_CONTACT', 'mailto:security@arogo.app')
        base = os.environ.get('APP_BASE_URL', 'http://localhost:5000').rstrip('/')
        expires = (_dt.datetime.utcnow() + _dt.timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')
        body = (f"Contact: {contact}\n"
                f"Expires: {expires}\n"
                f"Preferred-Languages: en\n"
                f"Policy: {base}/.well-known/security.txt\n"
                f"# Full policy & breach procedure: SECURITY.md in the Arogo repo\n")
        return Response(body, mimetype='text/plain')

    @app.after_request
    def apply_security_headers(response):
        try:
            from auth import add_security_headers
            return add_security_headers(response)
        except Exception:
            return response

    # ── Response compression (gzip) ───────────────────────────────────────────
    # The biggest first-load latency lever: app.js is ~480KB raw but ~116KB
    # gzipped (4x). Done manually (no dependency) so it also covers Flask's
    # static files, which are sent with direct_passthrough=True and are skipped
    # by flask-compress. In production a reverse proxy (nginx) may gzip instead —
    # this is idempotent (skips already-encoded responses). SVG/JSON/CSS too.
    import gzip as _gzip
    from flask import request as _request
    _COMPRESSIBLE = {
        'text/html', 'text/css', 'text/xml', 'application/xml', 'application/json',
        'application/javascript', 'text/javascript', 'image/svg+xml', 'text/plain',
    }

    @app.after_request
    def compress_response(response):
        try:
            if (response.status_code < 200 or response.status_code >= 300
                    or 'Content-Encoding' in response.headers
                    or 'gzip' not in _request.headers.get('Accept-Encoding', '').lower()):
                return response
            ctype = (response.content_type or '').split(';')[0].strip().lower()
            if ctype not in _COMPRESSIBLE:
                return response
            response.direct_passthrough = False          # materialize static files
            data = response.get_data()
            if len(data) < 1024:                         # not worth it for tiny bodies
                return response
            response.set_data(_gzip.compress(data, 6))
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(response.get_data()))
            vary = response.headers.get('Vary', '')
            if 'accept-encoding' not in vary.lower():
                response.headers['Vary'] = (vary + ', Accept-Encoding').lstrip(', ')
        except Exception:
            pass
        return response

    # Return JSON for 404s instead of HTML (prevents JSON.parse errors)
    @app.errorhandler(404)
    def not_found(e):
        from flask import jsonify, request
        if request.path.startswith('/api/') or request.path.startswith('/auth/'):
            return jsonify({'error': 'Route not found', 'path': request.path}), 404
        return e

    @app.errorhandler(405)
    def method_not_allowed(e):
        from flask import jsonify, request
        if request.path.startswith('/api/') or request.path.startswith('/auth/'):
            return jsonify({'error': 'Method not allowed'}), 405
        return e

    @app.route('/')
    def index():
        return render_template('index.html')

    # Public transparency page — readable before sign-up (no ads / no data sale /
    # what every number means). Intentionally unauthenticated; carries no user data.
    @app.route('/how-it-works')
    def how_it_works():
        return render_template('how_it_works.html')

    # NOTE: /uploads/<filename> is served by routes/reports.py with
    # authentication AND an ownership check — medical files are private.
    # Never add an unauthenticated file route here.

    # ── Service worker + shell assets (content-versioned, minified in prod) ────
    # Serve the SW from the root path so its scope covers '/'. The CACHE_VERSION
    # baked into it is a content hash of the shell files (see assets.py), so the
    # SW changes on every deploy and the browser drops the stale cache — no more
    # hand-bumping a version string and forgetting to. In production the same
    # hash powers minified app.js/style.css served from their usual paths; in
    # debug we leave the raw files to Flask's static handler so edits are live
    # and the source stays debuggable.
    import re as _re
    from flask import request as _req
    import assets as _assets

    _MINIFY = not app.config.get('DEBUG')

    @app.route('/sw.js')
    def service_worker():
        b = _assets.build_bundle(app.static_folder, _MINIFY)
        js = _re.sub(r"const CACHE_VERSION = '[^']*';",
                     "const CACHE_VERSION = 'arogo-%s';" % b['version'],
                     b['sw_src'], count=1)
        resp = app.response_class(js, mimetype='application/javascript')
        # The SW file itself must always be revalidated, or a cached sw.js would
        # hide the very update it exists to deliver.
        resp.headers['Cache-Control'] = 'no-cache'
        resp.headers['Service-Worker-Allowed'] = '/'
        return resp

    if _MINIFY:
        def _shell_asset(body, mimetype, version):
            resp = app.response_class(body, mimetype=mimetype)
            resp.set_etag(version)              # 304 on repeat loads when unchanged
            resp.headers['Cache-Control'] = 'public, max-age=0, must-revalidate'
            return resp.make_conditional(_req)

        # These string routes are more specific than Flask's /static/<path:…>,
        # so they win — the SW shell + index.html keep referencing the same URLs.
        @app.route('/static/js/app.js')
        def _shell_app_js():
            b = _assets.build_bundle(app.static_folder, _MINIFY)
            return _shell_asset(b['app_js'], 'application/javascript', b['version'])

        @app.route('/static/css/style.css')
        def _shell_style_css():
            b = _assets.build_bundle(app.static_folder, _MINIFY)
            return _shell_asset(b['css'], 'text/css', b['version'])

    # ── Liveness / scheduler health ───────────────────────────────────────────
    # The reminder + caregiver-escalation jobs run in a SEPARATE worker process
    # (see run_scheduler.py). If that worker dies, reminders stop silently — the
    # web service can't see the thread, but it can read the heartbeat the worker
    # writes every minute. Surface it so an uptime check (or a human) can catch a
    # dead scheduler instead of discovering it via a missed dose.
    @app.route('/healthz')
    def healthz():
        import datetime as _dt
        from flask import jsonify
        from db.core import execute
        # scheduler considered healthy if it wrote its heartbeat recently.
        # Jobs tick at 5 min and the heartbeat at 1 min; 15 min is a generous
        # "definitely stalled" threshold that won't flap on a slow tick.
        STALE_AFTER_S = 15 * 60
        last, age = None, None
        try:
            row = execute("SELECT value FROM app_config WHERE key='scheduler_last_run'",
                          fetchone=True)
            if row and row['value']:
                last = row['value']
                delta = _dt.datetime.now() - _dt.datetime.fromisoformat(last)
                age = int(delta.total_seconds())
        except Exception:
            pass
        sched_ok = age is not None and age <= STALE_AFTER_S
        return jsonify({
            'status': 'ok',                       # the web process answered
            'scheduler': {
                'ok': sched_ok,
                'last_run': last,                 # None until the worker runs once
                'age_seconds': age,
                'stale_after_seconds': STALE_AFTER_S,
            },
        }), 200

    return app


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5000)))
    args = ap.parse_args()

    init_db()
    app = create_app()
    try:
        from scheduler import start_scheduler
        start_scheduler()   # honours SCHEDULER_ENABLED=0
    except Exception as e:
        print(f'[scheduler] Not started: {e}')
    app.run(debug=Config.DEBUG, use_reloader=False, host='0.0.0.0', port=args.port)
