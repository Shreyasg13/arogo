"""Search across everything the user has recorded.

The search bar used to cover seven tables — food, journal, symptoms, tasks,
workouts, medicines, records — out of the sixty-nine the app writes to. A search
for a lab result, an allergy, a procedure, a note, an insurance policy or a
question for the doctor came back "No results", which reads as "you never
recorded that". Silent incompleteness in a search bar is worse than a visible
limitation: it makes the user distrust their own memory.

So coverage is declared, not incidental. Every table in DATA_TABLES must appear
in SEARCHABLE or in NOT_SEARCHABLE with a stated reason, and a conventions test
fails the build when a new table appears in neither. Adding a feature now forces
a search decision instead of quietly shrinking what the bar can find.

Two rules the registry encodes:

  - Never render a value whose meaning depends on a display unit. A vitals row
    is found by its type, date and note, not by "110" — the stored number is
    canonical mg/dL and printing it raw would show an mmol/L user a number they
    never typed. Rows that carry their own unit column (labs) can show both.

  - Never make an identifier findable or visible. A policy is searchable by
    insurer and plan, never by policy number; tokens and access credentials are
    excluded outright.
"""
import re

from .core import execute, current_user_id, user_today


# ── Spec ─────────────────────────────────────────────────────────────────────
# text:   columns matched against the query (LIKE, case-folded)
# date:   column used for date-range filtering and ordering; None = no date
# show:   extra columns to select for rendering
# title:  callable(row) -> the line the user reads
# meta:   callable(row) -> the quieter second line (may be '')
# view:   the page this result navigates to
# private: a diary category — excluded whenever a caregiver is acting-as
class Spec:
    __slots__ = ('table', 'label', 'icon', 'text', 'date', 'show',
                 'title', 'meta', 'view', 'private', 'type')

    def __init__(self, table, label, icon, text, date, view, title,
                 meta=None, show=(), private=False, type=None):
        self.table, self.label, self.icon = table, label, icon
        self.text, self.date, self.show = tuple(text), date, tuple(show)
        self.title, self.meta, self.view = title, meta, view
        self.private = private
        self.type = type or table


def _j(*parts):
    """Join the non-empty bits of a meta line with the app's separator."""
    return ' · '.join(str(p) for p in parts if p not in (None, '', 0))


def _clip(s, n=90):
    s = str(s or '').strip()
    return s if len(s) <= n else s[:n].rstrip() + '…'


def _cap(s):
    return str(s or '').replace('_', ' ').strip().capitalize()


