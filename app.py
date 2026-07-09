"""
app.py — MedEasy Health OS.

Usage:
    python app.py
"""
import os
from flask import Flask, render_template, send_from_directory
from config import Config

from db.core import init_db


def create_app(config=Config):
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

    @app.after_request
    def apply_security_headers(response):
        try:
            from auth import add_security_headers
            return add_security_headers(response)
        except Exception:
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

    # NOTE: /uploads/<filename> is served by routes/reports.py with
    # authentication AND an ownership check — medical files are private.
    # Never add an unauthenticated file route here.

    @app.route('/sw.js')
    def service_worker():
        # Served from the root path so the service worker scope covers '/'
        return send_from_directory(app.static_folder, 'sw.js',
                                   mimetype='application/javascript')

    return app


if __name__ == '__main__':
    init_db()
    app = create_app()
    try:
        from scheduler import start_scheduler
        start_scheduler()   # honours SCHEDULER_ENABLED=0
    except Exception as e:
        print(f'[scheduler] Not started: {e}')
    app.run(debug=Config.DEBUG, use_reloader=False, host='0.0.0.0', port=5000)
