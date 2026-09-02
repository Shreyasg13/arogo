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

Schema added since then (menstrual_cycles table; the language, schedule_days,
interval_days and allow_manage columns + migrations) was re-audited for
Postgres on 2026-08-03: portable `ALTER TABLE … ADD COLUMN` DDL guarded by
try/except, `?`-parameterized queries (execute() rewrites to `%s`), all date
formatting done in Python, no SQLite-only SQL (`strftime`/`INSERT OR REPLACE`/
`GROUP_CONCAT`/inline `LIKE '%…%'`). No cross-engine risks found.

## Deploying on Render (recommended — one blueprint)

1. Push the repo, then on render.com: **New + → Blueprint** → select the
   repo. `render.yaml` provisions the web service and a free PostgreSQL
   database, generates `SECRET_KEY`, and sets the hardening env vars.
2. After the first deploy, set in the dashboard: `APP_BASE_URL` (the
   public URL Render assigned) and `SMTP_HOST/USER/PASS/FROM`.
3. Redeploy. Done — HTTPS, CSP, secure cookies all active.

### CI-gated auto-deploy

Both services are `autoDeploy: false`, so Render never deploys a commit on
its own — `.github/workflows/deploy.yml` triggers the deploy, and only
after `.github/workflows/test.yml` (SQLite + PostgreSQL suites, JS tests)
passes on `main`.

