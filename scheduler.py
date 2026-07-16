"""
scheduler.py — Background job runner
Uses Python's threading + schedule library (stdlib-only fallback).
If APScheduler is available it uses that instead.

Jobs:
  - sync_all_connected() : every day at 05:00
  - check_missed_doses()  : every hour
"""
import threading, time, datetime, os
from db import get_today_doses, log_sync, get_sync_history, execute, user_context

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
        now = datetime.datetime.now().strftime('%H:%M')
        users = execute("SELECT DISTINCT user_id FROM medicines WHERE active=1", fetchall=True)
        total_missed = 0
        for u in users:
            with user_context(u['user_id']):
                doses = get_today_doses()
                total_missed += len([d for d in doses if not d['taken'] and d['time'] < now])
        if total_missed:
            print(f"[scheduler] {total_missed} missed dose(s) as of {now}")
    except Exception as e:
        print(f"[scheduler] Missed dose check error: {e}")

# ── Server-sent push reminders (works with the browser tab closed) ───────────

def _user_local_now(uid):
    """Current datetime in the user's profile timezone (server tz fallback)."""
    try:
        from db.food import get_user_timezone
        tz = get_user_timezone()
        if tz:
            import zoneinfo
            return datetime.datetime.now(zoneinfo.ZoneInfo(tz))
    except Exception:
        pass
    return datetime.datetime.now()


def _mins_since(hhmm, now_hhmm):
    """Minutes from hhmm to now_hhmm, or None if unparsable."""
    try:
        h1, m1 = map(int, hhmm.split(':'))
        h2, m2 = map(int, now_hhmm.split(':'))
        return (h2 * 60 + m2) - (h1 * 60 + m1)
    except Exception:
        return None


def _pushed_today(uid, key, today):
    return execute(
        "SELECT 1 FROM notification_log WHERE user_id=? AND source_id=? AND created_at>=? LIMIT 1",
        (uid, key, today), fetchone=True)


def _mark_pushed(uid, key, title, body):
    from db.core import new_id, now_iso
    execute("""INSERT INTO notification_log (id,type,title,body,source_id,read,created_at,user_id)
               VALUES (?,?,?,?,?,0,?,?)""",
            (new_id(), 'push', title, body, key, now_iso(), uid), commit=True)


def _push_reminders_for_user(uid):
    import push
    from db import get_today_doses
    from db.wellness import get_hydration_day

    now = _user_local_now(uid)
    today, hhmm = now.strftime('%Y-%m-%d'), now.strftime('%H:%M')
    rs = execute("SELECT * FROM reminder_settings WHERE user_id=? LIMIT 1",
                 (uid,), fetchone=True) or {}

    def notify(key, title, body):
        if _pushed_today(uid, key, today):
            return
        if push.push_to_user(uid, title, body):
            _mark_pushed(uid, key, title, body)

    # 1. Medicine doses that came due in the last 15 minutes and aren't taken
    for d in get_today_doses():
        if d.get('taken'):
            continue
        mins = _mins_since(d.get('time') or '', hhmm)
        if mins is not None and 0 <= mins <= 15:
            notify(f"med:{d['med_id']}:{d['time']}:{today}",
                   f"💊 Time for {d.get('med_name', 'your medicine')}",
                   f"Scheduled at {d['time']}" + (' · take with food' if d.get('with_food') else ''))

    # 2. Water — only when enabled, inside the active window, and behind pace
    if rs.get('water_enabled'):
        start, end = rs.get('water_start') or '08:00', rs.get('water_end') or '21:00'
        if start <= hhmm <= end:
            interval_h = float(rs.get('water_interval_h') or 2.0)
            day = get_hydration_day(today)
            goal = rs.get('water_goal_ml') or day.get('goal_ml') or 2450
            s_mins = _mins_since('00:00', start) or 0
            e_mins = _mins_since('00:00', end) or 1
            n_mins = _mins_since('00:00', hhmm) or 0
            window = max(e_mins - s_mins, 1)
            expected = goal * min(max((n_mins - s_mins) / window, 0), 1)
            if day.get('total_ml', 0) < expected * 0.8:
                bucket = int((n_mins - s_mins) / max(int(interval_h * 60), 30))
                remaining = int(goal - day.get('total_ml', 0))
                notify(f"water:{today}:{bucket}",
                       '💧 Hydration check',
                       f"You're behind on water — about {remaining}ml to go today.")

    # 3. Evening habit / sleep / mood nudges at their configured times
    for flag, tkey, key, title, body in [
        ('habit_reminder_enabled', 'habit_reminder_time', 'habit',
         '⭐ Evening habit check', 'Tick off what you completed today.'),
        ('sleep_reminder_enabled', 'sleep_reminder_time', 'sleep',
         '🌙 Wind-down time', "Log last night's sleep and get ready for bed."),
        ('mood_reminder_enabled', 'mood_reminder_time', 'mood',
         '😊 How was your day?', 'A one-line journal entry keeps the streak alive.'),
    ]:
        if rs.get(flag):
            mins = _mins_since(rs.get(tkey) or '', hhmm)
            if mins is not None and 0 <= mins <= 15:
                notify(f"{key}:{today}", title, body)


