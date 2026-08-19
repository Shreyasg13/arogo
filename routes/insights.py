"""routes/insights.py — Health report, goal progress, global search, data export, notifications."""
from db.food import get_user_timezone
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from auth import require_auth
import os, json as json_mod
from db import *
from config import Config

import csv, io, datetime as dt_mod
bp = Blueprint("insights", __name__)

@bp.route('/api/report/weekly')
@require_auth
def api_weekly_report():
    return jsonify(generate_weekly_report())


@bp.route('/api/report/review')
@require_auth
def api_health_review():
    """Richer on-screen recap for a 7- or 30-day window: adherence, vitals
    direction, goal progress and honest wins."""
    try:
        days = int(request.args.get('days', 7))
    except (TypeError, ValueError):
        days = 7
    return jsonify(generate_health_review(days))


@bp.route('/api/doctor-summary')
@require_auth
def api_doctor_summary():
    """Compile a one-page summary to bring to a medical appointment:
    active medicines, latest vitals, recent symptoms, conditions/allergies,
    and 30-day medication adherence."""
    from db.core import execute, current_user_id
    import datetime as dt

    profile = get_profile() or {}
    emg = get_emergency_info() or {}
    urow = execute("SELECT name, email FROM users WHERE id=?", (current_user_id(),), fetchone=True)

    meds = [{'name': m['name'], 'dosage': m.get('dosage'), 'unit': m.get('unit'),
             'frequency': m.get('frequency'), 'times': m.get('times'),
             'with_food': m.get('with_food'), 'timing_text': m.get('timing_text', '')}
            for m in list_medicines() if m.get('active')]

    latest = {}
    for v in get_vitals(days=90):          # ordered newest-first
        if v['type'] not in latest:
            latest[v['type']] = {'value1': v['value1'], 'value2': v.get('value2'),
                                 'unit': v.get('unit'), 'date': v.get('date_key')}

    symptoms = [{'name': s['name'], 'severity': s.get('severity'), 'date': s.get('date_key')}
                for s in get_symptoms(30)[:25]]

    from db import list_doctor_questions
    questions = [q['question'] for q in list_doctor_questions() if not q.get('asked')]

    return jsonify({
        'generated': dt.date.today().isoformat(),
        'person': {
            'name': (urow['name'] if urow else '') or (urow['email'] if urow else ''),
            'age': profile.get('age'), 'gender': profile.get('gender'),
            'blood_type': emg.get('blood_type') or None,
        },
        'conditions': emg.get('conditions') or '',
        'allergies': emg.get('allergies') or '',
        'medications': meds,
        'vitals': latest,
        'symptoms': symptoms,
        'questions': questions,
        'adherence_30d': get_adherence_stats(30),
        'visit_prep': get_visit_prep(),
    })

# ══════════════════════════════════════════════════════════════════════════════
# Goal Progress
# ══════════════════════════════════════════════════════════════════════════════


@bp.route('/api/calorie-balance')
@require_auth
def api_calorie_balance():
    """
    Today's calorie balance: eaten vs burned vs target.
    Also returns 7-day daily breakdown for trend chart.
    """
    import datetime as dt
    from db import get_nutrition_summary, get_profile, calc_tdee
    from db.fitness import list_activities

    today    = dt.date.today().isoformat()
    raw_prof = get_profile()
    targets  = calc_tdee(raw_prof)
    profile  = {'profile': raw_prof, 'targets': targets}
    # target_calories is present-but-None until the profile has weight/height/
    # age/gender. It stays None: `or 2000` used to invent a calorie budget for
    # a user who never gave us a body to compute one from, and the dashboard
    # then printed it as "2000 kcal remaining" — the most confident number on
    # a brand-new user's first screen, about a budget nobody had calculated.
    # calc_tdee is careful to return None; honour it and let the UI ask.
    target = targets.get('target_calories')
    target = int(target) if target else None
    has_target = target is not None

    # Today's food
    food_sum = get_nutrition_summary(today)
    eaten    = round(food_sum['totals'].get('calories', 0))

    # Today's workouts (calories floored at 0 — a workout never shrinks the budget)
    all_acts      = list_activities()
    today_acts    = [a for a in all_acts if a.get('date') == today]
    burned_today  = sum(max(0, a.get('calories', 0) or 0) for a in today_acts)

    # Net balance: positive = deficit (under budget), negative = surplus (over
    # budget). budget = target + burned (exercise earns more calories).
    # With no target there is no budget and no "remaining" — those are None
    # rather than a number derived from a guess.
    budget  = (target + burned_today) if has_target else None
    net     = (budget - eaten) if has_target else None

    # 7-day daily breakdown
    daily = []
    for i in range(6, -1, -1):
        d     = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        fs    = get_nutrition_summary(d)
        d_eat = round(fs['totals'].get('calories', 0))
        d_acts = [a for a in all_acts if a.get('date') == d]
        d_burn = sum(max(0, a.get('calories', 0) or 0) for a in d_acts)
        d_bud  = (target + d_burn) if has_target else None
        daily.append({
            'date':    d,
            'eaten':   d_eat,
            'burned':  d_burn,
            'target':  target,
            'budget':  d_bud,
            'net':     (d_bud - d_eat) if has_target else None,
            'logged':  fs['log_count'] > 0,
        })

    return jsonify({
        'has_target': has_target,
        'today': {
            'date':    today,
            'eaten':   eaten,
            'burned':  burned_today,
            'target':  target,
            'budget':  budget,
            'net':     net,
            'workouts': [
                {'name': a.get('name') or a.get('type','workout'),
                 'type': a.get('type',''),
                 'calories': a.get('calories', 0),
                 'duration': a.get('duration', 0)}
                for a in today_acts
            ],
        },
        'daily':   daily,
        'targets': targets,
        'profile': profile.get('profile', {}),
    })


