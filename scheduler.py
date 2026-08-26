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

try:
    import observability
except Exception:                       # never let telemetry break the jobs
    observability = None


def _report(job: str, e: Exception):
    """Log a swallowed job failure to stderr AND to error tracking. Background
    jobs run on a headless worker, so a bare print() is easy to never see."""
    print(f"[scheduler] {job} error: {e}")
    if observability:
        observability.capture(e, job=job)


_scheduler_thread = None


def _heartbeat():
    """Write a liveness timestamp so a dead scheduler becomes visible.

    The web service can't see the worker thread directly (it's a separate
    process in production), but it can read this row. /healthz compares it to
    now and reports the scheduler as down if it's stale. Without this, a
    crashed scheduler means reminders silently stop with no signal anywhere."""
    try:
        from db.core import execute, now_iso
        execute("DELETE FROM app_config WHERE key='scheduler_last_run'", commit=True)
        execute("INSERT INTO app_config (key, value) VALUES ('scheduler_last_run', ?)",
                (now_iso(),), commit=True)
    except Exception as e:
        print(f"[scheduler] heartbeat error: {e}")


def _nightly_backup():
    """Take a verified backup, nightly.

    The verification is the point. A file in a backups directory is not a
    backup until something has opened it and checked it reads — and the
    moment that matters is the moment there is nothing left to compare it
    against.
    """
    try:
        from db.backups import run_backup
        res = run_backup()
        if res.get('ok'):
            print(f"[scheduler] backup ok: {res['name']} ({res['bytes']:,} bytes)")
        else:
            # Loud on failure. A silent backup failure is how an install
            # ends up believing it is covered when it isn't.
            print(f"[scheduler] BACKUP FAILED: {res.get('reason')}")
    except Exception as e:
        print(f'[scheduler] BACKUP FAILED: {e}')


def _purge_trash():
    """Delete trashed records past their thirty days, for good.

    Runs install-wide rather than per user: someone who never opens the app
    again should still have the records they deleted actually deleted.
    """
    try:
        from db.trash import purge_expired
        n = purge_expired()
        if n:
            print(f'[scheduler] purged {n} expired trash items')
    except Exception as e:
        print(f'[scheduler] trash purge error: {e}')


def _daily_sync():
    try:
        from fitness_sync import sync_all_connected
        results = sync_all_connected()
        print(f"[scheduler] Daily sync: {results}")
    except Exception as e:
        _report("daily_sync", e)

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


def in_quiet_hours(start, end, hhmm):
    """Is hhmm inside the do-not-disturb window? Handles a window that wraps past
    midnight (e.g. 22:00→07:00). A zero-length window (start==end) is 'off'."""
    try:
        s = int(start[:2]) * 60 + int(start[3:5])
        e = int(end[:2]) * 60 + int(end[3:5])
        n = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    except (ValueError, TypeError, IndexError):
        return False
    if s == e:
        return False
    if s < e:
        return s <= n < e                 # same-day window
    return n >= s or n < e                # wraps past midnight


def reminder_offset_min(dose_time, lead_min, now_hhmm):
    """Minutes since a dose's reminder became due, where the reminder fires
    `lead_min` minutes BEFORE the dose time. Negative = not due yet; None if
    unparsable. A 09:00 dose with a 15-min lead is 'due' from 08:45."""
    base = _mins_since(dose_time, now_hhmm)
    if base is None:
        return None
    return base + max(0, int(lead_min or 0))


def _pushed_today(uid, key, today):
    return execute(
        "SELECT 1 FROM notification_log WHERE user_id=? AND source_id=? AND created_at>=? LIMIT 1",
        (uid, key, today), fetchone=True)


def _mark_pushed(uid, key, title, body):
    from db.core import new_id, now_iso
    execute("""INSERT INTO notification_log (id,type,title,body,source_id,read,created_at,user_id)
               VALUES (?,?,?,?,?,0,?,?)""",
            (new_id(), 'push', title, body, key, now_iso(), uid), commit=True)


def _usual_sip_ml(uid, default=250):
    """The user's real glass/bottle — see db.wellness.usual_sip_ml."""
    try:
        from db.wellness import usual_sip_ml
        return usual_sip_ml(uid, default)
    except Exception:
        return default


