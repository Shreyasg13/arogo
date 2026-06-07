"""
db/insights.py — Notification log, weekly report generator, global search, goal progress.

"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id

from .medicines import get_low_stock_medicines
from .wellness  import get_thoughts_range
from .fitness   import fitness_stats
from .food      import get_profile, calc_tdee
from .health    import get_habit_stats

def add_notification(ntype: str, title: str, body: str = '', source_id: str = None) -> dict:
    nid = new_id()
    execute("INSERT INTO notification_log (id,type,title,body,source_id,read,created_at) VALUES (?,?,?,?,?,0,?)",
            (nid, ntype, title, body, source_id, now_iso()), commit=True)
    return dict(execute("SELECT * FROM notification_log WHERE id=?", (nid,), fetchone=True))

def get_notifications(limit: int = 50, unread_only: bool = False) -> list:
    if unread_only:
        rows = execute("SELECT * FROM notification_log WHERE read=0 ORDER BY created_at DESC LIMIT ?",
                       (limit,), fetchall=True)
    else:
        rows = execute("SELECT * FROM notification_log ORDER BY created_at DESC LIMIT ?",
                       (limit,), fetchall=True)
    return [dict(r) for r in rows]

def mark_notification_read(nid: str):
    execute("UPDATE notification_log SET read=1 WHERE id=?", (nid,), commit=True)

def mark_all_notifications_read():
    execute("UPDATE notification_log SET read=1", commit=True)

def unread_notification_count() -> int:
    r = execute("SELECT COUNT(*) as n FROM notification_log WHERE read=0", fetchone=True)
    return r['n'] if r else 0

# ── Weekly health report ──────────────────────────────────────────────────────

def generate_weekly_report() -> dict:
    import datetime as dt
    today = dt.date.today()
    week_start = (today - dt.timedelta(days=6)).isoformat()
    today_iso_v = today.isoformat()

    # Sleep
    sleep_rows = execute("SELECT duration_h,quality FROM sleep_logs WHERE date_key >= ? AND date_key <= ?",
                         (week_start, today_iso_v), fetchall=True)
    avg_sleep = round(sum(r['duration_h'] for r in sleep_rows) / len(sleep_rows), 1) if sleep_rows else None
    avg_sleep_q = round(sum(r['quality'] for r in sleep_rows) / len(sleep_rows), 1) if sleep_rows else None

    # Workouts
    acts = execute("SELECT * FROM fitness_activities WHERE date >= ? AND date <= ?",
                   (week_start, today_iso_v), fetchall=True)
    workout_days = len(set(r['date'] for r in acts))
    cal_burned   = sum(r['calories'] or 0 for r in acts)

    # Calories eaten
    food = execute("SELECT SUM(calories) as total FROM food_logs WHERE date_key >= ? AND date_key <= ?",
                   (week_start, today_iso_v), fetchone=True)
    cal_eaten = round(food['total'] or 0, 0)

    # Profile for target
    profile = get_profile()
    targets = calc_tdee(profile)
    target_cal_week = targets['target_calories'] * 7
    cal_adherence = round(cal_eaten / target_cal_week * 100, 1) if target_cal_week else None

    # Habits
    habit_stats = get_habit_stats()
    total_habits = len(habit_stats['habits'])
    habit_done_count = sum(len(h['done_dates']) for h in habit_stats['habits'])
    habit_possible = total_habits * 7
    habit_pct = round(habit_done_count / habit_possible * 100, 1) if habit_possible else None

    # Top symptoms
    sym_rows = execute("""SELECT name, COUNT(*) as cnt FROM symptoms
                          WHERE date_key >= ? AND date_key <= ?
                          GROUP BY name ORDER BY cnt DESC LIMIT 5""",
                       (week_start, today_iso_v), fetchall=True)
    top_symptoms = [{'name': r['name'], 'count': r['cnt']} for r in sym_rows]

    # Body metrics
    bm = execute("SELECT weight_kg,bmi FROM body_metrics WHERE date_key >= ? ORDER BY date_key DESC LIMIT 1",
                 (week_start,), fetchone=True)

    # Hydration avg
    hyd = execute("""SELECT AVG(daily_total) as avg FROM
                     (SELECT date_key, SUM(amount_ml) as daily_total FROM hydration_logs
                      WHERE date_key >= ? AND date_key <= ? GROUP BY date_key)""",
                  (week_start, today_iso_v), fetchone=True)
    avg_hydration = round(hyd['avg'] or 0) if hyd else 0

    # Vitals latest
    vitals_latest = {}
    for vtype in ['blood_pressure','blood_sugar','heart_rate']:
        r = execute("SELECT value1,value2,unit FROM vitals WHERE type=? ORDER BY logged_at DESC LIMIT 1",
                    (vtype,), fetchone=True)
        if r: vitals_latest[vtype] = dict(r)

    return {
        'period': {'start': week_start, 'end': today_iso_v},
        'sleep':   {'avg_hours': avg_sleep, 'avg_quality': avg_sleep_q, 'nights': len(sleep_rows)},
        'fitness': {'workout_days': workout_days, 'calories_burned': cal_burned, 'activities': len(acts)},
        'nutrition':{'calories_eaten': cal_eaten, 'target': targets['target_calories'],
                     'weekly_target': target_cal_week, 'adherence_pct': cal_adherence,
                     'avg_hydration_ml': avg_hydration},
        'habits':  {'total': total_habits, 'completion_pct': habit_pct, 'done_count': habit_done_count},
        'symptoms': top_symptoms,
        'body':    {'weight_kg': bm['weight_kg'] if bm else None, 'bmi': bm['bmi'] if bm else None},
        'vitals':  vitals_latest,
        'profile': {'name': profile.get('name','User'), 'goal': profile.get('goal','maintain')},
    }

# ── Global search ─────────────────────────────────────────────────────────────

def _parse_date_query(query: str):
    """
    Parse natural language date references and return (clean_query, date_filter_sql, date_params).
    Handles: 'last week', 'last monday', 'last tuesday' etc., 'yesterday', 'today',
             'this month', 'last month', specific dates like 'june 3'.
    Returns (stripped_query, date_key_col_expr, [params]) or (query, None, []).
    """
    import datetime as dt, re
    today = dt.date.today()
    q = query.lower().strip()
    date_range = None

    # today / yesterday
    if re.search(r'\btoday\b', q):
        date_range = (today.isoformat(), today.isoformat())
        q = re.sub(r'\btoday\b', '', q).strip()
    elif re.search(r'\byesterday\b', q):
        d = today - dt.timedelta(days=1)
        date_range = (d.isoformat(), d.isoformat())
        q = re.sub(r'\byesterday\b', '', q).strip()

    # last week
    elif re.search(r'\blast week\b', q):
        start = today - dt.timedelta(days=today.weekday()+7)
        end   = start + dt.timedelta(days=6)
        date_range = (start.isoformat(), end.isoformat())
        q = re.sub(r'\blast week\b', '', q).strip()

    # this week
    elif re.search(r'\bthis week\b', q):
        start = today - dt.timedelta(days=today.weekday())
        date_range = (start.isoformat(), today.isoformat())
        q = re.sub(r'\bthis week\b', '', q).strip()

    # this month
    elif re.search(r'\bthis month\b', q):
        start = today.replace(day=1)
        date_range = (start.isoformat(), today.isoformat())
        q = re.sub(r'\bthis month\b', '', q).strip()

    # last month
    elif re.search(r'\blast month\b', q):
        first_this = today.replace(day=1)
        last_prev  = first_this - dt.timedelta(days=1)
        start = last_prev.replace(day=1)
        date_range = (start.isoformat(), last_prev.isoformat())
        q = re.sub(r'\blast month\b', '', q).strip()

    # last <weekday>  e.g. "last tuesday"
    else:
        days_map = {'monday':0,'tuesday':1,'wednesday':2,'thursday':3,
                    'friday':4,'saturday':5,'sunday':6}
        m = re.search(r'\blast (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', q)
        if m:
            target_wd = days_map[m.group(1)]
            delta = (today.weekday() - target_wd) % 7 or 7
            d = today - dt.timedelta(days=delta)
            date_range = (d.isoformat(), d.isoformat())
            q = re.sub(r'\blast ' + m.group(1) + r'\b', '', q).strip()

        # on <weekday>  e.g. "on monday"
        if not date_range:
            m = re.search(r'\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', q)
            if m:
                target_wd = days_map[m.group(1)]
                delta = (today.weekday() - target_wd) % 7
                d = today - dt.timedelta(days=delta)
                date_range = (d.isoformat(), d.isoformat())
                q = re.sub(r'\bon ' + m.group(1) + r'\b', '', q).strip()

    return q.strip() or None, date_range


def global_search(query: str, limit: int = 40) -> dict:
    clean_q, date_range = _parse_date_query(query)
    # If entire query was a date phrase and nothing else, search everything in that range
    text_q = f'%{clean_q.lower()}%' if clean_q else '%'
    results = {'query': query, 'total': 0, 'sections': [], 'date_range': date_range}

    def date_filter(col):
        if not date_range: return '', []
        return f' AND {col} BETWEEN ? AND ?', list(date_range)

    # ── Food logs ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT food_name,date_key,calories,meal_type,quantity_g FROM food_logs"
        f" WHERE (LOWER(food_name) LIKE ? OR LOWER(meal_type) LIKE ?){df}"
        f" ORDER BY date_key DESC LIMIT {limit//4}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'food','label':'Food Logs','icon':'🍽️',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Thoughts ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT id,content,mood,date_key,created_at FROM thoughts"
        f" WHERE LOWER(content) LIKE ?{df}"
        f" ORDER BY created_at DESC LIMIT {limit//5}",
        [text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'thought','label':'Thoughts','icon':'💭',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Symptoms ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT id,name,severity,date_key,time_of_day,notes FROM symptoms"
        f" WHERE (LOWER(name) LIKE ? OR LOWER(notes) LIKE ?){df}"
        f" ORDER BY date_key DESC LIMIT {limit//5}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'symptom','label':'Symptoms','icon':'🩺',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Todos ──
    df, dp = date_filter('created_at')
    rows = execute(
        f"SELECT id,title,notes,status,priority,due_date,created_at FROM todos"
        f" WHERE (LOWER(title) LIKE ? OR LOWER(notes) LIKE ?){df}"
        f" ORDER BY created_at DESC LIMIT {limit//5}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'todo','label':'Tasks','icon':'✅',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Activities ──
    df, dp = date_filter('date')
    rows = execute(
        f"SELECT id,name,type,date,duration,calories,distance FROM fitness_activities"
        f" WHERE (LOWER(name) LIKE ? OR LOWER(type) LIKE ?){df}"
        f" ORDER BY date DESC LIMIT {limit//5}",
        [text_q, text_q] + dp, fetchall=True)
    if rows:
        results['sections'].append({'type':'activity','label':'Workouts','icon':'🏃',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Medicines ──
    if clean_q:
        rows = execute(
            "SELECT id,name,dosage,unit,frequency FROM medicines"
            " WHERE LOWER(name) LIKE ? AND active=1 ORDER BY name LIMIT 5",
            (text_q,), fetchall=True)
        if rows:
            results['sections'].append({'type':'medicine','label':'Medicines','icon':'💊',
                                        'items':[dict(r) for r in rows]})
            results['total'] += len(rows)

    # ── Reports ──
    df, dp = date_filter('report_date')
    rows = execute(
        f"SELECT id,filename,patient_name,doctor,severity,report_date FROM reports"
        f" WHERE (LOWER(filename) LIKE ? OR LOWER(patient_name) LIKE ? OR LOWER(doctor) LIKE ?){df}"
        f" ORDER BY report_date DESC LIMIT 5",
        [text_q, text_q, text_q] + dp, fetchall=True)
    if rows:
        items = [{'id':r['id'],'filename':r['filename'],'patient':r['patient_name'],
                  'doctor':r['doctor'],'severity':r['severity'],'date':r['report_date']} for r in rows]
        results['sections'].append({'type':'report','label':'Medical Reports','icon':'📋','items':items})
        results['total'] += len(rows)

    return results

# ── Goal progress data ────────────────────────────────────────────────────────

def get_goal_progress() -> dict:
    import datetime as dt
    today = dt.date.today()
    month_start = today.replace(day=1).isoformat()
    week_start  = (today - dt.timedelta(days=6)).isoformat()
    days30_start = (today - dt.timedelta(days=29)).isoformat()

    profile = get_profile()
    targets = calc_tdee(profile)

    # Weight trend (all entries, up to 60 days for chart)
    bm_rows = execute(
        "SELECT date_key,weight_kg,bmi FROM body_metrics WHERE weight_kg IS NOT NULL ORDER BY date_key",
        fetchall=True)
    weight_trend = [{'date':r['date_key'],'weight':r['weight_kg'],'bmi':r['bmi']} for r in bm_rows[-60:]]

    # Workout frequency this month + daily workout presence for chart
    acts_month = execute("SELECT date FROM fitness_activities WHERE date >= ?", (month_start,), fetchall=True)
    workout_days_month = len(set(r['date'] for r in acts_month))
    days_in_month = today.day

    # 30-day daily workout map for mini bar chart
    acts_30 = execute("SELECT date, SUM(calories) as cal FROM fitness_activities WHERE date >= ? GROUP BY date",
                      (days30_start,), fetchall=True)
    workout_map = {r['date']: r['cal'] for r in acts_30}
    daily_workouts = []
    for i in range(29, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily_workouts.append({'date': d, 'cal': workout_map.get(d, 0)})

    # Habit completion this month + per-habit breakdown
    habit_stats = get_habit_stats(30)
    total_habits = len(habit_stats['habits'])
    habit_done = sum(len(h['done_dates']) for h in habit_stats['habits'])
    habit_possible = total_habits * days_in_month
    habit_pct = round(habit_done / habit_possible * 100, 1) if habit_possible else 0
    # Per-habit detail
    habit_detail = []
    for h in habit_stats['habits'][:6]:
        done_this_month = sum(1 for d in h['done_dates'] if d >= month_start)
        pct = round(done_this_month / days_in_month * 100)
        habit_detail.append({'name': h['name'], 'emoji': h['emoji'], 'color': h['color'],
                              'streak': h['streak'], 'pct': pct, 'done': done_this_month})

    # Sleep — 30 days of data
    sleep_rows = execute(
        "SELECT date_key,duration_h,quality FROM sleep_logs WHERE date_key >= ? ORDER BY date_key",
        (days30_start,), fetchall=True)
    sleep_list = [{'date':r['date_key'],'h':r['duration_h'],'q':r['quality']} for r in sleep_rows]
    sleep_7 = [r for r in sleep_list if r['date'] >= week_start]
    avg_sleep_7 = round(sum(r['h'] for r in sleep_7)/len(sleep_7),1) if sleep_7 else None
    avg_sleep_30 = round(sum(r['h'] for r in sleep_list)/len(sleep_list),1) if sleep_list else None

    # Calorie adherence — 30 days
    food_rows = execute(
        "SELECT date_key, SUM(calories) as total FROM food_logs WHERE date_key >= ? GROUP BY date_key",
        (days30_start,), fetchall=True)
    food_map = {r['date_key']: round(r['total'] or 0) for r in food_rows}
    daily_cals = []
    for i in range(29, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily_cals.append({'date': d, 'cal': food_map.get(d, 0)})
    cal_this_week = sum(food_map.get((today - dt.timedelta(days=i)).isoformat(), 0) for i in range(7))
    cal_target_week = targets['target_calories'] * 7
    cal_adherence = round(cal_this_week / cal_target_week * 100, 1) if cal_target_week else 0

    return {
        'profile': profile, 'targets': targets,
        'weight_trend': weight_trend,
        'workouts': {
            'this_month': workout_days_month, 'days_elapsed': days_in_month,
            'frequency_pct': round(workout_days_month/days_in_month*100),
            'daily': daily_workouts
        },
        'habits': {
            'total': total_habits, 'completion_pct': habit_pct,
            'done_count': habit_done, 'detail': habit_detail
        },
        'sleep': {
            'avg_7': avg_sleep_7, 'avg_30': avg_sleep_30,
            'target_hours': 7.5, 'logged_30': len(sleep_list),
            'daily': sleep_list
        },
        'nutrition': {
            'cal_this_week': cal_this_week, 'cal_target': cal_target_week,
            'adherence_pct': cal_adherence, 'daily': daily_cals,
            'target_daily': targets['target_calories']
        },
        'refill_alerts': get_low_stock_medicines(),
    }