# ── The registry ─────────────────────────────────────────────────────────────
# Ordered roughly by how often someone searches for it: medicines and records
# first, background and reference material last.
SEARCHABLE = [
    Spec('medicines', 'Medicines', '💊', type='medicine',
         text=('name', 'dosage', 'purpose', 'notes', 'pharmacy_note'),
         date=None, view='medicines', show=('unit', 'frequency', 'active'),
         title=lambda r: r['name'],
         meta=lambda r: _j(_j(r['dosage'], r['unit']) or None,
                           _cap(r['frequency']), r['purpose'],
                           None if r['active'] else 'archived')),

    Spec('medicine_events', 'Medicine history', '🕑',
         text=('med_name', 'kind', 'detail'), date='at', view='medicines',
         show=('med_name', 'kind', 'detail'),
         title=lambda r: _j(r['med_name'], _cap(r['kind'])),
         meta=lambda r: _j(str(r['at'] or '')[:10], r['detail'])),

    Spec('prescriptions', 'Prescriptions', '📜',
         text=('prescriber', 'notes'), date='date_issued', view='prescriptions',
         show=('prescriber', 'valid_until', 'notes'),
         title=lambda r: _j(r['prescriber'] or 'Prescription'),
         meta=lambda r: _j(r['date_issued'],
                           f"valid to {r['valid_until']}" if r['valid_until'] else None,
                           _clip(r['notes'], 60))),

    Spec('med_taper_steps', 'Dose taper', '📉',
         text=('dosage', 'note'), date='start_date', view='taper',
         show=('dosage', 'note'),
         title=lambda r: _j(r['dosage'] or 'Taper step'),
         meta=lambda r: _j(r['start_date'], _clip(r['note'], 60))),

    Spec('reports', 'Medical records', '📋', type='report',
         text=('filename', 'original_name', 'patient_name', 'doctor',
               'report_type', 'tags', 'analysis_notes'),
         date='report_date', view='reports',
         show=('filename', 'original_name', 'doctor', 'report_type', 'severity'),
         title=lambda r: r['original_name'] or r['filename'] or 'Record',
         meta=lambda r: _j(r['report_date'], _cap(r['report_type']),
                           r['doctor'], r['severity'])),

    # Labs carry their own unit column, so the value is safe to show as recorded.
    Spec('lab_results', 'Lab results', '🧪',
         text=('name', 'notes'), date='date_key', view='labs',
         show=('name', 'value', 'unit', 'notes'),
         title=lambda r: r['name'],
         meta=lambda r: _j(r['date_key'],
                           _j(r['value'], r['unit']) if r['value'] is not None else None,
                           _clip(r['notes'], 50))),

    # Vitals are stored canonically (mg/dL, kg, °C). Showing the raw number would
    # print a figure an mmol/L or lb user never typed, so the value is left out —
    # the row is found by what it is and when, and the page shows it properly.
    Spec('vitals', 'Vitals', '❤️',
         text=('type', 'notes', 'context'), date='date_key', view='body',
         show=('type', 'context', 'notes'),
         title=lambda r: _cap(r['type']),
         meta=lambda r: _j(r['date_key'], _cap(r['context']), _clip(r['notes'], 50))),

    Spec('symptoms', 'Symptoms', '🩺', type='symptom',
         text=('name', 'notes', 'region'), date='date_key', view='body',
         show=('name', 'severity', 'time_of_day', 'region', 'notes'),
         title=lambda r: r['name'],
         meta=lambda r: _j(r['date_key'], _cap(r['time_of_day']),
                           f"{r['severity']}/10" if r['severity'] else None,
                           r['region'], _clip(r['notes'], 50))),

    Spec('body_metrics', 'Body measurements', '📏',
         text=('notes',), date='date_key', view='progress', show=('notes',),
         title=lambda r: 'Measurement note',
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 70))),

    Spec('allergies', 'Allergies', '⚠️',
         text=('allergen', 'reaction', 'notes'), date='date_noted',
         view='allergies', show=('allergen', 'reaction', 'severity', 'notes'),
         title=lambda r: r['allergen'],
         meta=lambda r: _j(r['reaction'], _cap(r['severity']),
                           r['date_noted'], _clip(r['notes'], 50))),

    Spec('immunizations', 'Vaccines', '💉',
         text=('name', 'dose_label', 'notes'), date='date_given',
         view='immunizations', show=('name', 'dose_label', 'notes'),
         title=lambda r: r['name'],
         meta=lambda r: _j(r['date_given'], r['dose_label'], _clip(r['notes'], 50))),

    Spec('procedures', 'Procedures', '🏥',
         text=('name', 'kind', 'provider', 'location', 'notes'),
         date='date_key', view='procedures',
         show=('name', 'kind', 'provider', 'location', 'notes'),
         title=lambda r: r['name'],
         meta=lambda r: _j(r['date_key'], _cap(r['kind']), r['provider'],
                           r['location'], _clip(r['notes'], 50))),

    Spec('appointments', 'Appointments', '📅',
         text=('title', 'kind', 'location', 'notes', 'visit_summary', 'follow_up'),
         date='date', view='upcoming',
         show=('title', 'kind', 'time', 'location', 'notes', 'visit_summary'),
         title=lambda r: r['title'] or _cap(r['kind']) or 'Appointment',
         meta=lambda r: _j(r['date'], r['time'], r['location'],
                           _clip(r['visit_summary'] or r['notes'], 60))),

    Spec('doctor_questions', 'Questions for the doctor', '❓',
         text=('question',), date='created_at', view='upcoming',
         show=('question',),
         title=lambda r: _clip(r['question']),
         meta=lambda r: str(r['created_at'] or '')[:10]),

    Spec('visit_action_items', 'Visit follow-ups', '☑️',
         text=('text',), date='created_at', view='upcoming', show=('text',),
         title=lambda r: _clip(r['text']),
         meta=lambda r: str(r['created_at'] or '')[:10]),

    Spec('providers', 'Care team', '🧑‍⚕️',
         text=('name', 'specialty', 'clinic', 'address', 'notes'), date=None,
         view='care-team', show=('name', 'specialty', 'clinic', 'phone', 'notes'),
         title=lambda r: r['name'],
         meta=lambda r: _j(r['specialty'], r['clinic'], r['phone'])),

    Spec('care_plan_items', 'Care plan', '🗂️',
         text=('title', 'detail', 'category', 'owner'), date='review_date',
         view='care-plan', show=('title', 'detail', 'category', 'owner', 'status'),
         title=lambda r: r['title'],
         meta=lambda r: _j(_cap(r['category']), r['owner'], _cap(r['status']),
                           _clip(r['detail'], 50))),

    Spec('health_reminders', 'Health reminders', '🔔',
         text=('title', 'notes'), date='due_date', view='reminders',
         show=('title', 'notes', 'last_done'),
         title=lambda r: r['title'],
         meta=lambda r: _j(f"due {r['due_date']}" if r['due_date'] else None,
                           f"last {r['last_done']}" if r['last_done'] else None,
                           _clip(r['notes'], 50))),

    Spec('dental_vision_visits', 'Dental & vision', '🦷',
         text=('kind', 'provider', 'summary'), date='visit_date',
         view='dentalvision', show=('kind', 'provider', 'summary', 'next_due'),
         title=lambda r: _j(_cap(r['kind']) or 'Visit', r['provider']),
         meta=lambda r: _j(r['visit_date'], _clip(r['summary'], 60),
                           f"next {r['next_due']}" if r['next_due'] else None)),

    Spec('vision_prescriptions', 'Glasses & lenses', '👓',
         text=('kind', 'notes'), date='rx_date', view='dentalvision',
         show=('kind', 'notes'),
         title=lambda r: _cap(r['kind']) or 'Vision prescription',
         meta=lambda r: _j(r['rx_date'], _clip(r['notes'], 60))),

    Spec('family_history', 'Family history', '🧬',
         text=('relation', 'condition', 'notes'), date=None,
         view='familyhistory', show=('relation', 'condition', 'notes'),
         title=lambda r: r['condition'],
         meta=lambda r: _j(_cap(r['relation']), _clip(r['notes'], 60))),

    Spec('health_notes', 'Notes', '📝',
         text=('body', 'entity_label'), date='created_at', view='notes',
         show=('body', 'entity_label', 'entity_type'),
         title=lambda r: _clip(r['body']),
         meta=lambda r: _j(r['entity_label'], str(r['created_at'] or '')[:10])),

    Spec('health_expenses', 'Spending', '💰',
         text=('description', 'category', 'notes'), date='date_key',
         view='spending', show=('description', 'category', 'notes'),
         title=lambda r: r['description'] or _cap(r['category']) or 'Expense',
         meta=lambda r: _j(r['date_key'], _cap(r['category']),
                           _clip(r['notes'], 50))),

    # Searchable by insurer and plan, never by policy_no — that number is a
    # financial identifier, so it is neither matched nor rendered.
    Spec('insurance_policies', 'Insurance', '🛡️',
         text=('insurer', 'kind', 'notes', 'members'), date='renewal_date',
         view='insurance', show=('insurer', 'kind', 'renewal_date', 'active'),
         title=lambda r: _j(r['insurer'], _cap(r['kind'])),
         meta=lambda r: _j(f"renews {r['renewal_date']}" if r['renewal_date'] else None,
                           None if r['active'] else 'archived')),

    Spec('claims', 'Claims', '🧾',
         text=('insurer', 'status', 'notes'), date='date_submitted',
         view='claims', show=('insurer', 'status', 'notes'),
         title=lambda r: r['insurer'] or 'Claim',
         meta=lambda r: _j(r['date_submitted'], _cap(r['status']),
                           _clip(r['notes'], 50))),

    Spec('home_supplies', 'Home supplies', '🧰',
         text=('name', 'category', 'notes'), date='expiry_date', view='supplies',
         show=('name', 'category', 'quantity', 'unit', 'expiry_date'),
         title=lambda r: r['name'],
         meta=lambda r: _j(_cap(r['category']),
                           _j(r['quantity'], r['unit']) if r['quantity'] is not None else None,
                           f"expires {r['expiry_date']}" if r['expiry_date'] else None)),

    Spec('symptom_photos', 'Photo journal', '📷',
         text=('label', 'notes'), date='taken_date', view='symptomphotos',
         show=('label', 'notes'),
         title=lambda r: r['label'] or 'Photo',
         meta=lambda r: _j(r['taken_date'], _clip(r['notes'], 60))),

    Spec('thoughts', 'Journal', '💭', type='thought', private=True,
         text=('content',), date='date_key', view='thoughts',
         show=('content', 'mood'),
         title=lambda r: _clip(r['content']),
         meta=lambda r: _j(r['date_key'], _cap(r['mood']))),

    Spec('todos', 'Tasks', '✅', type='todo',
         text=('title', 'notes', 'tags'), date='created_at', view='todos',
         show=('title', 'notes', 'priority', 'status', 'due_date'),
         title=lambda r: r['title'],
         meta=lambda r: _j(f"{_cap(r['priority'])} priority" if r['priority'] else None,
                           f"due {r['due_date']}" if r['due_date'] else None,
                           _cap(r['status']))),

    Spec('habits', 'Habits', '🔁',
         text=('name', 'category'), date=None, view='habits',
         show=('name', 'category', 'emoji'),
         title=lambda r: _j(r['emoji'], r['name']),
         meta=lambda r: _cap(r['category'])),

    Spec('health_goals', 'Goals', '🎯',
         text=('title', 'metric'), date='deadline', view='goals',
         show=('title', 'metric', 'status', 'deadline'),
         title=lambda r: r['title'],
         meta=lambda r: _j(_cap(r['metric']),
                           f"by {r['deadline']}" if r['deadline'] else None,
                           _cap(r['status']))),

    Spec('experiments', 'Experiments', '🔬',
         text=('title', 'metric', 'notes'), date='start_date',
         view='experiments', show=('title', 'metric', 'status', 'notes'),
         title=lambda r: r['title'],
         meta=lambda r: _j(r['start_date'], _cap(r['metric']), _cap(r['status']))),

    Spec('weekly_reviews', 'Weekly review', '🗓️',
         text=('wins', 'focus'), date='week_start', view='weekreview',
         show=('wins', 'focus'),
         title=lambda r: _clip(r['wins'] or r['focus']),
         meta=lambda r: _j(f"week of {r['week_start']}" if r['week_start'] else None,
                           _clip(r['focus'], 50) if r['wins'] else None)),

    Spec('food_logs', 'Food', '🍽️', type='food',
         text=('food_name', 'meal_type'), date='date_key', view='food',
         show=('food_name', 'meal_type', 'calories'),
         title=lambda r: r['food_name'],
         meta=lambda r: _j(r['date_key'], _cap(r['meal_type']),
                           f"{round(r['calories'])} kcal" if r['calories'] else None)),

    Spec('custom_foods', 'My foods', '🥗',
         text=('name', 'category'), date='created_at', view='food',
         show=('name', 'category', 'emoji'),
         title=lambda r: _j(r['emoji'], r['name']),
         meta=lambda r: _cap(r['category'])),

    Spec('meal_plans', 'Meal plan', '📆',
         text=('item', 'meal_type'), date='date', view='meal-plan',
         show=('item', 'meal_type'),
         title=lambda r: r['item'],
         meta=lambda r: _j(r['date'], _cap(r['meal_type']))),

    Spec('fitness_activities', 'Workouts', '🏃', type='activity',
         text=('name', 'type', 'notes'), date='date', view='fitness',
         show=('name', 'type', 'duration', 'calories', 'distance'),
         title=lambda r: r['name'] or _cap(r['type']),
         meta=lambda r: _j(r['date'], f"{r['duration']} min" if r['duration'] else None,
                           f"{round(r['calories'])} kcal" if r['calories'] else None)),

    Spec('workout_sets', 'Strength log', '🏋️',
         text=('exercise', 'notes'), date='date_key', view='strength',
         show=('exercise', 'notes'),
         title=lambda r: r['exercise'],
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 50))),

    Spec('sleep_logs', 'Sleep', '😴',
         text=('notes',), date='date_key', view='sleep', show=('notes',),
         title=lambda r: 'Sleep note',
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 70))),

    Spec('fasting_sessions', 'Fasting', '⏳',
         text=('notes',), date='start_at', view='fasting',
         show=('notes', 'status'),
         title=lambda r: _j('Fast', _cap(r['status'])),
         meta=lambda r: _j(str(r['start_at'] or '')[:10], _clip(r['notes'], 60))),

    Spec('quit_plans', 'Quit tracker', '🚭',
         text=('label', 'kind', 'notes'), date='quit_date', view='quit',
         show=('label', 'kind', 'notes'),
         title=lambda r: r['label'] or _cap(r['kind']) or 'Quit plan',
         meta=lambda r: _j(r['quit_date'], _clip(r['notes'], 60))),

    Spec('dependents', 'People I care for', '👪',
         text=('name', 'relationship', 'notes'), date=None, view='dependents',
         show=('name', 'relationship', 'notes'),
         title=lambda r: r['name'],
         meta=lambda r: _j(_cap(r['relationship']), _clip(r['notes'], 50))),

    Spec('dependent_records', 'Dependent records', '🧒',
         text=('label', 'detail', 'kind'), date='date_key', view='dependents',
         show=('label', 'detail', 'kind'),
         title=lambda r: r['label'] or _cap(r['kind']),
         meta=lambda r: _j(r['date_key'], _cap(r['kind']), _clip(r['detail'], 50))),

    Spec('injection_logs', 'Injections', '💉',
         text=('site', 'notes'), date='date_key', view='medicines',
         show=('site', 'notes'),
         title=lambda r: _j('Injection', _cap(r['site'])),
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 60))),

    Spec('med_effectiveness', 'How a medicine felt', '📊',
         text=('notes',), date='date_key', view='medicines', show=('notes',),
         title=lambda r: 'Effectiveness note',
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 70))),

    Spec('action_plans', 'Action plans', '📋',
         text=('title',), date='created_at', view='conditions', show=('title',),
         title=lambda r: r['title'],
         meta=lambda r: str(r['created_at'] or '')[:10]),

    # ── Private diary categories. Findable by their owner; never surfaced while
    # a caregiver is acting-as, matching the wall on the journal itself.
    Spec('menstrual_cycles', 'Cycle', '🩸', private=True,
         text=('notes',), date='start_date', view='body', show=('notes', 'end_date'),
         title=lambda r: 'Cycle',
         meta=lambda r: _j(r['start_date'], _clip(r['notes'], 60))),

    Spec('cycle_symptoms', 'Cycle symptoms', '🩸', private=True,
         text=('symptoms', 'flow', 'notes'), date='date_key', view='body',
         show=('symptoms', 'flow', 'notes'),
         title=lambda r: _cap(r['flow']) or 'Cycle day',
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 60))),

    Spec('menopause_logs', 'Menopause', '🌡️', private=True,
         text=('notes',), date='date_key', view='menopause', show=('notes',),
         title=lambda r: 'Menopause note',
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 70))),

    Spec('pregnancy', 'Pregnancy', '🤰', private=True,
         text=('notes',), date='due_date', view='pregnancy',
         show=('notes', 'due_date'),
         title=lambda r: 'Pregnancy',
         meta=lambda r: _j(f"due {r['due_date']}" if r['due_date'] else None,
                           _clip(r['notes'], 60))),

    Spec('pregnancy_logs', 'Pregnancy log', '🤰', private=True,
         text=('notes',), date='date_key', view='pregnancy', show=('notes',),
         title=lambda r: 'Pregnancy note',
         meta=lambda r: _j(r['date_key'], _clip(r['notes'], 70))),
]


