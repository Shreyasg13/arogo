# Arogo on a Raspberry Pi — self-hosting kit

Everything to run Arogo at home on a Pi as the sole user. Full step-by-step
lives in **[../../DEPLOY.md](../../DEPLOY.md) → "Raspberry Pi (self-hosting)"**.

| File | What it is |
|------|------------|
| `arogo-web.service`       | systemd unit — gunicorn web server (`SCHEDULER_ENABLED=0`) |
| `arogo-scheduler.service` | systemd unit — background jobs worker (`SCHEDULER_ENABLED=1`, run on ONE process) |
| `arogo-backup.sh`         | consistent nightly SQLite snapshot, gzipped, 14-day rotation |
| `arogo-backup.service`    | oneshot that runs the backup script |
| `arogo-backup.timer`      | fires the backup nightly at 03:30 |
| `arogo.env.example`       | environment template → copy to `arogo.env`, `chmod 600` |

**Assumptions in the files** (edit if yours differ): user `pi`, app at
`/home/pi/arogo`, venv at `/home/pi/arogo/.venv`, web bound to `127.0.0.1:8000`
behind Tailscale Serve for HTTPS. HTTPS is required — Web Push and the PWA
service worker only work in a secure context.