One-time setup (needs dashboard access — can't be scripted):

1. On each service in the Render dashboard: **Settings → Deploy Hook** →
   copy the URL.
2. In the GitHub repo: **Settings → Secrets and variables → Actions**,
   add `RENDER_DEPLOY_HOOK_WEB` and `RENDER_DEPLOY_HOOK_WORKER` with those
   two URLs.

From then on, every green run of the test workflow on `main` deploys both
services; a red run deploys nothing.

For Railway/Fly, the `Procfile` covers the start command; supply the
same env vars from the table above.

## Raspberry Pi (self-hosting)

Run Arogo at home on a Pi as the sole user. SQLite is the default and the right
choice here — no database server to run. The ready-made units and scripts are in
[`deploy/pi/`](deploy/pi/); the files assume user `pi` and app dir
`/home/pi/arogo` (edit if yours differ).

**Why Tailscale:** Web Push and the PWA service worker only work over HTTPS (a
"secure context"). [Tailscale](https://tailscale.com) gives your Pi an HTTPS URL
on your private tailnet with zero port-forwarding or certificates — reach it from
your phone anywhere, and nobody else can.

### 1. Get the code and dependencies

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone <your-repo-url> /home/pi/arogo
cd /home/pi/arogo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Configure the environment

```bash
cp deploy/pi/arogo.env.example arogo.env
python3 -c "import secrets; print(secrets.token_hex(32))"   # paste as SECRET_KEY
nano arogo.env        # set SECRET_KEY and (after step 3) APP_BASE_URL
chmod 600 arogo.env   # it holds your secret key
```

### 3. HTTPS with Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8000          # proxy https://<pi>.<tailnet>.ts.net → :8000
tailscale serve status                  # copy the https URL
```

Put that URL in `arogo.env` as `APP_BASE_URL`.

### 4. Install the systemd services

```bash
sudo cp deploy/pi/arogo-web.service deploy/pi/arogo-scheduler.service /etc/systemd/system/
chmod +x deploy/pi/arogo-backup.sh
sudo systemctl daemon-reload
sudo systemctl enable --now arogo-web.service arogo-scheduler.service
```

The **web** unit runs gunicorn with `SCHEDULER_ENABLED=0`; the **scheduler** unit
runs `run_scheduler.py` with `SCHEDULER_ENABLED=1`. Keep the scheduler on exactly
one process so jobs never double-fire.

### 5. Nightly backups

```bash
sudo cp deploy/pi/arogo-backup.service deploy/pi/arogo-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arogo-backup.timer
sudo systemctl start arogo-backup.service    # test it once now
ls -lh /home/pi/arogo-backups                # gzipped snapshot appears
```

Snapshots are crash-consistent (SQLite online backup) and rotate after 14 days.
Copy `arogo-backups/` off the Pi periodically — an SD card is a single point of
failure. You can also pull a one-file backup any time from **Data → Backup &
restore** in the app.

### 6. Verify

```bash
curl -s http://127.0.0.1:8000/healthz          # {"status":"ok","scheduler":{"ok":true,...}}
journalctl -u arogo-web -u arogo-scheduler -f  # live logs
```

Open the Tailscale HTTPS URL on your phone, add to home screen, grant
notifications → a dose/water push should arrive with the app closed.

### Updating

```bash
cd /home/pi/arogo && git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart arogo-web arogo-scheduler
```

## Google Cloud (GCP e2-micro, self-hosting)

Run Arogo on a Google Cloud `e2-micro` — the "Always Free" tier's VM
(permanent, not a trial), publicly reachable on your own domain. The
ready-made units and scripts are in [`deploy/gcp/`](deploy/gcp/); the
files assume a dedicated `arogo` user and app dir `/home/arogo/arogo`
(edit if yours differ).

Unlike the Raspberry Pi kit, this path keeps the database off the VM
entirely — an `e2-micro` only has 1GB RAM, so a free managed Postgres
(Neon or Supabase both work) leaves that RAM for the app instead of a
local database server. Public HTTPS comes from Caddy + Let's Encrypt
instead of Tailscale, since this VM is meant to be reachable by family
members without installing anything extra.

### 1. Create the VM

Always Free eligibility requires one of `us-west1`, `us-central1`, or
`us-east1`. Run this yourself (needs your own GCP project/auth):

```bash
gcloud compute instances create arogo \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud
gcloud compute addresses create arogo-ip --region=us-central1
gcloud compute instances add-access-config arogo --zone=us-central1-a \
  --address="$(gcloud compute addresses describe arogo-ip --region=us-central1 --format='value(address)')"
gcloud compute firewall-rules create arogo-http --allow=tcp:80,tcp:443
```

Point your domain's `A` record at that static IP.

### 2. Get a free Postgres database

Create a project on [Neon](https://neon.tech) or [Supabase](https://supabase.com)
(both free-tier, no card required) and copy the connection string — this is
a manual dashboard step, same as the SMTP setup below.

### 3. Provision the VM

```bash
gcloud compute ssh arogo --zone=us-central1-a
# on the VM:
git clone <your-repo-url> /tmp/arogo-repo   # just to grab deploy/gcp/ before the real clone
AROGO_REPO_URL=<your-repo-url> bash /tmp/arogo-repo/deploy/gcp/provision.sh
```

### 4. Configure and start

```bash
cp deploy/gcp/arogo.env.example /home/arogo/arogo/arogo.env
python3 -c "import secrets; print(secrets.token_hex(32))"   # paste as SECRET_KEY
sudo -u arogo nano /home/arogo/arogo/arogo.env   # SECRET_KEY, DATABASE_URL, APP_BASE_URL
sudo chmod 600 /home/arogo/arogo/arogo.env

sudo cp deploy/gcp/arogo-web.service deploy/gcp/arogo-scheduler.service /etc/systemd/system/
sudo cp deploy/gcp/Caddyfile /etc/caddy/Caddyfile   # edit the domain first
sudo systemctl daemon-reload
sudo systemctl enable --now arogo-web arogo-scheduler caddy
```

### 5. Verify

```bash
curl -s https://arogo.yourdomain.com/healthz   # {"status":"ok","scheduler":{"ok":true,...}}
journalctl -u arogo-web -u arogo-scheduler -f  # live logs
```

DB backups on this path are the Postgres provider's job — Neon and
Supabase both offer point-in-time recovery on their free tiers, so unlike
the Pi kit there's no local backup script here (no local SQLite file to
snapshot).

### Updating

```bash
sudo -u arogo git -C /home/arogo/arogo pull
sudo -u arogo /home/arogo/arogo/.venv/bin/pip install -r /home/arogo/arogo/requirements.txt
sudo systemctl restart arogo-web arogo-scheduler
```

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
- [ ] `GET /healthz` shows `scheduler.ok: true`
- [ ] `python scripts/backup.py backup` succeeds; a daily backup + off-box copy
      is scheduled (SQLite disks are ephemeral on Render free tier)
- [ ] (optional) `SENTRY_DSN` set → force a test error and confirm it lands,
      scrubbed of request/PII

## Operations

Day-2 operations — health checks, the backup/restore drill, error tracking, and
the quiet failure modes — live in **[RUNBOOK.md](RUNBOOK.md)**.
