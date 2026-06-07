"""
scheduler.py — Background job runner
Uses Python's threading + schedule library (stdlib-only fallback).
If APScheduler is available it uses that instead.

Jobs:
  - sync_all_connected() : every day at 05:00
  - check_missed_doses()  : every hour
"""
import threading, time, datetime, os
from database import get_today_doses, log_sync, get_sync_history

_scheduler_thread = None

def _daily_sync():
    try:
        from fitness_sync import sync_all_connected
        results = sync_all_connected()
        print(f"[scheduler] Daily sync: {results}")
    except Exception as e:
        print(f"[scheduler] Daily sync error: {e}")

def _check_missed_doses():
    try:
        doses = get_today_doses()
        now = datetime.datetime.now().strftime('%H:%M')
        missed = [d for d in doses if not d['taken'] and d['time'] < now]
        if missed:
            print(f"[scheduler] {len(missed)} missed dose(s) as of {now}")
    except Exception as e:
        print(f"[scheduler] Missed dose check error: {e}")

def _run_loop():
    import schedule
    schedule.every().day.at("05:00").do(_daily_sync)
    schedule.every().hour.do(_check_missed_doses)
    # Also do an initial sync 30 s after startup
    schedule.every(30).seconds.do(lambda: (schedule.cancel_job(schedule.jobs[-1]), _daily_sync()))
    while True:
        schedule.run_pending()
        time.sleep(30)

def _run_loop_stdlib():
    """Fallback scheduler using plain threading when 'schedule' isn't available."""
    last_daily = None
    while True:
        now = datetime.datetime.now()
        if now.hour == 5 and now.minute == 0:
            day_key = now.date().isoformat()
            if last_daily != day_key:
                _daily_sync()
                last_daily = day_key
        if now.minute == 0:
            _check_missed_doses()
        time.sleep(60)

def start_scheduler():
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    try:
        import schedule
        runner = _run_loop
    except ImportError:
        runner = _run_loop_stdlib

    _scheduler_thread = threading.Thread(target=runner, daemon=True, name='mediscan-scheduler')
    _scheduler_thread.start()
    print("[scheduler] Started")
