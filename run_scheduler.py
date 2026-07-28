"""
run_scheduler.py — Standalone entrypoint for Arogo's background jobs.

`gunicorn "app:create_app()"` imports the app but never runs app.py's
`__main__` block, so the scheduler (push reminders, caregiver missed-dose
escalation, weekly digests, OAuth sync) does NOT start with the web service.
Run this as ONE separate worker process alongside the web dyno:

    python run_scheduler.py

The Procfile declares it as `worker:`. Keep SCHEDULER_ENABLED=1 on exactly
one process (this one) and 0 elsewhere so jobs don't run twice.
"""
import time

from db.core import init_db
from scheduler import start_scheduler


def main():
    try:
        from observability import init_error_tracking
        init_error_tracking("scheduler")
    except Exception:
        pass
    init_db()
    started = start_scheduler()
    # start_scheduler() no-ops when SCHEDULER_ENABLED=0; if this process is
    # meant to BE the scheduler, that misconfiguration should be loud.
    if started is False:
        raise SystemExit(
            "run_scheduler.py: scheduler is disabled (SCHEDULER_ENABLED=0). "
            "This process exists to run the jobs — set SCHEDULER_ENABLED=1.")
    print("[scheduler] worker process up — jobs running")
    while True:
        time.sleep(3600)


if __name__ == '__main__':
    main()