@bp.route('/api/fitness/prs')
@require_auth
def api_fitness_prs():
    """
    Compute Personal Records from all-time activity history.
    Returns PRs grouped by type + a recent PR flag (set in last 30 days).
    """
    import datetime as dt
    from db.fitness import list_activities

    activities  = list_activities()
    if not activities:
        return jsonify({'prs': [], 'total_activities': 0, 'has_data': False})

    today       = dt.date.today()
    recent_cutoff = (today - dt.timedelta(days=30)).isoformat()

    DISTANCE_TYPES  = {'running', 'cycling', 'swimming', 'walking', 'hiking'}
    ELEVATION_TYPES = {'running', 'cycling', 'hiking'}
    STEPS_TYPES     = {'running', 'walking'}

    # ── Per-category PRs ─────────────────────────────────────────
    # Longest distance per type
    distance_prs = {}
    for a in activities:
        t = a.get('type', 'other')
        if t not in DISTANCE_TYPES: continue
        d = float(a.get('distance') or 0)
        if d <= 0: continue
        if t not in distance_prs or d > distance_prs[t]['value']:
            distance_prs[t] = {
                'value':    d,
                'unit':     'km',
                'date':     a['date'],
                'name':     a.get('name') or t,
                'activity_id': a['id'],
                'is_recent': a['date'] >= recent_cutoff,
            }

    # Longest duration per type
    duration_prs = {}
    for a in activities:
        t = a.get('type', 'other')
        dur = int(a.get('duration') or 0)
        if dur <= 0: continue
        if t not in duration_prs or dur > duration_prs[t]['value']:
            duration_prs[t] = {
                'value':    dur,
                'unit':     'min',
                'date':     a['date'],
                'name':     a.get('name') or t,
                'activity_id': a['id'],
                'is_recent': a['date'] >= recent_cutoff,
            }

    # Most calories burned (single session) per type
    calorie_prs = {}
    for a in activities:
        t = a.get('type', 'other')
        cal = int(a.get('calories') or 0)
        if cal <= 0: continue
        if t not in calorie_prs or cal > calorie_prs[t]['value']:
            calorie_prs[t] = {
                'value':    cal,
                'unit':     'kcal',
                'date':     a['date'],
                'name':     a.get('name') or t,
                'activity_id': a['id'],
                'is_recent': a['date'] >= recent_cutoff,
            }

    # Most steps (overall, not per type)
    best_steps = None
    for a in activities:
        if a.get('type') not in STEPS_TYPES: continue
        s = int(a.get('steps') or 0)
        if s <= 0: continue
        if not best_steps or s > best_steps['value']:
            best_steps = {
                'value': s, 'unit': 'steps',
                'date':  a['date'],
                'name':  a.get('name') or a.get('type'),
                'activity_id': a['id'],
                'is_recent': a['date'] >= recent_cutoff,
            }

    # Highest elevation gain (overall)
    best_elevation = None
    for a in activities:
        if a.get('type') not in ELEVATION_TYPES: continue
        e = float(a.get('elevation') or 0)
        if e <= 0: continue
        if not best_elevation or e > best_elevation['value']:
            best_elevation = {
                'value': e, 'unit': 'm',
                'date':  a['date'],
                'name':  a.get('name') or a.get('type'),
                'activity_id': a['id'],
                'is_recent': a['date'] >= recent_cutoff,
            }

    # Most active week (total duration)
    from collections import defaultdict
    week_totals = defaultdict(int)
    for a in activities:
        d = a.get('date', '')
        if not d: continue
        dt_obj   = dt.date.fromisoformat(d)
        week_key = (dt_obj - dt.timedelta(days=dt_obj.weekday())).isoformat()
        week_totals[week_key] += int(a.get('duration') or 0)

    best_week = None
    if week_totals:
        best_wk  = max(week_totals, key=week_totals.get)
        best_week = {
            'value':    week_totals[best_wk],
            'unit':     'min',
            'date':     best_wk,
            'name':     'Active week',
            'is_recent': best_wk >= recent_cutoff,
        }

    # ── Build PR list ─────────────────────────────────────────────
    TYPE_LABELS = {
        'running': 'Running', 'cycling': 'Cycling', 'swimming': 'Swimming',
        'walking': 'Walking',  'hiking':  'Hiking',  'yoga':     'Yoga',
        'gym':     'Gym',      'hiit':    'HIIT',    'other':    'Other',
    }
    TYPE_ICONS = {
        'running': '🏃', 'cycling': '🚴', 'swimming': '🏊',
        'walking': '🚶', 'hiking':  '🥾', 'yoga':     '🧘',
        'gym':     '🏋️',  'hiit':    '⚡', 'other':    '🏅',
    }

    prs = []

    for t, pr in distance_prs.items():
        prs.append({
            'category':  TYPE_LABELS.get(t, t),
            'icon':      TYPE_ICONS.get(t, '🏅'),
            'metric':    'Longest distance',
            'value':     round(pr['value'], 2),
            'unit':      'km',
            'date':      pr['date'],
            'name':      pr['name'],
            'is_recent': pr['is_recent'],
            'type':      t,
        })

    for t, pr in duration_prs.items():
        label = TYPE_LABELS.get(t, t)
        h, m  = divmod(pr['value'], 60)
        prs.append({
            'category':     label,
            'icon':         TYPE_ICONS.get(t, '🏅'),
            'metric':       'Longest session',
            'value':        pr['value'],
            'value_display': f"{int(h)}h {int(m)}m" if h else f"{int(m)}m",
            'unit':         'min',
            'date':         pr['date'],
            'name':         pr['name'],
            'is_recent':    pr['is_recent'],
            'type':         t,
        })

    for t, pr in calorie_prs.items():
        prs.append({
            'category':  TYPE_LABELS.get(t, t),
            'icon':      TYPE_ICONS.get(t, '🏅'),
            'metric':    'Most calories burned',
            'value':     pr['value'],
            'unit':      'kcal',
            'date':      pr['date'],
            'name':      pr['name'],
            'is_recent': pr['is_recent'],
            'type':      t,
        })

    if best_steps:
        prs.append({
            'category': 'Steps', 'icon': '👟',
            'metric':   'Most steps in a session',
            'value':    best_steps['value'],
            'value_display': f"{best_steps['value']:,}",
            'unit':     'steps',
            'date':     best_steps['date'],
            'name':     best_steps['name'],
            'is_recent': best_steps['is_recent'],
        })

    if best_elevation:
        prs.append({
            'category': 'Elevation', 'icon': '⛰️',
            'metric':   'Most elevation gain',
            'value':    best_elevation['value'],
            'unit':     'm',
            'date':     best_elevation['date'],
            'name':     best_elevation['name'],
            'is_recent': best_elevation['is_recent'],
        })

    if best_week:
        h, m = divmod(best_week['value'], 60)
        prs.append({
            'category': 'Weekly', 'icon': '📅',
            'metric':   'Most active week',
            'value':    best_week['value'],
            'value_display': f"{int(h)}h {int(m)}m",
            'unit':     'min',
            'date':     best_week['date'],
            'name':     'Week of ' + best_week['date'],
            'is_recent': best_week['is_recent'],
        })

    # Sort: recent PRs first, then by type alphabetically
    prs.sort(key=lambda x: (not x['is_recent'], x['category']))

    return jsonify({
        'prs':              prs,
        'total_activities': len(activities),
        'recent_prs':       sum(1 for p in prs if p['is_recent']),
        'has_data':         True,
    })