def _push_reminders():
    try:
        import push
        if not push.PUSH_AVAILABLE:
            return
        users = execute("SELECT DISTINCT user_id FROM push_subscriptions", fetchall=True)
        for u in users:
            with user_context(u['user_id']):
                try:
                    _push_reminders_for_user(u['user_id'])
                except Exception as e:
                    print(f"[scheduler] push reminders for {u['user_id'][:8]}: {e}")
    except Exception as e:
        print(f'[scheduler] Push reminder error: {e}')


# ── Caregiver alerts: tell the family when a dose is 2h+ overdue ─────────────

SELF_CORRECT_MIN = 60     # give the member a chance before family is told
ESCALATE_MIN     = 120    # then alert the family


def _caregiver_alerts():
    """Escalation ladder for opted-in members who share medicines — designed so
    the member keeps agency and is never monitored covertly:

      • dose time      → the member's own reminder (see _push_reminders_for_user)
      • ~60m overdue   → a stronger nudge to the MEMBER ONLY, warning that family
                         will be told soon (a chance to self-correct first)
      • ~120m overdue  → alert the rest of the family, AND tell the member we did
                         (transparency)

    Deduped per dose per day via the member's notification_log."""
    try:
        import push
        import mailer
        watched = execute("""
            SELECT m.user_id, m.group_id, u.name, u.email FROM family_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.alert_missed_doses=1 AND m.share_medicines=1""", fetchall=True)
        for w in watched:
            uid = w['user_id']
            try:
                with user_context(uid):
                    from db import get_today_doses
                    now = _user_local_now(uid)
                    today, hhmm = now.strftime('%Y-%m-%d'), now.strftime('%H:%M')
                    doses = get_today_doses()
                untaken = [(d, _mins_since(d.get('time') or '', hhmm) or 0)
                           for d in doses if not d.get('taken')]

                # ── Rung 1: self-correct nudge (the member only) ──
                for d, mins in untaken:
                    if not (SELF_CORRECT_MIN <= mins < ESCALATE_MIN):
                        continue
                    key = f"selfnudge:{d['med_id']}:{d['time']}:{today}"
                    if _pushed_today(uid, key, today):
                        continue
                    title = f"⏰ Don't forget {d.get('med_name', 'your medicine')}"
                    body = (f"It was due at {d['time']}. Take it now — if it stays "
                            f"unlogged, your family will get a heads-up soon.")
                    if push.push_to_user(uid, title, body, '/'):
                        _mark_pushed(uid, key, title, body)

                # ── Rung 2: escalate to family, and tell the member ──
                for d, mins in untaken:
                    if mins < ESCALATE_MIN:
                        continue
                    key = f"caregiver:{d['med_id']}:{d['time']}:{today}"
                    if _pushed_today(uid, key, today):
                        continue
                    name = w['name'] or w['email']
                    med  = d.get('med_name', 'A medicine')
                    title = f"🚨 {name} missed a dose"
                    body = (f"{med} was scheduled at {d['time']} and hasn't been "
                            f"marked as taken.")
                    others = execute("""
                        SELECT u.id, u.email, u.name FROM family_members m
                        JOIN users u ON u.id = m.user_id
                        WHERE m.group_id=? AND m.user_id<>?""",
                        (w['group_id'], uid), fetchall=True)
                    for o in others:
                        push.push_to_user(o['id'], title, body, '/')
                        mailer.send_email(
                            o['email'], title,
                            f"Hi {o['name'] or 'there'},\n\n{body}\n\n"
                            f"They opted in to these alerts so you can check on them.\n"
                            f"Open Arogo: {mailer.APP_BASE_URL}/\n")
                    # Transparency: the member always learns when family is told.
                    # Log THIS honest message to the member's own feed (also the
                    # dedup record), not the third-person "X missed a dose".
                    tp_title = "We let your family know"
                    tp_body  = (f"{med} ({d['time']}) is still unlogged, so your family "
                                f"was notified. Take it and this clears.")
                    push.push_to_user(uid, tp_title, tp_body, '/')
                    _mark_pushed(uid, key, tp_title, tp_body)
            except Exception as e:
                print(f"[scheduler] caregiver alert for {uid[:8]}: {e}")
    except Exception as e:
        print(f'[scheduler] Caregiver alert error: {e}')


