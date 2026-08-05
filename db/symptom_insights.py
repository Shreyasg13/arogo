"""
db/symptom_insights.py — honest cross-factor correlations for symptoms.

Surfaces PATTERNS, never causes: whether a symptom tends to line up with short
sleep, the start of a medicine (possible side-effect *timing*), or the menstrual
cycle. Every finding is framed as "worth mentioning to a doctor", never as a
diagnosis or a proven cause.

Cycle data is private. When a caregiver is acting-as a member, the cycle block
is omitted (same guard the condition dashboards use) so private data never leaks
through this otherwise-shareable endpoint.
"""
import datetime as _dt
from collections import defaultdict

from .core import execute, current_user_id
from .health import get_symptoms
from .wellness import get_sleep_logs
from .medicines import list_medicines
from .conditions import _acting_as_someone

MIN_OCCURRENCES = 3          # don't infer a pattern from one or two logs
SLEEP_GAP_H = 0.75           # symptom-day sleep must be this much lower to flag
SIDE_EFFECT_WINDOW = 14      # days after starting a med to call it "around when"
CYCLE_SHARE = 0.6            # this fraction of a symptom's days in one phase to flag


def _dkey(s):
    return (s or '')[:10]


def get_symptom_correlations(days=60) -> dict:
    days = max(7, min(int(days or 60), 365))
    symptoms = get_symptoms(days=days)

    by_name = defaultdict(list)
    for s in symptoms:
        by_name[s['name']].append(_dkey(s['date_key']))
    # unique occurrence-days per symptom, only those with enough data to judge
    frequent = {n: sorted(set(ds)) for n, ds in by_name.items() if len(set(ds)) >= MIN_OCCURRENCES}

    findings = []
    findings += _sleep_findings(frequent, days)
    findings += _med_start_findings(frequent)
    cycle_private = _acting_as_someone()
    if not cycle_private:
        findings += _cycle_findings(frequent)

    return {
        'days': days,
        'findings': findings,
        'cycle_private': cycle_private,
        'analysed': len(frequent),
        'note': 'These are patterns in your own logs, not proven causes. '
                'Mention anything that concerns you to a doctor.',
    }


def _sleep_findings(frequent, days):
    logs = get_sleep_logs(days=days)
    per = defaultdict(list)
    for l in logs:
        if l.get('duration_h') is not None:
            per[_dkey(l['date_key'])].append(l['duration_h'])
    sleep_by_date = {d: sum(v) / len(v) for d, v in per.items()}
    if len(sleep_by_date) < 5:
        return []
    all_dates = set(sleep_by_date)
    out = []
    for name, sdays in frequent.items():
        s_on = [sleep_by_date[d] for d in sdays if d in sleep_by_date]
        other = [sleep_by_date[d] for d in all_dates - set(sdays)]
        if len(s_on) < MIN_OCCURRENCES or len(other) < 3:
            continue
        a, b = sum(s_on) / len(s_on), sum(other) / len(other)
        if b - a >= SLEEP_GAP_H:
            out.append({
                'type': 'sleep', 'symptom': name,
                'symptom_avg': round(a, 1), 'other_avg': round(b, 1),
                'under6_days': sum(1 for h in s_on if h < 6), 'total_days': len(s_on),
            })
    return out


def _med_start_findings(frequent):
    meds = [m for m in list_medicines() if m.get('start_date')]
    out = []
    for name, sdays in frequent.items():
        first = sdays[0]           # earliest occurrence (list is sorted)
        try:
            fd = _dt.date.fromisoformat(first)
        except ValueError:
            continue
        for m in meds:
            sd = _dkey(m.get('start_date'))
            try:
                gap = (fd - _dt.date.fromisoformat(sd)).days
            except ValueError:
                continue
            if 0 <= gap <= SIDE_EFFECT_WINDOW:
                out.append({'type': 'med_start', 'symptom': name,
                            'medicine': m['name'], 'days_after': gap})
                break              # one plausible medicine link per symptom is enough
    return out


def _cycle_findings(frequent):
    cycles = execute("SELECT start_date, end_date FROM menstrual_cycles WHERE user_id=? ORDER BY start_date",
                     (current_user_id(),), fetchall=True) or []
    ranges, starts = [], []
    for c in cycles:
        s = _dkey(c['start_date'])
        try:
            sd = _dt.date.fromisoformat(s)
        except ValueError:
            continue
        starts.append(sd)
        e = _dkey(c['end_date'])
        try:
            ed = _dt.date.fromisoformat(e) if e else sd + _dt.timedelta(days=4)
        except ValueError:
            ed = sd + _dt.timedelta(days=4)
        ranges.append((sd, ed))
    if not ranges:
        return []

    def classify(dkey):
        try:
            d = _dt.date.fromisoformat(dkey)
        except ValueError:
            return 'other'
        for sd, ed in ranges:
            if sd <= d <= ed:
                return 'period'
        for sd in starts:
            if 0 < (sd - d).days <= 5:
                return 'pre_period'
        return 'other'

    out = []
    for name, sdays in frequent.items():
        cls = [classify(d) for d in sdays]
        n = len(cls)
        period_n, pre_n = cls.count('period'), cls.count('pre_period')
        if period_n >= MIN_OCCURRENCES and period_n / n >= CYCLE_SHARE:
            out.append({'type': 'cycle', 'symptom': name, 'phase': 'period',
                        'count': period_n, 'total': n})
        elif pre_n >= MIN_OCCURRENCES and pre_n / n >= CYCLE_SHARE:
            out.append({'type': 'cycle', 'symptom': name, 'phase': 'pre_period',
                        'count': pre_n, 'total': n})
    return out