def _push_reminders_for_user(uid):
    import push
    from db import get_today_doses
    from db.wellness import get_hydration_day

    now = _user_local_now(uid)
    today, hhmm = now.strftime('%Y-%m-%d'), now.strftime('%H:%M')
    rs = execute("SELECT * FROM reminder_settings WHERE user_id=? LIMIT 1",
                 (uid,), fetchone=True) or {}

    # Do-not-disturb: while inside the quiet window, hold ALL time-of-day nudges
    # (doses, snoozes, water, habit/sleep/mood, measurements). Nothing is marked
    # notified, so a snoozed dose simply fires once the window ends. A dose whose
    # 30-min window overlaps the end of quiet hours still gets sent then.
    if rs.get('quiet_enabled') and in_quiet_hours(
            rs.get('quiet_start') or '22:00', rs.get('quiet_end') or '07:00', hhmm):
        return

    # The recipient's chosen UI language, so push text matches the app they see.
    # Defaults to 'en'; tr() falls back to English for any missing translation.
    from i18n_server import tr
    from db import get_user_language
    lang = get_user_language(uid)

    def notify(key, title, body, actions=None):
        if _pushed_today(uid, key, today):
            return
        if push.push_to_user(uid, title, body, '/', actions):
            _mark_pushed(uid, key, title, body)

    # 1. Medicine doses that came due recently and aren't taken.
    #    The window is 30 min (not 5, the tick interval) so a missed tick —
    #    a deploy, restart, or GC stall — still gets the reminder out late
    #    rather than dropping it silently. The per-dose dedup below means the
    #    wider window still sends at most once.
    DOSE_REMINDER_WINDOW_MIN = 30
    for d in get_today_doses():
        if d.get('taken'):
            continue
        # A per-medicine lead time fires the reminder that many minutes early.
        lead = d.get('reminder_lead_min') or 0
        mins = reminder_offset_min(d.get('time') or '', lead, hhmm)
        if mins is not None and 0 <= mins <= DOSE_REMINDER_WINDOW_MIN:
            early = lead and mins < lead      # reminding ahead of the dose time
            when = (tr(lang, 'push.dose_when_early', time=d['time'], min=lead - mins) if early
                    else tr(lang, 'push.dose_when_sched', time=d['time']))
            # "✓ Taken" logs the dose straight from the notification — the core
            # adherence loop shouldn't cost an app open either.
            notify(f"med:{d['med_id']}:{d['time']}:{today}",
                   tr(lang, 'push.dose_title', med=d.get('med_name', 'your medicine')),
                   when
                   + (tr(lang, 'push.dose_for', purpose=d['purpose']) if d.get('purpose') else '')
                   + (tr(lang, 'push.dose_with_food') if d.get('with_food') else ''),
                   actions=[{'action': f"dose-{d['med_id']}-{d['time']}", 'title': tr(lang, 'push.act_taken')},
                            {'action': f"snooze-{d['med_id']}-{d['time']}", 'title': tr(lang, 'push.act_later')}])

    # 1b. Snoozed doses whose "remind me later" delay has elapsed and are still
    #     untaken. Each snooze fires once (marked notified); tapping Later again
    #     writes a fresh snooze, so it can be pushed back repeatedly.
    from db import get_due_snoozes, mark_snooze_notified
    for s in get_due_snoozes():
        title = tr(lang, 'push.snooze_title', med=s['med_name'])
        body = tr(lang, 'push.snooze_body') \
               + (tr(lang, 'push.dose_for', purpose=s['purpose']) if s.get('purpose') else '')
        if push.push_to_user(uid, title, body, '/',
                             [{'action': f"dose-{s['med_id']}-{s['time']}", 'title': tr(lang, 'push.act_taken')},
                              {'action': f"snooze-{s['med_id']}-{s['time']}", 'title': tr(lang, 'push.act_later')}]):
            mark_snooze_notified(s['id'])

    # Low-key mode: the user asked to keep it quiet. Everything above here —
    # medication doses and snoozes — is safety-critical and still fires. Below
    # here is non-essential (water, habit/sleep/mood, measurements), so we stop.
    # This is the guilt-free "leave me alone but keep me safe" switch.
    if rs.get('low_key'):
        return

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
                # Log straight from the notification — the whole point is that
                # hydration never costs an app open. `sip` is the user's usual
                # pour (see _usual_sip_ml), not a fabricated 250.
                sip = _usual_sip_ml(uid)
                notify(f"water:{today}:{bucket}",
                       tr(lang, 'push.water_title'),
                       tr(lang, 'push.water_body', ml=remaining),
                       actions=[{'action': f'water-{sip}', 'title': tr(lang, 'push.water_act', ml=sip)},
                                {'action': 'snooze',       'title': tr(lang, 'push.act_later')}])

    # 3. Evening habit / sleep / mood nudges at their configured times.
    #    The mood nudge answers itself: browsers render 2 buttons, so we offer
    #    the split that matters — fine vs not-fine ("not great" is the signal
    #    worth catching). Anything more nuanced is one tap away in the app.
    MOOD_ACTIONS = [{'action': 'mood-happy', 'title': tr(lang, 'push.mood_good')},
                    {'action': 'mood-sad',   'title': tr(lang, 'push.mood_notgreat')}]
    for flag, tkey, key, title_key, body_key, acts in [
        ('habit_reminder_enabled', 'habit_reminder_time', 'habit',
         'push.habit_title', 'push.habit_body', None),
        ('sleep_reminder_enabled', 'sleep_reminder_time', 'sleep',
         'push.sleep_title', 'push.sleep_body', None),
        ('mood_reminder_enabled', 'mood_reminder_time', 'mood',
         'push.mood_title', 'push.mood_body', MOOD_ACTIONS),
    ]:
        if rs.get(flag):
            mins = _mins_since(rs.get(tkey) or '', hhmm)
            if mins is not None and 0 <= mins <= 15:
                notify(f"{key}:{today}", tr(lang, title_key), tr(lang, body_key), acts)

    # 4. Measurement check-ins (BP / sugar / weight …) at their configured times.
    #    A reading needs a value, so tapping opens the app rather than logging
    #    from the notification. Deduped per reminder per day.
    MEAS = {
        'blood_pressure': ('push.meas_bp_title', 'push.meas_bp_body'),
        'blood_sugar':    ('push.meas_sugar_title', 'push.meas_sugar_body'),
        'weight':         ('push.meas_weight_title', 'push.meas_weight_body'),
        'spo2':           ('push.meas_spo2_title', 'push.meas_spo2_body'),
        'temperature':    ('push.meas_temp_title', 'push.meas_temp_body'),
        'heart_rate':     ('push.meas_hr_title', 'push.meas_hr_body'),
    }
    for r in (execute("SELECT * FROM measurement_reminders WHERE user_id=? AND enabled=1",
                      (uid,), fetchall=True) or []):
        mins = _mins_since(r['time'], hhmm)
        if mins is not None and 0 <= mins <= 15:
            tk, bk = MEAS.get(r['kind'], ('push.meas_generic_title', 'push.meas_generic_body'))
            notify(f"meas:{r['id']}:{today}", tr(lang, tk), tr(lang, bk))


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
        _report("push_reminders", e)


