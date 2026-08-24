"""Is anything actually going to send this user a reminder?

A dose reminder only arrives if every link holds: push is configured on the
server, the scheduler process is alive, and this device is still subscribed.
Any one of them failing is completely silent — the app looks normal, and the
person finds out by missing medication. For an adherence app that is the worst
failure mode there is, because the user has deliberately stopped holding the
schedule in their head.

Rules this module keeps to:

  - Say nothing to someone who isn't relying on reminders. A warning shown to a
    person with no scheduled medicines and no subscription is noise, and noise
    is how a real warning gets ignored later.

  - Never guess at consequences. It reports that reminders are not being sent
    and when the sender last ran. It does not say a dose was missed — the app
    has no idea whether the medicine was taken.

  - Distinguish "never started" from "stopped". On a fresh install the worker
    hasn't written a heartbeat yet, which is not a fault.

  - Use the same staleness threshold as /healthz, so a human and an uptime check
    never disagree about whether the scheduler is up.
"""
import datetime as dt

from .core import execute, current_user_id

# Jobs tick every 5 minutes and the heartbeat every minute, so 15 minutes is
# "definitely stalled" rather than "a slow tick". Kept identical to /healthz.
STALE_AFTER_S = 15 * 60


def _scheduler_state():
    """(last_run_iso | None, age_seconds | None). Age is None when it has never
    run, which is a different thing from having stopped."""
    try:
        row = execute("SELECT value FROM app_config WHERE key='scheduler_last_run'",
                      fetchone=True)
    except Exception:
        return None, None
    if not row or not row.get('value'):
        return None, None
    last = row['value']
    try:
        age = int((dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds())
    except Exception:
        return last, None
    return last, age


def _device_count(uid):
    try:
        r = execute("SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id=?",
                    (uid,), fetchone=True)
        return int(r['n']) if r else 0
    except Exception:
        return 0


def _scheduled_medicine_count(uid):
    """Active medicines with a time on them. An as-needed medicine is not
    something the user is waiting to be reminded about."""
    try:
        r = execute("""SELECT COUNT(*) AS n FROM medicines
                       WHERE user_id=? AND active=1 AND frequency<>'as_needed'""",
                    (uid,), fetchone=True)
        return int(r['n']) if r else 0
    except Exception:
        return 0


def reminder_health(uid=None) -> dict:
    uid = uid or current_user_id()
    try:
        import push
        push_available = bool(getattr(push, 'PUSH_AVAILABLE', False))
    except Exception:
        push_available = False

    devices = _device_count(uid)
    meds = _scheduled_medicine_count(uid)
    last_run, age = _scheduler_state()
    never_ran = last_run is None
    sched_ok = age is not None and age <= STALE_AFTER_S

    # Someone with no scheduled medicine and no subscribed device is not waiting
    # on a reminder, so there is nothing to warn them about.
    relying = bool(devices or meds)

    problems = []
    if relying:
        if not push_available:
            problems.append({
                'code': 'push_unconfigured',
                'title': 'Reminders are not set up on this server',
                'detail': 'Push notifications need a VAPID key pair and the '
                          'pywebpush package. Until those are in place, Arogo '
                          'cannot send a reminder to any device.',
                'actionable_by_user': False,
            })
        elif never_ran:
            problems.append({
                'code': 'scheduler_never_ran',
                'title': 'The reminder service has not started',
                'detail': 'Nothing has sent a reminder yet. On a new install '
                          'this clears as soon as the scheduler runs for the '
                          'first time.',
                'actionable_by_user': False,
            })
        elif not sched_ok:
            problems.append({
                'code': 'scheduler_stalled',
                'title': 'Reminders are not being sent',
                'detail': 'The service that sends reminders last ran '
                          f'{_ago(age)}. Until it is running again, dose and '
                          'water reminders will not arrive.',
                'actionable_by_user': False,
            })
        if push_available and devices == 0:
            problems.append({
                'code': 'no_device',
                'title': 'No device is set to receive reminders',
                'detail': 'Notifications are not switched on here, so reminders '
                          'have nowhere to go. You can turn them on from '
                          'Notifications.',
                'actionable_by_user': True,
            })

    return {
        'relying': relying,
        'ok': not problems,
        'problems': problems,
        'scheduler': {
            'ok': sched_ok,
            'never_ran': never_ran,
            'last_run': last_run,
            'age_seconds': age,
            'stale_after_seconds': STALE_AFTER_S,
        },
        'push': {'available': push_available, 'devices': devices},
        'scheduled_medicines': meds,
    }


def _ago(seconds):
    """A plain phrase for how long ago something happened. Deliberately coarse —
    claiming "17 minutes ago" from a once-a-minute heartbeat would imply a
    precision this doesn't have."""
    if seconds is None:
        return 'at an unknown time'
    if seconds < 90 * 60:
        return f'{max(1, seconds // 60)} minutes ago'
    if seconds < 36 * 3600:
        return f'{seconds // 3600} hours ago'
    return f'{seconds // 86400} days ago'
