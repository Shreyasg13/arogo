# MedEasy — Deploy Checklist

## Required environment (see `.env.example`)

| Variable | Value in production |
|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` — the app **refuses to start** in production mode without it |
| `FLASK_DEBUG` | `0` |
| `COOKIE_SECURE` | `1` (HTTPS only — also enables HSTS) |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/medeasy` |
| `SMTP_HOST/PORT/USER/PASS/FROM` | your SMTP provider (Gmail app password, Brevo, Mailgun…) |
| `APP_BASE_URL` | public URL — used in verification / reset / invite email links |

## PostgreSQL smoke test (do this once before going live)

The PG backend is code-complete but has not been run against a live server
(no Postgres on the dev machine). Verify with a free Neon/Supabase instance:

```bash
export DATABASE_URL=postgresql://...     # from the provider
pip install psycopg2-binary
python app.py                            # expect: [DB] Ready — PostgreSQL
```

Then click through: register → onboarding → log food/sleep/water →
dashboard + progress views → invite a second account to a family group.
All SQL is written in the portable subset both engines accept, but this
click-through is the real confirmation.

## Security posture (current state)

- Sessions: signed HttpOnly cookie, 7-day expiry, `Secure` + HSTS when `COOKIE_SECURE=1`
- CSP is on by default. Known gap: `script-src` includes `'unsafe-inline'`
  because the frontend uses inline `onclick` handlers (CSP nonces don't apply
  to event-handler attributes). Tightening it means refactoring handlers to
  `addEventListener` — tracked as future work.
- Auth rate limiting (10/min/IP) is stored in the database, so it holds
  across multiple workers. Behind a proxy, make sure `X-Forwarded-For`
  is set by the proxy, not the client.
- Scheduler/OAuth sync run per-user based on stored tokens. With more
  than one worker/process, set `SCHEDULER_ENABLED=0` on all but one so
  jobs don't run twice.

## Serving

Use a real WSGI server, not `python app.py`:

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:8000 "app:create_app()"
```

Note: `gunicorn "app:create_app()"` does not run the `__main__` block, so
the background scheduler doesn't start there. Either run the app once as
`python app.py`, or start the scheduler from a separate small process
(`python -c "from db.core import init_db; from scheduler import start_scheduler; import time; init_db(); start_scheduler(); time.sleep(1e9)"`).
