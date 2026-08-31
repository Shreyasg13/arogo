"""
scripts/bench_scale.py — what this app does after years of daily logging.

Against its own database Arogo holds a few dozen dose logs. Every claim about
how it behaves at 5,500 or 73,000 is therefore a guess, and the codebase had
206 unbounded SELECTs to guess about. This builds the data instead and times
what the app actually serves.

    python scripts/bench_scale.py            # 5 years
    BENCH_YEARS=20 python scripts/bench_scale.py

Writes to its own throwaway database (MEDEASY_DB is set before db.core is
imported, because that module reads the path at import time). It never touches
the real one — read that line before running it anyway.

What it found, 2026-08-30:

    5 years   18,250 dose logs,  6 MB   every endpoint under  41 ms
    20 years  73,000 dose logs, 22 MB   every endpoint under  90 ms

So the unbounded queries were not the problem, and no page needed paging. The
one real finding was the backup download: building it as a dict and then
json.dumps(indent=2) peaked at 228 MB to serve a 28 MB file — ten times the
database, in RAM, on a Raspberry Pi, during the one operation you cannot afford
to have fail. db/account.stream_all_data now yields it a page at a time, and
the peak is 1.6 MB. tests/test_backup_streaming.py keeps it that way.

/api/export is still flagged at 10+ years, on SIZE (about 2 MB) rather than
time. Left alone deliberately: it is scoped by section and date range, the user
chose to download all of it, and 2 MB is a reasonable file. If that line ever
starts showing hundreds of MB, it needs the same treatment as the backup.

Re-run this before believing anything about scale, including the above.
"""
import datetime as dt
import json
import os
import random
import sys
import tempfile
import time

DB = os.path.join(tempfile.gettempdir(), 'arogo-scale-bench.db')
os.environ['MEDEASY_DB'] = DB
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

random.seed(20260829)          # same dataset every run, so timings compare

from app import create_app                                          # noqa: E402
from db.core import execute, init_db, new_id, now_iso, user_context  # noqa: E402

YEARS = int(os.environ.get('BENCH_YEARS', '5'))
DAYS = 365 * YEARS

# Endpoints a real session actually hits. 404s are printed rather than hidden:
# a benchmark that quietly times a missing route reports a very fast app.
ENDPOINTS = [
    '/api/medicines', '/api/medicines/today', '/api/medicines/adherence',
    '/api/vitals', '/api/vitals?days=3650', '/api/symptoms?days=3650',
    '/api/body-metrics', '/api/sleep', '/api/timeline', '/api/data-trust',
    '/api/dormant', '/api/export/counts', '/api/storage', '/api/upcoming',
    '/api/health-binder', '/api/year-story', '/api/progress',
    '/api/search?q=head', '/api/calendar.ics',
    '/api/export', '/api/backup',
]

SLOW_MS, BIG_KB = 400, 2048