# Tables with nothing a person would type into a search bar, or which must never
# be searchable. Each reason is load-bearing: the conventions test only checks
# that a decision was made, so the reason is what stops "not searchable" from
# becoming a shrug.
NOT_SEARCHABLE = {
    # No user-authored text — numbers, timestamps and flags only. These are
    # found through their own charts and day views, not by keyword.
    'hydration_logs':        'amounts and drink types only; no free text',
    'habit_logs':            'a tick per day; the habit itself is searchable',
    'dose_logs':             'taken/skipped ticks; the medicine is searchable',
    'dose_snoozes':          'transient reminder state',
    'lab_rechecks':          'a flag per lab key; the result is searchable',
    'vital_targets':         'numeric targets; shown on the vitals page',
    'environment_days':      'imported AQI/weather numbers, not records',
    'measurement_reminders': 'reminder schedule, not a health record',
    'reminder_settings':     'notification preferences',

    # Settings and system rows, not records.
    'user_profile':          'the user\'s own settings, not something to find',
    'sync_log':              'integration diagnostics',
    'notification_log':      'copy the app generated, not what the user recorded',

    # Deliberately excluded: these hold identifiers or credentials. Making them
    # searchable would both surface and confirm the values.
    'emergency_info':        'holds an insurance number; shown whole on Health ID',
    'oauth_tokens':          'access credentials — never searchable',
    'share_snapshots':       'share tokens — never searchable',
}


