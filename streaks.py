"""
streaks.py — a forgiving streak counter.

A single missed day should not wipe a streak. Zero-tolerance streaks are
punitive for a chronically-ill audience and forgiveness ("streak freeze" /
grace days) is the best-evidenced retention mechanic Arogo was missing.

But this is a health app, so the honesty rules still bind:
  - A forgiven day is NEVER counted as done. `streak` is only the days actually
    completed — we never inflate an adherence number across a missed dose.
  - We report `grace_used` so the UI can say "1 rest day used" instead of
    implying a perfect run.

Grace is a small TOTAL budget over the run (not per-gap), so it can't be gamed
by missing every other day.
"""
import datetime as _dt


def forgiving_streak(done_dates, today, grace=1, earliest=None, lookback=400):
    """Count a streak back from `today`, tolerating up to `grace` missed days.

    done_dates : collection of ISO date strings that are completed.
    today      : datetime.date to count back from. If today itself isn't done,
                 it's treated as "in progress" — it neither counts nor breaks
                 the streak.
    grace      : total missed days (before today) the streak tolerates; the
                 (grace+1)th miss ends it.
    earliest   : optional datetime.date; stop when we walk past it, so the edge
                 of the known data isn't mistaken for a missed day.

    Returns {'streak': int, 'grace_used': int}.
    """
    done = set(done_dates or ())
    run = []                           # done/miss flags, today-ish → older
    misses = 0
    d = today
    first = True
    for _ in range(lookback):
        if earliest is not None and d < earliest:
            break
        done_today = d.isoformat() in done
        if first and not done_today:
            first = False              # today not done yet — in progress, skip
            d -= _dt.timedelta(days=1)
            continue
        first = False
        if not done_today:
            misses += 1
            if misses > grace:
                break                  # this miss is unforgiven — streak ends
        run.append(done_today)
        d -= _dt.timedelta(days=1)
    # Trailing misses aren't part of the streak (nothing to keep going), so a
    # forgiven day only counts when it sits BETWEEN completed days.
    while run and not run[-1]:
        run.pop()
    return {
        'streak':     sum(1 for x in run if x),
        'grace_used': sum(1 for x in run if not x),
    }
