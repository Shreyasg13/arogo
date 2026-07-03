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
- Auth routes are rate-limited in-process (10/min/IP). Behind a proxy, make
  sure `X-Forwarded-For` is set by the proxy, not the client.
- Scheduler/OAuth sync run per-user based on stored tokens.

## Serving

Use a real WSGI server, not `python app.py`:

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:8000 "app:create_app()"
```

Note: the in-memory rate limiter and reminder scheduler are per-process;
keep workers low (or move rate limiting to the proxy) until they're
externalized.