# ── Refill reminders: nudge to reorder before running out ────────────────────

def _refill_reminders():
    """Push a reorder nudge for medicines running low, deduped per medicine per
    day. Skips anything already marked ordered — so it stops once you've acted.
    Running out of pills is a top cause of missed doses, so this closes the loop
    that dose reminders start."""
    try:
        import push
        if not push.PUSH_AVAILABLE:
            return
        from db import get_low_stock_medicines, get_user_language
        from i18n_server import tr
        users = execute("SELECT DISTINCT user_id FROM push_subscriptions", fetchall=True)
        for u in users:
            uid = u['user_id']
            with user_context(uid):
                try:
                    lang = get_user_language(uid)
                    today = _user_local_now(uid).strftime('%Y-%m-%d')
                    for m in get_low_stock_medicines():
                        if m.get('refill_status') == 'ordered':
                            continue          # already handled — don't nag
                        key = f"refill:{m['id']}:{today}"
                        if _pushed_today(uid, key, today):
                            continue
                        days = max(0, int(round(m.get('days_left') or 0)))
                        title = tr(lang, 'push.refill_title', med=m.get('name', 'your medicine'))
                        body = (tr(lang, 'push.refill_body', days=days, s=('' if days == 1 else 's'))
                                + (f" · {m['pharmacy_note']}" if m.get('pharmacy_note') else ''))
                        if push.push_to_user(uid, title, body, '/'):
                            _mark_pushed(uid, key, title, body)
                except Exception as e:
                    _report(f"refill_reminders:{uid[:8]}", e)
    except Exception as e:
        _report("refill_reminders", e)