def seed():
    if os.path.exists(DB):
        os.remove(DB)
    init_db()
    app = create_app()
    app.config['TESTING'] = True
    c = app.test_client()
    c.post('/auth/register',
           json={'email': 'scale@bench.test', 'password': 'ScaleBench2026!'})
    uid = dict(execute("SELECT id FROM users WHERE email='scale@bench.test'",
                       fetchone=True))['id']

    start = dt.date.today() - dt.timedelta(days=DAYS)
    counts = {}

    with user_context(uid):
        meds = []
        for i in range(8):                     # three of them long since stopped
            mid = new_id()
            meds.append(mid)
            execute("""INSERT INTO medicines (id,name,dosage,unit,frequency,times,
                                              active,created_at,user_id,pill_count,purpose)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (mid, f'Medicine {i+1}', '10', 'mg', 'once_daily',
                     json.dumps(['09:00'] if i % 2 else ['09:00', '21:00']),
                     0 if i >= 5 else 1, now_iso(), uid, 30, 'blood pressure'),
                    commit=True)

        batches = {t: [] for t in ('dose_logs', 'vitals', 'food_logs',
                                   'hydration_logs', 'sleep_logs',
                                   'body_metrics', 'symptoms', 'health_notes')}
        for d in range(DAYS):
            day = (start + dt.timedelta(days=d)).isoformat()
            for mid in meds[:5]:
                for tm in ('09:00', '21:00'):
                    batches['dose_logs'].append(
                        (new_id(), uid, mid, day, tm,
                         1 if random.random() > .12 else 0, now_iso()))
            if d % 2 == 0:
                batches['vitals'].append(
                    (new_id(), day, 'blood_pressure', 110 + random.randint(0, 30),
                     70 + random.randint(0, 20), 'mmHg', now_iso(), uid))
            if d % 3 == 0:
                batches['food_logs'].append(
                    (new_id(), day, f'Meal {d%7}', 400 + d % 300, now_iso(), uid))
            if d % 4 == 0:
                batches['hydration_logs'].append(
                    (new_id(), day, 250 * (1 + d % 4), now_iso(), uid))
            if d % 5 == 0:
                batches['sleep_logs'].append(
                    (new_id(), day, f'{day}T23:00', f'{day}T07:00',
                     6 + (d % 4) * 0.5, 3, now_iso(), uid))
            if d % 7 == 0:
                batches['body_metrics'].append(
                    (new_id(), day, 70 + (d % 40) / 10, now_iso(), uid))
            if d % 11 == 0:
                batches['symptoms'].append(
                    (new_id(), 'Headache', 1 + d % 9, day, 'morning', now_iso(), uid))
            if d % 30 == 0:
                batches['health_notes'].append(
                    (new_id(), 'medicine', meds[0], 'Medicine 1',
                     f'Note from day {d}', now_iso(), now_iso(), uid))

        COLS = {
            'dose_logs': ['id', 'user_id', 'medicine_id', 'date_key', 'time_key',
                          'taken', 'taken_at'],
            'vitals': ['id', 'date_key', 'type', 'value1', 'value2', 'unit',
                       'logged_at', 'user_id'],
            'food_logs': ['id', 'date_key', 'food_name', 'calories', 'logged_at',
                          'user_id'],
            'hydration_logs': ['id', 'date_key', 'amount_ml', 'logged_at', 'user_id'],
            'sleep_logs': ['id', 'date_key', 'bedtime', 'wake_time', 'duration_h',
                           'quality', 'created_at', 'user_id'],
            'body_metrics': ['id', 'date_key', 'weight_kg', 'created_at', 'user_id'],
            'symptoms': ['id', 'name', 'severity', 'date_key', 'time_of_day',
                         'logged_at', 'user_id'],
            'health_notes': ['id', 'entity_type', 'entity_id', 'entity_label',
                             'body', 'created_at', 'updated_at', 'user_id'],
        }
        for table, values in batches.items():
            cols = COLS[table]
            marks = ','.join('?' * len(cols))
            for v in values:
                execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({marks})", v)
            counts[table] = len(values)
        execute('SELECT 1', commit=True)

    print(f'{YEARS} years seeded into {DB} '
          f'({os.path.getsize(DB)/1024/1024:.1f} MB)')
    for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f'  {n:7}  {t}')
    return c


def bench(c):
    print(f'\n{"ms":>7} {"KB":>10}  code  endpoint')
    slow = []
    for ep in ENDPOINTS:
        t0 = time.perf_counter()
        r = c.get(ep)
        ms = (time.perf_counter() - t0) * 1000
        kb = len(r.data) / 1024
        note = ''
        if r.status_code == 404:
            note = '   <- no such route (fix this list)'
        elif ms > SLOW_MS or kb > BIG_KB:
            note = '   <- SLOW/BIG'
            slow.append((ep, ms, kb))
        print(f'{ms:7.0f} {kb:10.1f}  {r.status_code}   {ep}{note}')
    return slow


def backup_memory(c):
    """The one that mattered. Peak RAM to produce the backup, both ways."""
    import tracemalloc
    from db.account import export_all_data, stream_all_data
    uid = dict(execute("SELECT id FROM users WHERE email='scale@bench.test'",
                       fetchone=True))['id']
    with user_context(uid):
        tracemalloc.start()
        body = json.dumps(export_all_data(uid), indent=2, default=str)
        _c, peak_old = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        size = len(body) / 1024 / 1024
        del body

        tracemalloc.start()
        for _chunk in stream_all_data(uid):
            pass
        _c, peak_new = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    print(f'\nbackup file        : {size:7.1f} MB')
    print(f'peak RAM assembled : {peak_old/1024/1024:7.1f} MB')
    print(f'peak RAM streamed  : {peak_new/1024/1024:7.1f} MB')


if __name__ == '__main__':
    client = seed()
    slow = bench(client)
    backup_memory(client)
    print('\nover threshold:' if slow else
          f'\nnothing over {SLOW_MS} ms / {BIG_KB} KB')
    for ep, ms, kb in slow:
        print(f'  {ep}: {ms:.0f} ms, {kb:.0f} KB')