def _send_weekly_digests():
    """Email the weekly digest to every opted-in user (Sunday evenings).
    Deduped per user per week via notification_log."""
    import datetime as dt
    try:
        import mailer
        from auth import make_digest_unsub_token
        from db.insights import generate_weekly_digest
        week_ago = (dt.datetime.now() - dt.timedelta(days=6)).isoformat()
        users = execute("""
            SELECT u.id, u.email, u.name FROM users u
            LEFT JOIN reminder_settings rs ON rs.user_id = u.id
            WHERE COALESCE(rs.weekly_digest_enabled, 1) = 1
        """, fetchall=True)
        sent = 0
        for u in users:
            already = execute(
                "SELECT 1 FROM notification_log WHERE user_id=? AND type='digest_email' AND created_at >= ? LIMIT 1",
                (u['id'], week_ago), fetchone=True)
            if already:
                continue
            with user_context(u['id']):
                digest = generate_weekly_digest()
                unsub = f"{mailer.APP_BASE_URL}/api/digest/unsubscribe/{make_digest_unsub_token(u['id'])}"
                if mailer.send_weekly_digest_email(u['email'], u['name'], digest, unsub):
                    from db.core import new_id, now_iso
                    execute("""INSERT INTO notification_log (id,type,title,body,read,created_at,user_id)
                               VALUES (?,?,?,?,1,?,?)""",
                            (new_id(), 'digest_email', 'Weekly digest emailed',
                             digest['headline'], now_iso(), u['id']), commit=True)
                    sent += 1
        if sent:
            print(f'[scheduler] Weekly digest sent to {sent} user(s)')
    except Exception as e:
        print(f'[scheduler] Weekly digest error: {e}')