@bp.route('/api/mood-sleep/correlation')
@require_auth
def api_mood_sleep_correlation():
    """
    Join 90 days of mood logs with sleep logs on date_key.
    Returns:
    - scatter points (sleep_duration, mood_score) for chart
    - per-mood sleep averages
    - correlation strength: strong/moderate/weak/none
    - insight text
    """
    import datetime as dt, math
    from db.wellness import get_thoughts_range, get_sleep_logs

    days     = int(request.args.get('days', 90))
    thoughts = get_thoughts_range(days=days)
    sleeps   = get_sleep_logs(days=days)

    # Mood → numeric score
    MOOD_SCORE = {
        'terrible': 1, 'sad': 2, 'anxious': 3,
        'neutral':  4, 'calm': 5, 'tired':   3,
        'happy':    6, 'excited': 7,
    }
    MOOD_POSITIVE = {'calm', 'happy', 'excited'}
    MOOD_NEGATIVE = {'terrible', 'sad', 'anxious', 'tired'}

    # Index sleep by date (take the latest entry per day)
    sleep_by_date = {}
    for s in sleeps:
        d = s['date_key']
        if d not in sleep_by_date or s['duration_h'] > sleep_by_date[d]['duration_h']:
            sleep_by_date[d] = s

    # Index moods by date — take the highest-score mood per day
    mood_by_date = {}
    for t in thoughts:
        d = t['date_key']
        score = MOOD_SCORE.get(t.get('mood', 'neutral'), 4)
        if d not in mood_by_date or score > mood_by_date[d]['score']:
            mood_by_date[d] = {
                'mood':     t.get('mood', 'neutral'),
                'score':    score,
                'date_key': d,
            }

    # Join: only days where BOTH exist
    paired = []
    for date_key, mood_data in mood_by_date.items():
        if date_key not in sleep_by_date:
            continue
        s = sleep_by_date[date_key]
        paired.append({
            'date':     date_key,
            'mood':     mood_data['mood'],
            'score':    mood_data['score'],
            'duration': round(s['duration_h'], 1),
            'quality':  s['quality'],
        })

    if len(paired) < 3:
        return jsonify({
            'paired':      paired,
            'has_data':    len(paired) > 0,
            'need_more':   True,
            'need_count':  max(0, 5 - len(paired)),
            'insight':     None,
            'per_mood':    {},
            'correlation': None,
        })

    # ── Per-mood sleep averages ───────────────────────────────────
    from collections import defaultdict
    mood_groups = defaultdict(list)
    for p in paired:
        mood_groups[p['mood']].append(p['duration'])

    per_mood = {
        mood: {
            'avg_duration': round(sum(durs)/len(durs), 1),
            'count':        len(durs),
            'max':          round(max(durs), 1),
            'min':          round(min(durs), 1),
        }
        for mood, durs in mood_groups.items()
    }

    # ── Pearson correlation (duration × mood score) ───────────────
    n   = len(paired)
    xs  = [p['duration'] for p in paired]
    ys  = [p['score']    for p in paired]
    mx  = sum(xs) / n
    my  = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = math.sqrt(sum((x - mx)**2 for x in xs))
    dy  = math.sqrt(sum((y - my)**2 for y in ys))
    r   = round(num / (dx * dy), 3) if dx * dy > 0 else 0

    if abs(r) >= 0.5:   strength = 'strong'
    elif abs(r) >= 0.3: strength = 'moderate'
    elif abs(r) >= 0.1: strength = 'weak'
    else:               strength = 'none'

    direction = 'positive' if r > 0 else 'negative'

    # ── Insight sentence ──────────────────────────────────────────
    pos_avg = sum(p['duration'] for p in paired if p['mood'] in MOOD_POSITIVE)
    pos_n   = sum(1 for p in paired if p['mood'] in MOOD_POSITIVE)
    neg_avg = sum(p['duration'] for p in paired if p['mood'] in MOOD_NEGATIVE)
    neg_n   = sum(1 for p in paired if p['mood'] in MOOD_NEGATIVE)
    pos_dur = round(pos_avg / pos_n, 1) if pos_n else None
    neg_dur = round(neg_avg / neg_n, 1) if neg_n else None

    if strength == 'none':
        insight = f'No clear pattern yet across {n} matched days. Keep logging!'
    elif strength == 'strong' and direction == 'positive':
        insight = f'Strong link: more sleep → better mood. You sleep {pos_dur}h on good days vs {neg_dur}h on tough ones.' if pos_dur and neg_dur else f'Strong positive correlation (r={r}) across {n} days.'
    elif strength == 'moderate' and direction == 'positive':
        insight = f'Moderate link: longer sleep tends to lift your mood ({n} days analysed).'
        if pos_dur and neg_dur:
            diff = round(pos_dur - neg_dur, 1)
            insight = f'On your best mood days you sleep ~{diff}h more than on tough days ({pos_dur}h vs {neg_dur}h).'
    elif direction == 'negative':
        insight = f'Interesting pattern: your mood scores are higher after shorter sleep — possibly you wake earlier on energised days.'
    else:
        insight = f'Weak trend across {n} days. More data will clarify the pattern.'

    # ── 7h threshold split ────────────────────────────────────────
    above_7 = [p for p in paired if p['duration'] >= 7]
    below_7 = [p for p in paired if p['duration'] < 7]
    avg_mood_above = round(sum(p['score'] for p in above_7) / len(above_7), 2) if above_7 else None
    avg_mood_below = round(sum(p['score'] for p in below_7) / len(below_7), 2) if below_7 else None

    return jsonify({
        'paired':       paired,
        'has_data':     True,
        'need_more':    False,
        'days_analysed':days,
        'matched_days': n,
        'correlation':  {'r': r, 'strength': strength, 'direction': direction},
        'per_mood':     per_mood,
        'threshold': {
            'above_7h': {'count': len(above_7), 'avg_mood_score': avg_mood_above},
            'below_7h': {'count': len(below_7), 'avg_mood_score': avg_mood_below},
        },
        'insight': insight,
    })


