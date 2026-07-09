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

## PostgreSQL status: VALIDATED ✅

The full test suite (175 tests — every API, isolation, family, auth,
digest, push and token flow) passes against a real PostgreSQL 16 server
(verified 2026-07-08 with portable binaries). Setting `DATABASE_URL`
is all it takes to switch backends.

## Deploying on Render (recommended — one blueprint)

1. Push the repo, then on render.com: **New + → Blueprint** → select the
   repo. `render.yaml` provisions the web service and a free PostgreSQL
   database, generates `SECRET_KEY`, and sets the hardening env vars.
2. After the first deploy, set in the dashboard: `APP_BASE_URL` (the
   public URL Render assigned) and `SMTP_HOST/USER/PASS/FROM`.
3. Redeploy. Done — HTTPS, CSP, secure cookies all active.

For Railway/Fly, the `Procfile` covers the start command; supply the
same env vars from the table above.

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

## Scheduler under gunicorn

`gunicorn "app:create_app()"` does not run the `__main__` block, so the
background jobs (push reminders, caregiver alerts, weekly digest, OAuth
sync) don't start with the web service. Run them as ONE separate small
process (a Render background worker, or locally):

```bash
python -c "from db.core import init_db; from scheduler import start_scheduler; import time; init_db(); start_scheduler(); time.sleep(1e9)"
```

## Post-deploy checklist

- [ ] Register with a real email → verification email arrives → link works
- [ ] Forgot password → reset email → old session logged out
- [ ] Install the PWA on a phone; grant notifications → water/dose push
      arrives with the tab closed (needs the scheduler worker running)
- [ ] Invite a second account to a family group via email
- [ ] Sunday digest arrives (or trigger `_send_weekly_digests()` manually)
- [ ] Lighthouse run on the live URL