_IDENT = re.compile(r'^[a-z_][a-z0-9_]*$')


def _ident(name):
    """Table and column names come from the registry above, never from a request.
    This asserts that invariant rather than trusting it, since these go into SQL
    by interpolation (the values are always bound)."""
    if not _IDENT.match(name):
        raise ValueError(f'unsafe identifier in search registry: {name!r}')
    return name


def _run(spec, text_q, date_range, per_section):
    cols = {'id'} | set(spec.text) | set(spec.show)
    if spec.date:
        cols.add(spec.date)
    select = ', '.join(_ident(c) for c in sorted(cols))
    # COALESCE, not a bare LOWER: on Postgres LOWER(NULL) is NULL and the whole
    # OR-chain goes unknown, so a row with one empty column stops matching on
    # its other columns.
    where = ' OR '.join(f"LOWER(COALESCE({_ident(c)},'')) LIKE ?" for c in spec.text)
    params = [text_q] * len(spec.text)
    sql = (f"SELECT {select} FROM {_ident(spec.table)} WHERE ({where})")
    if date_range and spec.date:
        sql += f" AND {_ident(spec.date)} BETWEEN ? AND ?"
        params += list(date_range)
    sql += " AND user_id=?"
    params.append(current_user_id())
    if spec.date:
        sql += f" ORDER BY {_ident(spec.date)} DESC"
    sql += f" LIMIT {int(per_section)}"
    try:
        return execute(sql, params, fetchall=True) or []
    except Exception:
        # A table the running schema doesn't have yet (mid-migration) must not
        # take the whole search down with it.
        return []


