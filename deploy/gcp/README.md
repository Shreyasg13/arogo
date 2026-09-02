# Arogo on GCP `e2-micro` — self-hosting kit

Everything to run Arogo on a Google Cloud "Always Free" `e2-micro` VM,
publicly reachable over HTTPS on your own domain. Full step-by-step lives
in **[../../DEPLOY.md](../../DEPLOY.md) → "Google Cloud (GCP e2-micro,
self-hosting)"**.

| File | What it is |
|------|------------|
| `provision.sh`           | One-time setup: creates the `arogo` user, installs Python/Caddy, clones the repo, builds the venv |
| `arogo-web.service`      | systemd unit — gunicorn web server (`SCHEDULER_ENABLED=0`) |
| `arogo-scheduler.service`| systemd unit — background jobs worker (`SCHEDULER_ENABLED=1`, run on ONE process) |
| `Caddyfile`               | Reverse proxy — automatic Let's Encrypt HTTPS, no certbot/cron needed |
| `arogo.env.example`      | Environment template → copy to `arogo.env`, `chmod 600` |

**Assumptions in the files** (edit if yours differ): dedicated user
`arogo`, app at `/home/arogo/arogo`, venv at `/home/arogo/arogo/.venv`,
gunicorn bound to `127.0.0.1:8000` behind Caddy. Unlike
[`deploy/pi/`](../pi/), this path assumes an external managed Postgres
(Neon/Supabase free tier) rather than local SQLite — the VM only has 1GB
RAM, so keeping the database off-box leaves more of it for the app.