# ── Appointment reminders: the day before and the morning of ─────────────────

def appt_reminder_phase(appt_date, reminder_days, today):
    """Which reminder (if any) fires for an appointment on `today`:
      'day'  — the morning of the appointment
      'pre'  — the advance nudge, `reminder_days` before (default 1; 0 = none)
      None   — nothing today
    Pure and side-effect-free so it can be unit-tested without push/db."""
    import datetime as dt
    if appt_date == today:
        return 'day'
    rd = reminder_days if isinstance(reminder_days, int) and reminder_days >= 0 else 1
    if rd >= 1:
        try:
            lead_date = (dt.date.fromisoformat(today) + dt.timedelta(days=rd)).isoformat()
        except ValueError:
            return None
        if appt_date == lead_date:
            return 'pre'
    return None


def _appointment_reminders():
    """Remind about upcoming appointments — an advance heads-up (N days before,
    user-chosen) and again on the morning of. Deduped per appointment per phase."""
    try:
        import push
        if not push.PUSH_AVAILABLE:
            return
        from db import list_appointments, get_user_language
        from i18n_server import tr
        import datetime as dt
        users = execute("SELECT DISTINCT user_id FROM push_subscriptions", fetchall=True)
        KIND = {'doctor': '🩺', 'lab': '🧪', 'vaccine': '💉', 'other': '📅'}
        for u in users:
            uid = u['user_id']
            with user_context(uid):
                try:
                    lang = get_user_language(uid)
                    now = _user_local_now(uid)
                    today = now.strftime('%Y-%m-%d')
                    for a in list_appointments(upcoming_only=True):
                        if not a.get('remind'):
                            continue
                        rd = a.get('reminder_days')
                        rd = rd if isinstance(rd, int) and rd >= 0 else 1
                        phase = appt_reminder_phase(a['date'], rd, today)
                        if phase == 'pre':
                            lead = (tr(lang, 'push.appt_tomorrow') if rd == 1
                                    else tr(lang, 'push.appt_in_days', days=rd))
                        elif phase == 'day':
                            lead = tr(lang, 'push.appt_today')
                        else:
                            continue
                        key = f"appt:{a['id']}:{phase}"
                        if _pushed_today(uid, key, today):
                            continue
                        at = tr(lang, 'push.appt_at', time=a['time']) if a.get('time') else ''
                        where = f" · {a['location']}" if a.get('location') else ''
                        title = f"{KIND.get(a.get('kind'), '📅')} {lead}: {a['title']}"
                        body = f"{lead}{at}{where}".strip()
                        if push.push_to_user(uid, title, body, '/'):
                            _mark_pushed(uid, key, title, body)
                except Exception as e:
                    _report(f"appointment_reminders:{uid[:8]}", e)
    except Exception as e:
        _report("appointment_reminders", e)


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
                    acts = [{'action': f"dose-{d['med_id']}-{d['time']}", 'title': '✓ Taken'},
                            {'action': f"snooze-{d['med_id']}-{d['time']}", 'title': 'Later'}]
                    if push.push_to_user(uid, title, body, '/', acts):
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
                    # Only caregivers who opted to receive alerts (primary,
                    # not viewer) are pinged.
                    others = execute("""
                        SELECT u.id, u.email, u.name FROM family_members m
                        JOIN users u ON u.id = m.user_id
                        WHERE m.group_id=? AND m.user_id<>? AND m.receive_care_alerts=1""",
                        (w['group_id'], uid), fetchall=True)
                    # Count who we actually reached. Both of these can fail
                    # quietly: push returns 0 when nobody's subscribed or
                    # pywebpush is missing, and send_email returns True after
                    # merely printing to stderr when SMTP isn't configured.
                    reached = 0
                    for o in others:
                        pushed = bool(push.push_to_user(o['id'], title, body, '/'))
                        # Send first, then judge: send_email must still be called
                        # so dev flows keep logging it, but a dev-mode "True"
                        # (printed to stderr, nothing sent) must not count as
                        # having reached a human being.
                        sent = mailer.send_email(
                            o['email'], title,
                            f"Hi {o['name'] or 'there'},\n\n{body}\n\n"
                            f"They opted in to these alerts so you can check on them.\n"
                            f"Open Arogo: {mailer.APP_BASE_URL}/\n")
                        if pushed or (sent and mailer.is_configured()):
                            reached += 1
                    # Zero-install path: also reach account-less caregiver
                    # contacts over SMS/WhatsApp. Same honesty rule as email —
                    # a dev-mode send (logged, not delivered) doesn't count as
                    # reaching a human.
                    import sms
                    sms_name = w['name'] or 'your family member'
                    contacts = execute(
                        """SELECT id, name, phone, channel FROM caregiver_contacts
                           WHERE user_id=? AND alerts_enabled=1""",
                        (uid,), fetchall=True) or []
                    for c in contacts:
                        ext_msg = (f"Arogo: {sms_name}'s {med} ({d['time']}) hasn't been "
                                   f"marked as taken. A quick check-in would help.")
                        if sms.notify_contact(c, ext_msg) and sms.is_configured(c.get('channel', 'sms')):
                            reached += 1
                    # Transparency: the member always learns when family is told.
                    # Log THIS honest message to the member's own feed (also the
                    # dedup record), not the third-person "X missed a dose".
                    if reached:
                        tp_title = "We let your family know"
                        tp_body  = (f"{med} ({d['time']}) is still unlogged, so your family "
                                    f"was notified. Take it and this clears.")
                        push.push_to_user(uid, tp_title, tp_body, '/')
                        # Escalation succeeded for this dose today — stop retrying.
                        _mark_pushed(uid, key, tp_title, tp_body)
                    else:
                        # Reached NOBODY (nobody subscribed, SMTP down, no SMS
                        # contacts). Do NOT write the escalation key — a transient
                        # outage must not permanently burn the family alert; the
                        # next tick retries until someone is actually reached.
                        # But warn the member at most once per dose per day so a
                        # persistent outage doesn't spam them.
                        fail_key = f"caregiver_fail:{d['med_id']}:{d['time']}:{today}"
                        if not _pushed_today(uid, fail_key, today):
                            tp_title = "Couldn't reach your family"
                            tp_body  = (f"{med} ({d['time']}) is still unlogged and we couldn't "
                                        f"reach anyone in your family yet. Please take it, or call them.")
                            push.push_to_user(uid, tp_title, tp_body, '/')
                            _mark_pushed(uid, fail_key, tp_title, tp_body)
            except Exception as e:
                print(f"[scheduler] caregiver alert for {uid[:8]}: {e}")
    except Exception as e:
        _report("caregiver_alerts", e)


