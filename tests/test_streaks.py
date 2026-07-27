"""Tests for streaks.forgiving_streak — grace that forgives without lying.

The load-bearing guarantees: a forgiven day is never counted as done, grace is a
total budget (not gameable), and today-in-progress neither counts nor breaks.
"""
import datetime as dt

from streaks import forgiving_streak

D = dt.date(2026, 7, 26)


def iso(offset):
    return (D - dt.timedelta(days=offset)).isoformat()


def test_perfect_run_counts_all():
    done = {iso(i) for i in range(10)}          # today .. today-9
    r = forgiving_streak(done, today=D, grace=1, earliest=D - dt.timedelta(days=9))
    assert r["streak"] == 10 and r["grace_used"] == 0


def test_today_in_progress_does_not_break():
    done = {iso(i) for i in range(1, 8)}         # today not done, prior 7 done
    r = forgiving_streak(done, today=D, grace=1, earliest=D - dt.timedelta(days=7))
    assert r["streak"] == 7 and r["grace_used"] == 0


def test_single_miss_is_forgiven_but_not_counted():
    done = {iso(0), iso(1), iso(3), iso(4)}       # gap at iso(2)
    r = forgiving_streak(done, today=D, grace=1, earliest=D - dt.timedelta(days=4))
    assert r["streak"] == 4                        # the forgiven day is NOT counted
    assert r["grace_used"] == 1


def test_second_miss_ends_the_streak():
    done = {iso(0), iso(1), iso(3), iso(5), iso(6)}  # misses at iso(2) and iso(4)
    r = forgiving_streak(done, today=D, grace=1)
    assert r["streak"] == 3 and r["grace_used"] == 1


def test_grace_is_not_gameable_every_other_day():
    done = {iso(0), iso(2), iso(4), iso(6)}        # missing every other day
    r = forgiving_streak(done, today=D, grace=1)
    assert r["streak"] == 2                        # can't sustain via alternating


def test_earliest_boundary_is_not_a_miss():
    done = {iso(0), iso(1), iso(2)}                # only 3 days of data exist
    r = forgiving_streak(done, today=D, grace=1, earliest=D - dt.timedelta(days=2))
    assert r["streak"] == 3 and r["grace_used"] == 0


def test_empty_is_zero():
    r = forgiving_streak(set(), today=D, grace=1)
    assert r["streak"] == 0 and r["grace_used"] == 0
