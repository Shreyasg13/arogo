"""
db/vitals_import.py — Category 1 device CSV import.

Parse a CSV exported from a home BP monitor / glucometer / pulse-oximeter /
thermometer / HR band into candidate vitals rows. NOTHING is saved at parse
time: the preview is honest about what was read and what was skipped, and the
user ticks what to keep before it's committed (each committed row re-validates
through log_vital, so ranges are enforced and nothing is fabricated).

Supports two shapes, auto-detected from the header:
  • wide  — a date column plus per-measurement columns (systolic/diastolic,
            glucose, pulse, spo2, temp).
  • long  — a date column plus a 'type'/'measurement' column and a 'value'.
"""
import csv as _csv
import datetime as _dt
import io as _io

# header keyword -> internal vital type (checked as a substring, longest first)
_COL_MAP = [
    ('systolic', ('blood_pressure', 'sys')),
    ('diastolic', ('blood_pressure', 'dia')),
    ('glucose', ('blood_sugar', 'v1')),
    ('blood sugar', ('blood_sugar', 'v1')),
    ('sugar', ('blood_sugar', 'v1')),
    ('spo2', ('spo2', 'v1')),
    ('oxygen', ('spo2', 'v1')),
    ('sao2', ('spo2', 'v1')),
    ('temperature', ('temperature', 'v1')),
    ('pulse', ('heart_rate', 'v1')),
    ('heart rate', ('heart_rate', 'v1')),
    ('heartrate', ('heart_rate', 'v1')),
]
# long-format 'type' values -> internal type
_TYPE_ALIASES = {
    'bp': 'blood_pressure', 'blood pressure': 'blood_pressure', 'blood_pressure': 'blood_pressure',
    'sugar': 'blood_sugar', 'glucose': 'blood_sugar', 'blood sugar': 'blood_sugar', 'blood_sugar': 'blood_sugar',
    'hr': 'heart_rate', 'pulse': 'heart_rate', 'heart rate': 'heart_rate', 'heart_rate': 'heart_rate',
    'spo2': 'spo2', 'oxygen': 'spo2',
    'temp': 'temperature', 'temperature': 'temperature',
}
_DEFAULT_UNIT = {'blood_pressure': 'mmHg', 'blood_sugar': 'mg/dL', 'heart_rate': 'bpm',
                 'spo2': '%', 'temperature': ''}
_MAX_ROWS = 2000


def _parse_date(s):
    s = str(s or '').strip()
    if not s:
        return None
    s = s.split('T')[0].split(' ')[0]          # drop any time component
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _num(s):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def parse_vitals_csv(text: str) -> dict:
    """Return {candidates, skipped, detected} — candidates are unsaved dicts
    {date_key, type, value1, value2, unit, label}; skipped counts unparseable
    rows; detected names the shape and the measurements found."""
    text = str(text or '')
    if not text.strip():
        return {'candidates': [], 'skipped': 0, 'detected': None}
    reader = list(_csv.reader(_io.StringIO(text)))
    rows = [r for r in reader if any((c or '').strip() for c in r)]
    if len(rows) < 2:
        return {'candidates': [], 'skipped': 0, 'detected': None}

    header = [(_h or '').strip().lower() for _h in rows[0]]

    def find(pred):
        for i, h in enumerate(header):
            if pred(h):
                return i
        return None

    date_i = find(lambda h: 'date' in h)
    if date_i is None:
        date_i = find(lambda h: 'time' in h)
    if date_i is None:
        date_i = 0                              # fall back to the first column

    # Wide: map each column to a (type, slot).
    col_targets = {}
    for i, h in enumerate(header):
        for kw, target in _COL_MAP:
            if kw in h:
                col_targets[i] = target
                break

    # Long: a type column + a value column.
    type_i = find(lambda h: h in ('type', 'measurement', 'metric'))
    value_i = find(lambda h: h in ('value', 'reading', 'result'))
    unit_i = find(lambda h: h == 'unit')

    candidates, skipped = [], 0
    found_types = set()
    for r in rows[1:_MAX_ROWS + 1]:
        cell = lambda i: (r[i] if i is not None and i < len(r) else '')
        dk = _parse_date(cell(date_i))
        if not dk:
            skipped += 1
            continue

        made = False
        if col_targets:
            # Gather BP (needs both), and each single-value measurement.
            bp_sys = bp_dia = None
            singles = {}   # type -> value
            for i, (vt, slot) in col_targets.items():
                v = _num(cell(i))
                if v is None:
                    continue
                if vt == 'blood_pressure' and slot == 'sys':
                    bp_sys = v
                elif vt == 'blood_pressure' and slot == 'dia':
                    bp_dia = v
                else:
                    singles[vt] = v
            if bp_sys is not None and bp_dia is not None:
                candidates.append({'date_key': dk, 'type': 'blood_pressure', 'value1': bp_sys,
                                   'value2': bp_dia, 'unit': 'mmHg', 'label': 'Blood pressure'})
                found_types.add('blood_pressure'); made = True
            for vt, v in singles.items():
                candidates.append({'date_key': dk, 'type': vt, 'value1': v, 'value2': None,
                                   'unit': _DEFAULT_UNIT.get(vt, ''), 'label': vt.replace('_', ' ').title()})
                found_types.add(vt); made = True

        if not made and type_i is not None and value_i is not None:
            raw_t = str(cell(type_i)).strip().lower()
            vt = _TYPE_ALIASES.get(raw_t)
            v1 = _num(cell(value_i))
            # A "120/80" value cell for BP.
            v2 = None
            if vt == 'blood_pressure' and v1 is None and '/' in str(cell(value_i)):
                parts = str(cell(value_i)).split('/')
                v1, v2 = _num(parts[0]), _num(parts[1]) if len(parts) > 1 else None
            if vt and v1 is not None:
                candidates.append({'date_key': dk, 'type': vt, 'value1': v1, 'value2': v2,
                                   'unit': str(cell(unit_i)).strip() or _DEFAULT_UNIT.get(vt, ''),
                                   'label': vt.replace('_', ' ').title()})
                found_types.add(vt); made = True

        if not made:
            skipped += 1

    shape = 'wide' if col_targets else ('long' if (type_i is not None and value_i is not None) else 'unknown')
    return {'candidates': candidates, 'skipped': skipped,
            'detected': {'shape': shape, 'types': sorted(found_types)} if candidates else None}
