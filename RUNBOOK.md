# Arogo — Operations Run-book

What to do when something breaks in production. Deploy setup lives in
[DEPLOY.md](DEPLOY.md); this file is for **running** it.

## Architecture at a glance

| Piece | What it is | If it's down |
|-------|-----------|--------------|
| **web** | `gunicorn "app:create_app()"` — serves the app + API | Users see errors / can't load the app |
| **scheduler** | `python run_scheduler.py` — ONE worker process running the background jobs | **No reminders, no missed-dose escalation, no digests** — silently |
| **database** | SQLite file (`MEDEASY_DB`) or PostgreSQL (`DATABASE_URL`) | Everything is down |

The web and scheduler are **separate processes** and share one database and
`SECRET_KEY`. On Render both are declared in `render.yaml`.

---

## 1. Is the safety net alive? — `/healthz`

```bash
curl -s https://<your-app>/healthz | python -m json.tool
```

```json
{ "status": "ok",
  "scheduler": { "ok": true, "last_run": "...", "age_seconds": 42,
                 "stale_after_seconds": 900 } }
```

- `status: ok` → the **web** process is up.
- `scheduler.ok: true` → the worker wrote its heartbeat within the last 15 min.
- `scheduler.ok: false` or `last_run: null` → **the scheduler is down and no
  reminders are firing.** This is the alert that matters — wire `/healthz` into
  your uptime monitor (UptimeRobot, Render health check, etc.).

**Scheduler is down — fix it:**
1. Confirm the `medeasy-scheduler` worker service is running (Render dashboard →
   the worker → Logs). Look for `[scheduler] worker process up`.
2. If it exited immediately with *"scheduler is disabled (SCHEDULER_ENABLED=0)"*,
   set `SCHEDULER_ENABLED=1` on the **worker** (only the worker).
3. If it's crash-looping, read the logs / Sentry (below) for the traceback.
4. Restart the worker. `/healthz` should flip to `ok:true` within ~1 minute.

> Only ONE process may have `SCHEDULER_ENABLED=1`. Two schedulers = double
> reminders and double escalation. Web dynos stay at `0`.

---

## 2. Error tracking (Sentry) — optional

Set `SENTRY_DSN` (shared env group) to turn it on; blank = a complete no-op.
Health data and PII are scrubbed before any event leaves the process (no request
bodies, no user identity — see `observability.py`). Events are tagged
`component=web` or `component=scheduler` so you can tell which process failed.
Background-job failures are reported via `_report()` in `scheduler.py`, so a
swallowed job error still surfaces instead of dying in worker stderr.

No Sentry? The same errors are in the process logs — just less searchable.

---

## 3. Backups & restore

`scripts/backup.py` auto-detects the backend (Postgres if `DATABASE_URL` is set,
else the SQLite file). **SQLite** uses the online backup API (safe on a live DB);
**Postgres** shells out to `pg_dump`/`pg_restore` (install `postgresql-client`).

```bash
python scripts/backup.py backup            # write backups/medeasy-<stamp>.(sqlite|dump)
python scripts/backup.py list              # show existing backups
python scripts/backup.py restore <path>    # restore (prompts; --yes to skip)
```

**Schedule it** (daily, keep ~30 days). Example cron on the host:
```bash
0 3 * * *  cd /app && python scripts/backup.py backup --out /data/backups
```
Then copy `/data/backups` off-box (object storage) — a backup on the same disk
dies with the disk. On Render free tier the disk is ephemeral, so off-box copy
is not optional. Render Postgres also has its own managed backups; treat this
script as the portable, restore-tested second copy.

### Restore drill (run this quarterly — an untested backup is a rumour)
1. `python scripts/backup.py backup` — take a fresh one.
2. Restore it into a scratch DB and boot against it:
   ```bash
   MEDEASY_DB=/tmp/restore-test.db python scripts/backup.py restore backups/<file> --yes
   MEDEASY_DB=/tmp/restore-test.db python -c "from db.core import execute; \
     print('users:', execute('SELECT count(*) c FROM users', fetchone=True)['c'])"
   ```
3. Confirm the row counts look right. On SQLite a real restore also writes a
   `*.pre-restore-<stamp>` snapshot of the DB it replaced — keep it until you've
   verified the restore.

---

## 4. Failure modes that fail *quietly* (know these)

| Symptom | Cause | Where it shows |
|---------|-------|----------------|
| Digests say **"ready"** not "emailed" | `SMTP_*` not configured | By design — `mailer.is_configured()` gates the wording so we never claim an email we didn't send |
| No push notifications at all | `pywebpush` missing or VAPID unset | `push.PUSH_AVAILABLE` is False; app runs, push is a no-op |
| Caregiver alerts not arriving | nobody subscribed / SMTP down / no SMS contacts | The member is told *"couldn't reach your family"*, and the escalation **retries each tick** until someone is reached (it is NOT marked done) |
| Per-user "today" looks like the server's day | `tzdata` missing → `zoneinfo` falls back to server tz | Pinned in `requirements.txt`; if you slim deps, keep it |
| Reminders stopped entirely | scheduler worker down | `/healthz` → `scheduler.ok:false` |

---

## 5. Deploy & rollback

- **Deploy:** push to the tracked branch; Render rebuilds `web` + `scheduler`
  from `render.yaml`. Migrations are idempotent `ALTER TABLE … ` guards run at
  boot (`init_db`), so a redeploy is safe.
- **Rollback:** redeploy the previous commit from the Render dashboard. Because
  migrations only ever ADD columns, an older image keeps working against the
  newer schema. If a deploy changed data, restore from the pre-deploy backup.
- **Secrets:** rotating `SECRET_KEY` logs everyone out and invalidates
  outstanding email/verification/unsubscribe links. Rotate deliberately.