def _digest_log_title(base: str) -> str:
    """Say "emailed" only when an email actually went out.

    mailer.send_*() returns True after merely printing to stderr when SMTP
    isn't configured, so a deployment missing SMTP_HOST would tell every user
    their digest was emailed, every week, while sending nothing. The digest is
    generated and readable in the app either way — "ready" is the true word for
    that. (Same dev-mode blind spot as the caregiver alert; see _caregiver_alerts.)
    """
    import mailer          # lazily, as everywhere else in this module
    return f'{base} emailed' if mailer.is_configured() else f'{base} ready'


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
                from db import get_user_language
                lang = get_user_language(u['id'])
                digest = generate_weekly_digest(lang)
                unsub = f"{mailer.APP_BASE_URL}/api/digest/unsubscribe/{make_digest_unsub_token(u['id'])}"
                if mailer.send_weekly_digest_email(u['email'], u['name'], digest, unsub, lang=lang):
                    from db.core import new_id, now_iso
                    execute("""INSERT INTO notification_log (id,type,title,body,read,created_at,user_id)
                               VALUES (?,?,?,?,1,?,?)""",
                            (new_id(), 'digest_email', _digest_log_title('Weekly digest'),
                             digest['headline'], now_iso(), u['id']), commit=True)
                    sent += 1
        if sent:
            print(f'[scheduler] Weekly digest sent to {sent} user(s)')
    except Exception as e:
        _report("weekly_digest", e)


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
                from db import get_user_language
                cg_lang = get_user_language(c['user_id'])
                digest = generate_caregiver_digest()
            if not digest.get('has_members'):
                continue
            unsub = (f"{mailer.APP_BASE_URL}/api/caregiver-digest/unsubscribe/"
                     f"{make_caregiver_digest_unsub_token(c['user_id'])}")
            if mailer.send_caregiver_digest_email(c['email'], c['name'], digest, unsub, lang=cg_lang):
                from db.core import new_id, now_iso
                execute("""INSERT INTO notification_log (id,type,title,body,read,created_at,user_id)
                           VALUES (?,?,?,?,1,?,?)""",
                        (new_id(), 'caregiver_digest_email', _digest_log_title('Caregiver digest'),
                         digest['period_label'], now_iso(), c['user_id']), commit=True)
                sent += 1
        if sent:
            print(f'[scheduler] Caregiver digest sent to {sent} caregiver(s)')
    except Exception as e:
        _report("caregiver_digest", e)


