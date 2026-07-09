"""
db/fitness.py — Fitness activities, OAuth tokens, sync history.

All queries are scoped to the authenticated user via current_user_id().
"""
from __future__ import annotations

from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id


def insert_activity(data: dict, check_duplicate=True) -> dict | None:
    """Insert activity; skip if external_id already exists for this user."""
    uid = current_user_id()
    if check_duplicate and data.get('external_id'):
        exists = execute("SELECT id FROM fitness_activities WHERE external_id=? AND user_id=?",
                         (data['external_id'], uid), fetchone=True)
        if exists: return None   # already imported

    aid = new_id()
    execute("""
        INSERT INTO fitness_activities
          (id,type,name,date,duration,distance,calories,heart_rate_avg,
           heart_rate_max,steps,elevation,notes,source,external_id,created_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (aid, data.get('type','running'), data.get('name',''),
          data.get('date', today_iso()), int(data.get('duration',0)),
          float(data.get('distance',0)), int(data.get('calories',0)),
          int(data.get('heart_rate_avg',0)), int(data.get('heart_rate_max',0)),
          int(data.get('steps',0)), float(data.get('elevation',0)),
          data.get('notes',''), data.get('source','manual'),
          data.get('external_id',''), now_iso(), uid), commit=True)
    return get_activity(aid)


def get_activity(aid):
    r = execute("SELECT * FROM fitness_activities WHERE id=? AND user_id=?",
                (aid, current_user_id()), fetchone=True)
    return dict(r) if r else None


def list_activities():
    rows = execute("SELECT * FROM fitness_activities WHERE user_id=? ORDER BY date DESC, created_at DESC",
                   (current_user_id(),), fetchall=True)
    return [dict(r) for r in rows]


def delete_activity(aid):
    execute("DELETE FROM fitness_activities WHERE id=? AND user_id=?",
            (aid, current_user_id()), commit=True)


def fitness_stats():
    import datetime as dt
    today = dt.date.today()
    week_start = (today - dt.timedelta(days=today.weekday())).isoformat()
    month_str = today.strftime('%Y-%m')

    all_acts = list_activities()
    week_acts = [a for a in all_acts if a.get('date','') >= week_start]
    month_acts = [a for a in all_acts if a.get('date','')[:7] == month_str]

    def sf(lst, f): return sum(a.get(f,0) for a in lst)

    # Per-day breakdown Mon–Sun
    days = {}
    for i in range(7):
        d = (today - dt.timedelta(days=today.weekday()-i)).isoformat()
        da = [a for a in all_acts if a.get('date') == d]
        days[d] = {'calories': sf(da,'calories'), 'duration': sf(da,'duration'), 'count': len(da)}

    # Type breakdown
    type_bd = {}
    for a in all_acts[:100]:
        t = a.get('type','other'); type_bd[t] = type_bd.get(t,0) + 1

    # AI suggestions
    suggestions = []
    week_dur = sf(week_acts,'duration')
    week_cal = sf(week_acts,'calories')
    if len(week_acts) == 0:
        suggestions.append({'type':'critical','icon':'⚠️','text':'No workouts logged this week. Start with a 20-minute walk!','priority':0})
    if week_dur < 150:
        suggestions.append({'type':'warning','icon':'🏃','text':f'You\'ve done {week_dur} of the recommended 150 min/week. A 30-min jog today gets you closer!','priority':1})
    if week_cal < 1500:
        suggestions.append({'type':'info','icon':'🔥','text':f'Only {week_cal} kcal burned this week. A HIIT or cycling session adds 400–600 kcal.','priority':2})
    if not any(a.get('type') in ['yoga','stretching','flexibility'] for a in week_acts):
        suggestions.append({'type':'info','icon':'🧘','text':'No flexibility or recovery work this week. 10 min of stretching aids muscle repair.','priority':3})
    if any(a.get('heart_rate_avg',0) > 170 for a in week_acts):
        suggestions.append({'type':'warning','icon':'❤️','text':'High avg heart rate detected this week. Consider a low-intensity recovery session.','priority':3})
    if week_dur > 300:
        suggestions.append({'type':'success','icon':'🌟','text':f'Excellent week! {week_dur} active minutes. Ensure at least one full rest day.','priority':4})
    if sf(week_acts,'distance') > 20:
        suggestions.append({'type':'success','icon':'🏅','text':f'Over {round(sf(week_acts,"distance"),1)} km covered this week — great endurance work!','priority':4})
    suggestions.sort(key=lambda x: x['priority'])

    today_iso = today.isoformat()
    today_acts = [a for a in all_acts if a.get('date') == today_iso]

    return {
        'week': {'activities': len(week_acts), 'calories': sf(week_acts,'calories'),
                 'duration': sf(week_acts,'duration'), 'distance': round(sf(week_acts,'distance'),1)},
        'month': {'activities': len(month_acts), 'calories': sf(month_acts,'calories'),
                  'duration': sf(month_acts,'duration')},
        'today': {'activities': len(today_acts), 'calories': sf(today_acts,'calories'),
                  'duration': sf(today_acts,'duration'), 'distance': round(sf(today_acts,'distance'),1)},
        'total': len(all_acts),
        'weekly_days': days,
        'type_breakdown': type_bd,
        'suggestions': suggestions[:5]
    }


# ── OAuth Tokens ──────────────────────────────────────────────────────────────

def save_token(service, token_data: dict):
    uid = current_user_id()
    existing = execute("SELECT id FROM oauth_tokens WHERE service=? AND user_id=?",
                       (service, uid), fetchone=True)
    if existing:
        execute("""
            UPDATE oauth_tokens SET
              access_token=?, refresh_token=?, token_type=?, expires_at=?,
              scope=?, athlete_id=?, athlete_name=?, last_sync=?
            WHERE service=? AND user_id=?
        """, (token_data.get('access_token',''), token_data.get('refresh_token',''),
              token_data.get('token_type','Bearer'), token_data.get('expires_at',''),
              token_data.get('scope',''), token_data.get('athlete_id',''),
              token_data.get('athlete_name',''), '', service, uid), commit=True)
    else:
        execute("""
            INSERT INTO oauth_tokens
              (id,service,access_token,refresh_token,token_type,expires_at,
               scope,athlete_id,athlete_name,connected_at,last_sync,user_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (new_id(), service, token_data.get('access_token',''),
              token_data.get('refresh_token',''), token_data.get('token_type','Bearer'),
              token_data.get('expires_at',''), token_data.get('scope',''),
              token_data.get('athlete_id',''), token_data.get('athlete_name',''),
              now_iso(), '', uid), commit=True)


def get_token(service) -> dict | None:
    r = execute("SELECT * FROM oauth_tokens WHERE service=? AND user_id=?",
                (service, current_user_id()), fetchone=True)
    return dict(r) if r else None


def list_tokens():
    rows = execute("SELECT service,athlete_name,connected_at,last_sync FROM oauth_tokens WHERE user_id=?",
                   (current_user_id(),), fetchall=True)
    return [dict(r) for r in rows]


def update_last_sync(service):
    execute("UPDATE oauth_tokens SET last_sync=? WHERE service=? AND user_id=?",
            (now_iso(), service, current_user_id()), commit=True)


def delete_token(service):
    execute("DELETE FROM oauth_tokens WHERE service=? AND user_id=?",
            (service, current_user_id()), commit=True)


# ── Sync Log ──────────────────────────────────────────────────────────────────

def log_sync(service, status='success', count=0, message=''):
    execute("""
        INSERT INTO sync_log (id,service,synced_at,status,count,message,user_id)
        VALUES (?,?,?,?,?,?,?)
    """, (new_id(), service, now_iso(), status, count, message, current_user_id()),
        commit=True)


def get_sync_history(service=None, limit=20):
    uid = current_user_id()
    if service:
        rows = execute(
            "SELECT * FROM sync_log WHERE service=? AND user_id=? ORDER BY synced_at DESC LIMIT ?",
            (service, uid, limit), fetchall=True)
    else:
        rows = execute("SELECT * FROM sync_log WHERE user_id=? ORDER BY synced_at DESC LIMIT ?",
                       (uid, limit), fetchall=True)
    return [dict(r) for r in rows]