@bp.route('/api/weekly-digest')
@require_auth
def api_weekly_digest():
    """Weekly insight digest — logic lives in db.insights.generate_weekly_digest."""
    from db.insights import generate_weekly_digest
    return jsonify(generate_weekly_digest())


@bp.route('/api/insights/cards')
@require_auth
def api_insight_cards():
    """Rules-based dashboard insight cards (empty list until data exists)."""
    from db.insights import get_insight_cards
    return jsonify({'cards': get_insight_cards()})



@bp.route('/api/progress')
@require_auth
def api_goal_progress():
    return jsonify(get_goal_progress())

# ══════════════════════════════════════════════════════════════════════════════
# Global Search
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/search')
@require_auth
def api_global_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'query': q, 'total': 0, 'sections': []})
    return jsonify(global_search(q))

# ══════════════════════════════════════════════════════════════════════════════
# Data Export
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/export/counts')
@require_auth
def api_export_counts():
    """Return row counts per section for the export preview."""
    from db.core import execute, current_user_id
    uid = current_user_id()
    from_date = request.args.get('from', '2000-01-01')
    to_date   = request.args.get('to',   today_iso(get_user_timezone()))
    counts = {
        'food_logs':          execute("SELECT COUNT(*) as n FROM food_logs WHERE date_key BETWEEN ? AND ? AND user_id=?",       (from_date, to_date, uid), fetchone=True)['n'],
        'fitness_activities': execute("SELECT COUNT(*) as n FROM fitness_activities WHERE date BETWEEN ? AND ? AND user_id=?",  (from_date, to_date, uid), fetchone=True)['n'],
        'sleep_logs':         execute("SELECT COUNT(*) as n FROM sleep_logs WHERE date_key BETWEEN ? AND ? AND user_id=?",      (from_date, to_date, uid), fetchone=True)['n'],
        'symptoms':           execute("SELECT COUNT(*) as n FROM symptoms WHERE date_key BETWEEN ? AND ? AND user_id=?",        (from_date, to_date, uid), fetchone=True)['n'],
        'vitals':             execute("SELECT COUNT(*) as n FROM vitals WHERE date_key BETWEEN ? AND ? AND user_id=?",          (from_date, to_date, uid), fetchone=True)['n'],
        'thoughts':           execute("SELECT COUNT(*) as n FROM thoughts WHERE date_key BETWEEN ? AND ? AND user_id=?",        (from_date, to_date, uid), fetchone=True)['n'],
        'todos':              execute("SELECT COUNT(*) as n FROM todos WHERE created_at BETWEEN ? AND ? AND user_id=?",         (from_date, to_date+'T23:59:59', uid), fetchone=True)['n'],
        'body_metrics':       execute("SELECT COUNT(*) as n FROM body_metrics WHERE date_key BETWEEN ? AND ? AND user_id=?",    (from_date, to_date, uid), fetchone=True)['n'],
        'hydration_logs':     execute("SELECT COUNT(*) as n FROM hydration_logs WHERE date_key BETWEEN ? AND ? AND user_id=?",  (from_date, to_date, uid), fetchone=True)['n'],
        'habits':             execute("SELECT COUNT(*) as n FROM habits WHERE active=1 AND user_id=?",                          (uid,), fetchone=True)['n'],
        'medicines':          execute("SELECT COUNT(*) as n FROM medicines WHERE active=1 AND user_id=?",                       (uid,), fetchone=True)['n'],
        # "Connected a family member" = sent a family invite OR added a
        # zero-install alert contact (a phone). Either means a caregiver is
        # linked — the first-run step that most improves retention.
        'family': (
            execute("SELECT COUNT(*) as n FROM family_invites WHERE invited_by=?", (uid,), fetchone=True)['n']
            + execute("SELECT COUNT(*) as n FROM caregiver_contacts WHERE user_id=?", (uid,), fetchone=True)['n']
        ),
    }
    return jsonify(counts)