def _send_caregiver_digests():
    """Weekly reassurance email to caregivers summarising the family members
    who share their medicines. Deduped per caregiver per week; opt-out via
    reminder_settings.caregiver_digest_enabled."""
    import datetime as dt
    try:
        import mailer
        from auth import make_caregiver_digest_unsub_token
        from db.family import generate_caregiver_digest
        week_ago = (dt.datetime.now() - dt.timedelta(days=6)).isoformat()
        # A caregiver = someone in a group with ≥1 OTHER member sharing medicines
        cands = execute("""
            SELECT DISTINCT me.user_id, u.email, u.name
            FROM family_members me
            JOIN family_members other
                 ON other.group_id = me.group_id
                AND other.user_id <> me.user_id
                AND other.share_medicines = 1
            JOIN users u ON u.id = me.user_id
            LEFT JOIN reminder_settings rs ON rs.user_id = me.user_id
            WHERE COALESCE(rs.caregiver_digest_enabled, 1) = 1""", fetchall=True)
        sent = 0
        for c in cands:
            already = execute(
                "SELECT 1 FROM notification_log WHERE user_id=? AND type='caregiver_digest_email' AND created_at >= ? LIMIT 1",
                (c['user_id'], week_ago), fetchone=True)
            if already:
                continue
            with user_context(c['user_id']):
                digest = generate_caregiver_digest()
            if not digest.get('has_members'):
                continue
            unsub = (f"{mailer.APP_BASE_URL}/api/caregiver-digest/unsubscribe/"
                     f"{make_caregiver_digest_unsub_token(c['user_id'])}")
            if mailer.send_caregiver_digest_email(c['email'], c['name'], digest, unsub):
                from db.core import new_id, now_iso
                execute("""INSERT INTO notification_log (id,type,title,body,read,created_at,user_id)
                           VALUES (?,?,?,?,1,?,?)""",
                        (new_id(), 'caregiver_digest_email', 'Caregiver digest emailed',
                         digest['period_label'], now_iso(), c['user_id']), commit=True)
                sent += 1
        if sent:
            print(f'[scheduler] Caregiver digest sent to {sent} caregiver(s)')
    except Exception as e:
        print(f'[scheduler] Caregiver digest error: {e}')


def _run_loop():
    import schedule
    schedule.every().day.at("05:00").do(_daily_sync)
    schedule.every().hour.do(_check_missed_doses)
    schedule.every(5).minutes.do(_push_reminders)
    schedule.every(15).minutes.do(_caregiver_alerts)
    schedule.every().sunday.at("18:00").do(_send_weekly_digests)
    schedule.every().sunday.at("18:30").do(_send_caregiver_digests)
    # Also do an initial sync 30 s after startup
    schedule.every(30).seconds.do(lambda: (schedule.cancel_job(schedule.jobs[-1]), _daily_sync()))
    while True:
        schedule.run_pending()
        time.sleep(30)

def _run_loop_stdlib():
    """Fallback scheduler using plain threading when 'schedule' isn't available."""
    last_daily = None
    last_digest = None
    while True:
        now = datetime.datetime.now()
        if now.hour == 5 and now.minute == 0:
            day_key = now.date().isoformat()
            if last_daily != day_key:
                _daily_sync()
                last_daily = day_key
        if now.weekday() == 6 and now.hour == 18 and now.minute == 0:
            day_key = now.date().isoformat()
            if last_digest != day_key:
                _send_weekly_digests()
                last_digest = day_key
        if now.minute == 0:
            _check_missed_doses()
        if now.minute % 5 == 0:
            _push_reminders()
        if now.minute % 15 == 0:
            _caregiver_alerts()
        time.sleep(60)

def start_scheduler():
    global _scheduler_thread
    # With multiple gunicorn workers, enable the scheduler in ONE process
    # only (SCHEDULER_ENABLED=0 on the rest) to avoid duplicate job runs
    if os.environ.get('SCHEDULER_ENABLED', '1') != '1':
        print('[scheduler] Disabled via SCHEDULER_ENABLED=0')
        return
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    try:
        import schedule
        runner = _run_loop
    except ImportError:
        runner = _run_loop_stdlib

    _scheduler_thread = threading.Thread(target=runner, daemon=True, name='medeasy-scheduler')
    _scheduler_thread.start()
    print("[scheduler] Started")