def global_search(query: str, limit: int = 40, per_section: int = 5,
                  include_private: bool = True) -> dict:
    """Search everything the user has recorded.

    `limit` caps the grand total of items returned so a one-letter-ish query on a
    long history can't return a thousand rows; `per_section` caps each table.
    """
    from .insights import _parse_date_query
    clean_q, date_range = _parse_date_query(query)
    # A bare date phrase ("last week") means "everything then", so the text
    # pattern degrades to match-all rather than returning nothing.
    text_q = f'%{clean_q.lower()}%' if clean_q else '%'
    out = {'query': query, 'total': 0, 'sections': [], 'date_range': date_range}
    if not clean_q and not date_range:
        return out

    for spec in SEARCHABLE:
        if out['total'] >= limit:
            break
        if spec.private and not include_private:
            continue
        room = min(per_section, limit - out['total'])
        rows = _run(spec, text_q, date_range, room)
        if not rows:
            continue
        items = []
        for r in rows:
            d = dict(r)
            try:
                d['_title'] = str(spec.title(d) or '').strip()
            except Exception:
                d['_title'] = ''
            if not d['_title']:
                continue          # nothing readable to show — don't render a blank row
            try:
                d['_meta'] = str((spec.meta(d) if spec.meta else '') or '')
            except Exception:
                d['_meta'] = ''
            items.append(d)
        if not items:
            continue
        out['sections'].append({'type': spec.type, 'label': spec.label,
                                'icon': spec.icon, 'view': spec.view,
                                'private': spec.private, 'items': items})
        out['total'] += len(items)
    return out
