"""PHQ-9 and GAD-7: two questionnaires, and a score to take to a doctor.

These are published, freely reproducible screening instruments with fixed
wording and fixed, published scoring. That is exactly why they belong in an app
that refuses to invent clinical content: nothing here is Arogo's opinion. The
items are the instrument's, the arithmetic is addition, and the severity bands
are the published cut-offs.

What this is NOT, stated plainly and repeated in the response the UI renders:

  It is not a diagnosis. A score of 16 does not mean someone has depression. The
  instruments are screening tools; the band is a description of the answers just
  given, on two weeks, on one day.

  It is not a trend to be read casually. Two scores a week apart are two moments,
  not a direction, and the app does not draw a line between them or say anyone is
  "improving". People make decisions about medication on that kind of sentence.

  It is not a substitute for anyone. The output's whole purpose is to be shown to
  a person, which is why it prints and why the answers are kept.

PHQ-9 ITEM 9 asks about thoughts of self-harm or of being better off dead. A
non-zero answer there is not a number to file away. The response carries a flag
the UI must act on, and the guidance is deliberately conservative: tell a person
today, and here is your own country's emergency number — read from the table the
app already ships, never a helpline invented for a country nobody checked.
"""
import datetime as dt
import json

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date

# The four-point frequency scale both instruments share, over the last 2 weeks.
CHOICES = [
    (0, 'Not at all'),
    (1, 'Several days'),
    (2, 'More than half the days'),
    (3, 'Nearly every day'),
]

PHQ9_ITEMS = [
    'Little interest or pleasure in doing things',
    'Feeling down, depressed, or hopeless',
    'Trouble falling or staying asleep, or sleeping too much',
    'Feeling tired or having little energy',
    'Poor appetite or overeating',
    'Feeling bad about yourself — or that you are a failure, or have let '
    'yourself or your family down',
    'Trouble concentrating on things, such as reading the newspaper or '
    'watching television',
    'Moving or speaking so slowly that other people could have noticed — or '
    'the opposite, being so fidgety or restless that you have been moving '
    'around a lot more than usual',
    'Thoughts that you would be better off dead, or of hurting yourself in '
    'some way',
]

GAD7_ITEMS = [
    'Feeling nervous, anxious, or on edge',
    'Not being able to stop or control worrying',
    'Worrying too much about different things',
    'Trouble relaxing',
    'Being so restless that it is hard to sit still',
    'Becoming easily annoyed or irritable',
    'Feeling afraid, as if something awful might happen',
]

# Published cut-offs. Kept as data so a band is never a judgement written in code.
PHQ9_BANDS = [(0, 4, 'Minimal'), (5, 9, 'Mild'), (10, 14, 'Moderate'),
              (15, 19, 'Moderately severe'), (20, 27, 'Severe')]
GAD7_BANDS = [(0, 4, 'Minimal'), (5, 9, 'Mild'), (10, 14, 'Moderate'),
              (15, 21, 'Severe')]

# The item index whose answer is never just a number. Zero-based.
PHQ9_RISK_ITEM = 8

INSTRUMENTS = {
    'phq9': {'key': 'phq9', 'name': 'PHQ-9',
             'about': 'A nine-question screen for low mood, used widely in '
                      'general practice.',
             'items': PHQ9_ITEMS, 'bands': PHQ9_BANDS, 'max': 27,
             'risk_item': PHQ9_RISK_ITEM},
    'gad7': {'key': 'gad7', 'name': 'GAD-7',
             'about': 'A seven-question screen for anxiety, used widely in '
                      'general practice.',
             'items': GAD7_ITEMS, 'bands': GAD7_BANDS, 'max': 21,
             'risk_item': None},
}

# Said on every response, not tucked into a footer.
NOT_A_DIAGNOSIS = (
    'This is a questionnaire, not a diagnosis. It describes the answers you '
    'just gave, about the last two weeks. Only a clinician can say what it '
    'means for you — take it to them.'
)


def instrument(key):
    return INSTRUMENTS.get(str(key or '').lower())


def list_instruments() -> list:
    return [{'key': i['key'], 'name': i['name'], 'about': i['about'],
             'items': i['items'], 'choices': [{'value': v, 'label': l} for v, l in CHOICES],
             'max': i['max']}
            for i in INSTRUMENTS.values()]


def _band(score, bands):
    for lo, hi, label in bands:
        if lo <= score <= hi:
            return label
    return None


