# Arogo — Deploy Checklist

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
background jobs (push reminders, caregiver missed-dose escalation, weekly
digest, OAuth sync) do **not** start with the web service. They run as ONE
separate worker process — declared in the `Procfile`:

```
web:    gunicorn -w 2 -b 0.0.0.0:$PORT "app:create_app()"
worker: python run_scheduler.py
```

On Heroku the `worker` dyno must be scaled up (`heroku ps:scale worker=1`).
On Render, add a **Background Worker** service with start command
`python run_scheduler.py`. Locally, just run `python run_scheduler.py`
alongside the web process. Keep `SCHEDULER_ENABLED=1` on the worker only
(the web dynos never start it, so they need no change) — `run_scheduler.py`
exits loudly if it's disabled, so a misconfigured worker can't sit there
silently doing nothing.

**Verify it's alive:** `GET /healthz` returns
`{"scheduler": {"ok": true, "age_seconds": N}}` once the worker has run.
`ok:false` (or `last_run:null`) means the worker is down and **no reminders
are firing** — wire this into your uptime monitor.

## Post-deploy checklist

- [ ] Register with a real email → verification email arrives → link works
- [ ] Forgot password → reset email → old session logged out
- [ ] Install the PWA on a phone; grant notifications → water/dose push
      arrives with the tab closed (needs the scheduler worker running)
- [ ] Invite a second account to a family group via email
- [ ] Sunday digest arrives (or trigger `_send_weekly_digests()` manually)
- [ ] Lighthouse run on the live URL