@bp.route('/api/backup')
@require_auth
def api_backup():
    """One-file full snapshot for self-hosted backup — every table this user
    owns, secrets redacted. Downloads as an Arogo backup .json."""
    import json as _json, datetime as dt_mod
    from flask import Response
    from db.account import export_all_data
    from db.core import current_user_id
    data = export_all_data(current_user_id())
    data['_backup'] = {'app': 'arogo', 'version': 1}
    body = _json.dumps(data, indent=2, default=str)
    stamp = today_iso(get_user_timezone())
    return Response(body, mimetype='application/json', headers={
        'Content-Disposition': f'attachment; filename="arogo-backup-{stamp}.json"'})


@bp.route('/api/import', methods=['POST'])
@require_auth
def api_import():
    """Restore a backup into this user's own data (replaces it). The client
    previews the row counts and confirms before this is called."""
    from db.account import import_all_data
    from db.core import current_user_id
    data = request.get_json(silent=True)
    try:
        summary = import_all_data(current_user_id(), data or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'restored': summary,
                    'total': sum(summary.values())})


@bp.route('/api/export')
@require_auth
def api_export():
    import csv, io, datetime as dt_mod
    fmt       = request.args.get('format', 'json')
    sections  = request.args.get('sections', 'all')  # comma-separated or 'all'
    from_date = request.args.get('from', '2000-01-01')
    to_date   = request.args.get('to', today_iso(get_user_timezone()))

    wanted = sections.split(',') if sections != 'all' else None
    def want(k): return wanted is None or k in wanted

    from db.core import execute, current_user_id
    uid = current_user_id()
    data = {}

    if want('food_logs'):
        rows = execute("SELECT * FROM food_logs WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['food_logs'] = [dict(r) for r in rows]
    if want('fitness_activities'):
        rows = execute("SELECT * FROM fitness_activities WHERE date BETWEEN ? AND ? AND user_id=? ORDER BY date DESC", (from_date, to_date, uid), fetchall=True)
        data['fitness_activities'] = [dict(r) for r in rows]
    if want('sleep_logs'):
        rows = execute("SELECT * FROM sleep_logs WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['sleep_logs'] = [dict(r) for r in rows]
    if want('symptoms'):
        rows = execute("SELECT * FROM symptoms WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['symptoms'] = [dict(r) for r in rows]
    if want('vitals'):
        rows = execute("SELECT * FROM vitals WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['vitals'] = [dict(r) for r in rows]
    if want('thoughts'):
        rows = execute("SELECT * FROM thoughts WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['thoughts'] = [dict(r) for r in rows]
    if want('todos'):
        rows = execute("SELECT * FROM todos WHERE created_at BETWEEN ? AND ? AND user_id=? ORDER BY created_at DESC", (from_date, to_date+'T23:59:59', uid), fetchall=True)
        data['todos'] = [dict(r) for r in rows]
    if want('body_metrics'):
        rows = execute("SELECT * FROM body_metrics WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['body_metrics'] = [dict(r) for r in rows]
    if want('hydration_logs'):
        rows = execute("SELECT * FROM hydration_logs WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['hydration_logs'] = [dict(r) for r in rows]
    if want('habits'):
        rows = execute("SELECT * FROM habits WHERE active=1 AND user_id=? ORDER BY created_at", (uid,), fetchall=True)
        data['habits'] = [dict(r) for r in rows]
        log_rows = execute("SELECT * FROM habit_logs WHERE date_key BETWEEN ? AND ? AND user_id=? ORDER BY date_key DESC", (from_date, to_date, uid), fetchall=True)
        data['habit_logs'] = [dict(r) for r in log_rows]
    if want('medicines'):
        rows = execute("SELECT * FROM medicines WHERE active=1 AND user_id=? ORDER BY name", (uid,), fetchall=True)
        data['medicines'] = [dict(r) for r in rows]

    # Add metadata header
    import datetime as dt
    meta = {
        'exported_at': dt.datetime.now().isoformat(),
        'from_date': from_date,
        'to_date': to_date,
        'sections': list(data.keys()),
        'total_records': sum(len(v) for v in data.values()),
        'app': 'Arogo'
    }

    fname_base = f"medeasy_{from_date}_to_{to_date}"

    if fmt == 'csv':
        output = io.StringIO()
        # Write metadata as comments
        output.write("# Arogo Export\n")
        output.write('# Exported: ' + meta['exported_at'] + '\n')
        output.write('# Period: ' + from_date + ' to ' + to_date + '\n\n')
        for section, rows in data.items():
            if not rows: continue
            output.write('# === ' + section.upper().replace('_',' ') + ' (' + str(len(rows)) + ' records) ===\n')
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            output.write('\n')
        csv_data = output.getvalue()
        from flask import Response
        return Response(csv_data, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename={fname_base}.csv'})
    else:
        from flask import Response
        import json as json_mod
        export_obj = {'_meta': meta, **data}
        return Response(json_mod.dumps(export_obj, indent=2, default=str),
                        mimetype='application/json',
                        headers={'Content-Disposition': f'attachment; filename={fname_base}.json'})


# NOTE: /api/hydration (day/week/POST/DELETE) and /api/sleep (GET/POST/DELETE)
# live in routes/wellness.py — the duplicate definitions here were dead code
# (wellness registers first, so its rules own the URL map). Removed. See the
# no-duplicate-route guard in tests/test_conventions.py.

# NOTE: GET/POST /api/body-metrics live in routes/wellness.py — the duplicate
# definitions here were dead code (wellness registers first, so its rules win),
# and the dead POST even carried a fabricated height_cm=170 fallback the project
# forbids. Removed; wellness's log_body_metric handles the date/height defaults
# honestly (BMI stays None without a real height).

# NOTE: /api/habits (GET/POST/DELETE and the /<hid>/toggle) live in
# routes/wellness.py — the duplicate definitions here were dead code (wellness
# registers first) and were removed.

# NOTE: /api/symptoms (GET/POST) and /api/symptoms/<sid> (DELETE) live in
# routes/wellness.py — the duplicate definitions here were dead code (wellness
# registers first). Its POST wraps log_symptom's ValueError into a 400 (which
# fires on a missing name too), so no validation is lost. Removed.

# ══════════════════════════════════════════════════════════════════════════════
# Vitals Routes — the derived/insight endpoints only.
# NOTE: /api/vitals (GET/POST/DELETE CRUD) lives in routes/wellness.py; the
# duplicate CRUD here was dead code (wellness registers first) and was removed.
# The analytics below (glucose logbook, anomalies, categories, calculators, …)
# are unique to this blueprint.
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/glucose/logbook')
@require_auth
def api_glucose_logbook():
    from db.health import get_glucose_logbook
    days = to_int(request.args.get('days', 30), 30, lo=1, hi=3650)
    return jsonify(get_glucose_logbook(days))

@bp.route('/api/vitals/anomalies')
@require_auth
def api_vitals_anomalies():
    days = to_int(request.args.get('days', 60), 60, lo=7, hi=3650)
    return jsonify(get_vitals_anomalies(days))

@bp.route('/api/vitals/categories')
@require_auth
def api_vital_categories():
    days = to_int(request.args.get('days', 90), 90, lo=1, hi=3650)
    return jsonify(get_vital_categories(days))

@bp.route('/api/condition-checkin')
@require_auth
def api_condition_checkin():
    return jsonify(get_condition_checkin())

@bp.route('/api/condition-focus', methods=['POST'])
@require_auth
def api_set_condition_focus():
    focus = set_condition_focus((request.json or {}).get('focus'))
    return jsonify({'success': True, 'focus': focus})

@bp.route('/api/health/calculators')
@require_auth
def api_health_calculators():
    return jsonify(get_health_calculators())

@bp.route('/api/health/hr-zones')
@require_auth
def api_hr_zones():
    return jsonify(get_hr_zones())

@bp.route('/api/today/glance')
@require_auth
def api_today_glance():
    return jsonify(get_today_glance())

@bp.route('/api/week-over-week')
@require_auth
def api_week_over_week():
    """This week vs last across core metrics — only where both weeks have data."""
    from db.week_review import get_week_over_week
    return jsonify(get_week_over_week())

@bp.route('/api/profile/completeness')
@require_auth
def api_profile_completeness():
    return jsonify(get_profile_completeness())

@bp.route('/api/visit-checklist')
@require_auth
def api_visit_checklist():
    return jsonify(get_visit_checklist())

@bp.route('/api/data-trust')
@require_auth
def api_data_trust():
    """How current your record is + honest caveats where a summary rests on thin
    data. Purely descriptive — no advice, no cadence expectations, no verdicts."""
    from db.data_trust import get_data_trust
    return jsonify(get_data_trust())

@bp.route('/api/glossary')
@require_auth
def api_glossary():
    """Plain-language 'what this measures' for the user's own labs/vitals/meds,
    plus the full reference set. Definitional only — never a verdict on a value."""
    from db.glossary import get_glossary
    return jsonify(get_glossary())

@bp.route('/api/weekly-review')
@require_auth
def api_weekly_review():
    """The guided weekly-review payload (composed from existing recaps) + this
    week's saved reflection + past reflections."""
    from db.weekly_review import get_weekly_review
    return jsonify(get_weekly_review())

@bp.route('/api/weekly-review', methods=['POST'])
@require_auth
def api_save_weekly_review():
    from db.weekly_review import save_weekly_review
    d = request.get_json(silent=True) or {}
    return jsonify({'success': True, 'saved': save_weekly_review(d.get('wins'), d.get('focus'))})

@bp.route('/api/today-timeline')
@require_auth
def api_today_timeline():
    """Today's logged events (doses, vitals, food, water, sleep, symptoms) in
    clock order — a single-day, hour-by-hour view."""
    from db.today_timeline import get_today_timeline
    return jsonify(get_today_timeline())

@bp.route('/api/care-circle')
@require_auth
def api_care_circle():
    """A caregiver at-a-glance board — today + week for each member who shares
    their medicines with you. Composes existing consent-gated views; adds no new
    data access."""
    from db.care_circle import get_care_circle
    return jsonify(get_care_circle())

@bp.route('/api/ask')
@require_auth
def api_ask():
    """A private, deterministic Q&A over the user's own data — no LLM, no cloud,
    no fabrication. Walled from a caregiver acting-as (see _ACTING_AS_PRIVATE)."""
    from db.ask import answer_question
    return jsonify(answer_question(request.args.get('q', '')))

@bp.route('/api/year-story')
@require_auth
def api_year_story():
    """An honest 'year in health' recap — consistency + counts + milestones,
    all from real logs. ?days= (30..366, default 365)."""
    from db.year_story import get_year_story
    try:
        days = int(request.args.get('days', 365))
    except (TypeError, ValueError):
        days = 365
    return jsonify(get_year_story(days))

@bp.route('/api/year-story/prompt')
@require_auth
def api_year_story_prompt():
    """Whether to gently offer the year story on the dashboard (year-end or a
    account anniversary, and only if there's a real story)."""
    from db.year_story import year_story_prompt
    return jsonify(year_story_prompt())

# NOTE: /api/emergency (GET/POST) and /api/wellness/today live in
# routes/wellness.py — the duplicate definitions here were dead code (wellness
# registers first) and were removed.

# ══════════════════════════════════════════════════════════════════════════════
# Thoughts (Daily Journal) Routes
# ══════════════════════════════════════════════════════════════════════════════
#
# The GET/POST/PUT/DELETE + list handlers for /api/thoughts live in
# routes/wellness.py (registered first, so it owns them in the URL map). Only the
# week-range endpoint below is unique to this blueprint. Do NOT re-add the CRUD
# handlers here — duplicates would sit dead behind wellness and silently drift
# from it (e.g. the mood-triggers threading).

@bp.route('/api/thoughts/range/week')
@require_auth
def api_thoughts_week():
    return jsonify(get_thoughts_range(7))

# NOTE: /api/todos (GET/POST/PUT/DELETE, /<tid>/toggle, /reminders/due) live in
# routes/wellness.py — the duplicate definitions here were dead code (wellness
# registers first) and were removed.