def _run_loop():
    import schedule
    schedule.every().day.at("05:00").do(_daily_sync)
    schedule.every(5).minutes.do(_push_reminders)
    schedule.every(15).minutes.do(_caregiver_alerts)
    schedule.every(6).hours.do(_refill_reminders)
    schedule.every().day.at("19:00").do(_appointment_reminders)   # evening before
    schedule.every().day.at("08:00").do(_appointment_reminders)   # morning of
    schedule.every().minute.do(_heartbeat)
    schedule.every().day.at("03:30").do(_purge_trash)
    schedule.every().day.at("03:00").do(_nightly_backup)
    schedule.every().sunday.at("18:00").do(_send_weekly_digests)
    schedule.every().sunday.at("18:30").do(_send_caregiver_digests)
    # Also do an initial sync 30 s after startup
    schedule.every(30).seconds.do(lambda: (schedule.cancel_job(schedule.jobs[-1]), _daily_sync()))
    _heartbeat()   # mark alive immediately on start
    while True:
        schedule.run_pending()
        time.sleep(30)

def _run_loop_stdlib():
    """Fallback scheduler using plain threading when 'schedule' isn't available."""
    last_daily = None
    last_digest = None
    _heartbeat()   # mark alive immediately on start
    while True:
        _heartbeat()
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
        if now.minute % 5 == 0:
            _push_reminders()
        if now.minute % 15 == 0:
            _caregiver_alerts()
        if now.minute == 0 and now.hour % 6 == 0:
            _refill_reminders()
        if now.minute == 0 and now.hour in (8, 19):
            _appointment_reminders()
        time.sleep(60)

def start_scheduler():
    """Start the background job thread. Returns True if it started, False if
    disabled via SCHEDULER_ENABLED=0 (so a dedicated worker can fail loudly)."""
    global _scheduler_thread
    # With multiple gunicorn workers, enable the scheduler in ONE process
    # only (SCHEDULER_ENABLED=0 on the rest) to avoid duplicate job runs
    if os.environ.get('SCHEDULER_ENABLED', '1') != '1':
        print('[scheduler] Disabled via SCHEDULER_ENABLED=0')
        return False
    if _scheduler_thread and _scheduler_thread.is_alive():
        return True
    try:
        import schedule
        runner = _run_loop
    except ImportError:
        runner = _run_loop_stdlib

    _scheduler_thread = threading.Thread(target=runner, daemon=True, name='medeasy-scheduler')
    _scheduler_thread.start()
    print("[scheduler] Started")
    return True
