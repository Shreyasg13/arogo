"""
db/reports.py — Medical reports CRUD.

All queries are scoped to the authenticated user via current_user_id().
"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id


def insert_report(data: dict) -> dict:
    rid = new_id()
    execute("""
        INSERT INTO reports
          (id,filename,original_name,patient_name,report_type,report_date,
           upload_date,tags,analysis_notes,severity,doctor,file_ext,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (rid, data['filename'], data['original_name'], data['patient_name'],
          data['report_type'], data['report_date'], now_iso(),
          jdump(data.get('tags', [])), data.get('analysis_notes',''),
          data.get('severity','normal'), data.get('doctor',''), data.get('file_ext',''),
          current_user_id()),
        commit=True)
    return get_report(rid)


def get_report(rid):
    r = execute("SELECT * FROM reports WHERE id=? AND user_id=?",
                (rid, current_user_id()), fetchone=True)
    return _fmt_report(r) if r else None


def list_reports(search='', tag='', severity='', doc_type=''):
    rows = execute("SELECT * FROM reports WHERE user_id=? ORDER BY upload_date DESC",
                   (current_user_id(),), fetchall=True)
    result = [_fmt_report(r) for r in rows]
    if tag:
        result = [r for r in result if tag in r.get('tags', [])]
    if severity:
        result = [r for r in result if r.get('severity') == severity]
    if doc_type:
        # Group into vault buckets by keyword, so "Blood test", "CBC report",
        # "Lipid profile" all land under 'lab' without an exact-match taxonomy.
        result = [r for r in result if _doc_bucket(r.get('report_type', '')) == doc_type]
    if search:
        s = search.lower()
        result = [r for r in result if
                  s in r.get('patient_name','').lower() or
                  s in r.get('report_type','').lower() or
                  s in ' '.join(r.get('tags',[])).lower() or
                  s in r.get('analysis_notes','').lower()]
    return result


def delete_report(rid):
    execute("DELETE FROM reports WHERE id=? AND user_id=?",
            (rid, current_user_id()), commit=True)


# Vault buckets — map free-text report_type into a small, filterable set. Keyword
# match so "Blood test", "Lipid profile", "CBC" all land under 'lab'.
_DOC_BUCKETS = [
    ('prescription', ('prescription', 'rx', 'medicine')),
    ('lab',          ('lab', 'blood', 'test', 'cbc', 'lipid', 'sugar', 'thyroid',
                      'hba1c', 'urine', 'panel', 'profile')),
    ('imaging',      ('x-ray', 'xray', 'scan', 'mri', 'ct', 'ultrasound', 'sono',
                      'echo', 'imaging')),
    ('discharge',    ('discharge', 'admission', 'hospital', 'surgery', 'operative')),
    ('insurance',    ('insurance', 'policy', 'claim', 'ayushman', 'esi', 'mediclaim')),
]


def doc_buckets():
    return ['prescription', 'lab', 'imaging', 'discharge', 'insurance', 'other']


def _doc_bucket(report_type):
    s = str(report_type or '').lower()
    for bucket, kws in _DOC_BUCKETS:
        if any(k in s for k in kws):
            return bucket
    return 'other'


def _fmt_report(r):
    d = dict(r)
    d['tags'] = jload(d.get('tags', '[]'), [])
    d['doc_bucket'] = _doc_bucket(d.get('report_type', ''))
    return d


def report_stats():
    rows = execute("SELECT * FROM reports WHERE user_id=?",
                   (current_user_id(),), fetchall=True)
    sev, types, tags = {}, {}, {}
    for r in rows:
        s = r.get('severity', 'normal'); sev[s] = sev.get(s, 0) + 1
        t = r.get('report_type', 'General'); types[t] = types.get(t, 0) + 1
        for tg in jload(r.get('tags', '[]'), []): tags[tg] = tags.get(tg, 0) + 1
    top = sorted(tags.items(), key=lambda x: x[1], reverse=True)[:6]
    return {'total': len(rows), 'severity': sev, 'types': types, 'top_tags': top}