def _clean_answers(inst, raw):
    """Every item answered, each 0–3. A partial questionnaire has no valid total,
    so it is refused rather than scored as if the blanks were zeros — which would
    read as 'not at all' and quietly lower the result."""
    if not isinstance(raw, list) or len(raw) != len(inst['items']):
        raise ValueError('Please answer every question.')
    out = []
    for v in raw:
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError('Please answer every question.')
        if n < 0 or n > 3:
            raise ValueError('Please answer every question.')
        out.append(n)
    return out


def score_only(instrument_key, answers) -> dict:
    """Score without saving — the same arithmetic the saved run uses."""
    inst = instrument(instrument_key)
    if not inst:
        raise ValueError('Unknown questionnaire.')
    ans = _clean_answers(inst, answers)
    total = sum(ans)
    risk = (inst['risk_item'] is not None and ans[inst['risk_item']] > 0)
    return {'instrument': inst['key'], 'name': inst['name'], 'score': total,
            'max': inst['max'], 'band': _band(total, inst['bands']),
            'answers': ans, 'risk_flag': risk,
            'not_a_diagnosis': NOT_A_DIAGNOSIS}


def save_run(instrument_key, answers, taken_on=None) -> dict:
    inst = instrument(instrument_key)
    if not inst:
        raise ValueError('Unknown questionnaire.')
    result = score_only(instrument_key, answers)
    day = taken_on if (taken_on and valid_date(taken_on)) else user_today()
    rid = new_id()
    execute("""INSERT INTO questionnaire_runs
                 (id, instrument, answers, score, taken_on, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (rid, inst['key'], json.dumps(result['answers']), result['score'],
             day, now_iso(), current_user_id()), commit=True)
    result['id'] = rid
    result['taken_on'] = day
    return result


def list_runs(instrument_key=None, limit: int = 24) -> list:
    """Past scores, newest first.

    Returned as a list of moments, never as a trend. The app does not compute a
    direction or call anyone "improving": two scores a week apart are two days,
    and people make decisions about medication on that kind of sentence.
    """
    uid = current_user_id()
    sql = "SELECT * FROM questionnaire_runs WHERE user_id=?"
    params = [uid]
    if instrument_key and instrument(instrument_key):
        sql += " AND instrument=?"
        params.append(instrument(instrument_key)['key'])
    sql += f" ORDER BY taken_on DESC, created_at DESC LIMIT {max(1, min(int(limit or 24), 200))}"
    rows = execute(sql, params, fetchall=True) or []
    out = []
    for r in rows:
        inst = instrument(r['instrument']) or {}
        try:
            answers = json.loads(r['answers'])
        except Exception:
            answers = []
        out.append({'id': r['id'], 'instrument': r['instrument'],
                    'name': inst.get('name', r['instrument']),
                    'score': r['score'], 'max': inst.get('max'),
                    'band': _band(r['score'], inst.get('bands', [])),
                    'taken_on': r['taken_on'], 'answers': answers})
    return out


def delete_run(rid) -> bool:
    execute("DELETE FROM questionnaire_runs WHERE id=? AND user_id=?",
            (rid, current_user_id()), commit=True)
    return True


def risk_response(country=None) -> dict:
    """What to show when PHQ-9 item 9 is answered above zero.

    Deliberately short and concrete. No reassurance, no interpretation of the
    score, and no invented helpline — the numbers come from the emergency table
    the app already ships, and if a country is not in it the guidance says so
    rather than offering a number that might not connect.
    """
    numbers, country_name = [], None
    try:
        from .locale_config import (emergency_numbers, valid_country,
                                    EMERGENCY_NUMBERS)
        # Resolved explicitly rather than trusting emergency_numbers()'s answer.
        # That helper falls back to the app's default country for anything it
        # doesn't recognise, which is fine for showing a health-ID card and
        # actively dangerous here: it would print one country's ambulance number
        # to someone in another, at the moment they most need it to connect.
        code = valid_country(country) if country else None
        if code and code in EMERGENCY_NUMBERS:
            info = emergency_numbers(code) or {}
            numbers = info.get('numbers') or []
            country_name = info.get('country_name')
    except Exception:
        pass
    return {
        'headline': 'You answered that you have had thoughts of being better '
                    'off dead, or of hurting yourself.',
        'ask': 'Please tell someone today — your doctor, or someone you trust. '
               'You do not have to explain it well, and you do not have to be '
               'in crisis to ask for help.',
        'urgent': 'If you might act on those thoughts, treat it as an emergency '
                  'and call now.',
        'numbers': numbers,
        'country_name': country_name,
        # When the country isn't in the table, say so. A wrong number is worse
        # than no number to someone dialling it at 3am.
        'no_numbers_note': None if numbers else
            'Arogo does not have emergency numbers for your country on file — '
            'use your local emergency number.',
    }
