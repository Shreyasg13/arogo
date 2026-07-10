# Arogo Health OS

Your personal health operating system — food, sleep, medicines, fitness,
mood and family sharing in one installable web app.

Flask + vanilla JS + SQLite (PostgreSQL-ready), with zero third-party
auth dependencies.

---

## Features

- **Multi-user accounts** — pure-Python auth (PBKDF2 + signed session
  cookies), email verification, password reset, session revocation,
  per-user data isolation across every table
- **Trackers** — food & nutrition (400+ item Indian-leaning food DB,
  TDEE targets), hydration, sleep, mood journal, habits with streaks,
  medicines with dose/stock tracking, symptoms, vitals, body metrics,
  workouts (Strava / Google Fit / Apple Health import)
- **Family sharing** — invite by email; every member controls exactly
  which categories they share (all off by default)
- **Insights** — daily health score, weekly digest (in-app + Sunday
  email), mood×sleep correlation, progress charts, global search
- **PWA** — installable, offline shell, Web Push reminders that fire
  with the tab closed (medicine doses, water pace, evening nudges)
- **Mobile-first** — bottom tab bar layout under 768px, quick-log
  floating button, "water 500" style commands in search

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env        # optional in dev — defaults just work
python app.py               # → http://localhost:5000
```

The SQLite database (`medeasy.db`) and schema are created on first run.
Emails (verification, reset, digest) print to stderr until SMTP_* env
vars are set. See `DEPLOY.md` for the production checklist
(PostgreSQL via DATABASE_URL, gunicorn, HTTPS cookies, CSP).

## Tests

```bash
make test        # Python suite + JS syntax + JS unit tests
pytest tests/    # Python only: API, isolation, family, auth, digest,
                 # push, conventions (security headers, CSP guards)
```

Enable the pre-commit hook once per clone so the full check (~10s)
runs before every commit:

```bash
make hooks       # = git config core.hooksPath .githooks
```

CI runs the same checks on every push (`.github/workflows/test.yml`).
`tests/test_conventions.py` guards project decisions statically — no
inline handlers (strict CSP), no `confirm()`, portable SQL only, no
Linux-only strftime — so regressions fail loudly instead of silently.

## Project structure

```
app.py            # Flask app factory + inline route fallback
config.py         # Env-driven configuration
auth.py           # Sessions, tokens, rate limiting, security headers
mailer.py         # SMTP email (stderr fallback in dev)
push.py           # Web Push via pywebpush (optional dependency)
scheduler.py      # Background jobs: sync, reminders, weekly digest
fitness_sync.py   # Strava / Garmin / Google Fit clients
food_data.py      # Food & nutrition database

db/               # Database layer, one module per domain
  core.py         #   connection (SQLite/PostgreSQL), schema, migrations
  reports|medicines|fitness|food|wellness|health|insights|family.py

routes/           # Flask blueprints mirroring the db/ domains
static/
  js/app.js       # Single-file frontend (no framework)
  css/style.css   # Single-file styles
  sw.js           # Service worker (app shell + push)
  manifest.json   # PWA manifest
templates/
  index.html      # SPA shell
tests/            # pytest suite
```

## Conventions

- New API endpoint: DB function in `db/<domain>.py` → re-export in
  `db/__init__.py` → route in `routes/<domain>.py`. `app.py` stays
  untouched.
- All DB queries are scoped by `current_user_id()`; background jobs
  use `user_context(uid)`.
- No inline `on*=` handlers (strict CSP) — use `data-ev-click` etc.,
  interpreted by the dispatcher at the top of `app.js`.
- SQL sticks to the portable subset SQLite and PostgreSQL both accept.
