"""Hearing — tests, and the aids that follow them.

Dental and vision already work this way in Arogo: the app holds what a
professional told you, in their words, plus the practical upkeep that follows.
Hearing was simply missing, and it belongs in the same place — it changes
slowly, it is checked years apart, and by the next appointment nobody remembers
what the last one said.

The app never reads an audiogram. Frequencies and decibels are a measurement
made with calibrated equipment in a treated room, and interpreting one is an
audiologist's job. What is stored is the finding as reported: whatever the
clinician wrote or said, per ear, in their language.

The aid side is unglamorous and it is where the value is. A hearing aid has a
battery type nobody remembers, a fitting date, a service interval, and a
warranty — and the moment any of that matters is the moment the aid has stopped
working and the person cannot hear the phone call they need to make to ask.
"""
from __future__ import annotations

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date

KINDS = [
    ('test', 'Hearing test'),
    ('aid', 'Hearing aid'),
    ('note', 'Note'),
]
_KIND_LABEL = dict(KINDS)

# Fields that only make sense for one kind. Kept explicit so the UI and the API
# agree about what a "test" record is allowed to carry.
TEST_FIELDS = ('provider', 'left_ear', 'right_ear', 'finding', 'next_check')
AID_FIELDS = ('provider', 'device', 'battery', 'serviced_on', 'next_check')

_TEXT_MAX = 1000


def _clean(v, limit=_TEXT_MAX):
    return str(v or '').strip()[:limit]


def add_record(kind='test', record_date=None, **fields) -> dict:
    uid = current_user_id()
    kind = kind if kind in _KIND_LABEL else 'note'
    record_date = record_date if valid_date(record_date) else user_today()
    rid = new_id()
    execute("""INSERT INTO hearing_records
                 (id, user_id, kind, record_date, provider, left_ear, right_ear,
                  finding, device, battery, serviced_on, next_check, notes,
                  created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, uid, kind, record_date,
             _clean(fields.get('provider')), _clean(fields.get('left_ear')),
             _clean(fields.get('right_ear')), _clean(fields.get('finding'), 2000),
             _clean(fields.get('device')), _clean(fields.get('battery'), 120),
             fields.get('serviced_on') if valid_date(fields.get('serviced_on')) else '',
             fields.get('next_check') if valid_date(fields.get('next_check')) else '',
             _clean(fields.get('notes'), 2000), now_iso()),
            commit=True)
    return get_record(rid)


def get_record(rid):
    r = execute("SELECT * FROM hearing_records WHERE id=? AND user_id=?",
                (rid, current_user_id()), fetchone=True)
    return _shape(r) if r else None


def _shape(r) -> dict:
    d = dict(r)
    return {
        'id': d['id'], 'kind': d['kind'],
        'kind_label': _KIND_LABEL.get(d['kind'], d['kind']),
        'record_date': d['record_date'],
        'provider': d.get('provider') or '',
        'left_ear': d.get('left_ear') or '',
        'right_ear': d.get('right_ear') or '',
        'finding': d.get('finding') or '',
        'device': d.get('device') or '',
        'battery': d.get('battery') or '',
        'serviced_on': d.get('serviced_on') or '',
        'next_check': d.get('next_check') or '',
        'notes': d.get('notes') or '',
    }


def list_records(kind: str = None) -> list:
    uid = current_user_id()
    if kind in _KIND_LABEL:
        rows = execute("""SELECT * FROM hearing_records WHERE user_id=? AND kind=?
                          ORDER BY record_date DESC, created_at DESC""",
                       (uid, kind), fetchall=True) or []
    else:
        rows = execute("""SELECT * FROM hearing_records WHERE user_id=?
                          ORDER BY record_date DESC, created_at DESC""",
                       (uid,), fetchall=True) or []
    return [_shape(r) for r in rows]


def update_record(rid, **fields) -> dict:
    allowed = ('kind', 'record_date', 'provider', 'left_ear', 'right_ear',
               'finding', 'device', 'battery', 'serviced_on', 'next_check',
               'notes')
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k in ('record_date', 'serviced_on', 'next_check'):
            if not valid_date(v):
                continue
        elif k == 'kind':
            if v not in _KIND_LABEL:
                continue
        else:
            v = _clean(v, 2000)
        sets.append(f'{k}=?')
        args.append(v)
    if not sets:
        return get_record(rid)
    args += [rid, current_user_id()]
    execute(f"UPDATE hearing_records SET {', '.join(sets)} WHERE id=? AND user_id=?",
            tuple(args), commit=True)
    return get_record(rid)


def delete_record(rid) -> bool:
    from .trash import soft_delete
    return soft_delete('hearing_records', rid)


def overview() -> dict:
    """The last test, the current aids, and anything with a date coming up.

    `due` is derived only from dates the user entered. Nothing here invents a
    recommended interval — how often a hearing test is worth repeating depends
    on the person, and the app has no basis for a number.
    """
    records = list_records()
    if not records:
        return {'has_any': False, 'last_test': None, 'aids': [], 'due': []}

    tests = [r for r in records if r['kind'] == 'test']
    aids = [r for r in records if r['kind'] == 'aid']
    today = user_today()

    due = []
    for r in records:
        if r['next_check'] and r['next_check'] >= today:
            due.append({'id': r['id'], 'date': r['next_check'],
                        'label': r['device'] or r['provider'] or r['kind_label'],
                        'kind': r['kind']})
        elif r['next_check'] and r['next_check'] < today:
            due.append({'id': r['id'], 'date': r['next_check'], 'overdue': True,
                        'label': r['device'] or r['provider'] or r['kind_label'],
                        'kind': r['kind']})
    due.sort(key=lambda d: d['date'])

    return {
        'has_any': True,
        'last_test': tests[0] if tests else None,
        'aids': aids,
        'due': due,
        'counts': {'tests': len(tests), 'aids': len(aids),
                   'total': len(records)},
    }
