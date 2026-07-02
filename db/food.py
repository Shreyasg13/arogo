"""
db/food.py — Food logging, nutrition summary, custom foods, user profile, TDEE.

All queries are scoped to the authenticated user via current_user_id().
"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id


def get_profile() -> dict:
    uid = current_user_id()
    r = execute("SELECT * FROM user_profile WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if r: return dict(r)
    # Lazily create an empty profile row for this user (register normally
    # does this, but legacy accounts or direct db calls may not have one)
    execute("""INSERT INTO user_profile
               (id, name, weight_kg, height_cm, age, gender,
                activity_level, goal, updated_at, user_id)
               VALUES (?, '', NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)""",
            (new_id(), now_iso(), uid), commit=True)
    r = execute("SELECT * FROM user_profile WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    return dict(r) if r else {}

def update_profile(data: dict) -> dict:
    p = get_profile()
    existing_target = p.get('target_weight_kg')
    new_target = data.get('target_weight_kg', existing_target)
    if new_target is not None:
        try:
            new_target = float(new_target)
        except (TypeError, ValueError):
            new_target = None
    # Only coerce to float/int if the value is actually provided
    def _float(key, fallback):
        v = data.get(key, fallback)
        if v is None or v == '': return None
        try: return float(v)
        except: return fallback
    def _int(key, fallback):
        v = data.get(key, fallback)
        if v is None or v == '': return None
        try: return int(v)
        except: return fallback

    execute("""UPDATE user_profile SET
        name=?, weight_kg=?, height_cm=?, age=?, gender=?,
        activity_level=?, goal=?, target_weight_kg=?, timezone=?, updated_at=?
        WHERE id=? AND user_id=?""",
        (data.get('name', p.get('name')) or '',
         _float('weight_kg', p.get('weight_kg')),
         _float('height_cm', p.get('height_cm')),
         _int('age', p.get('age')),
         data.get('gender', p.get('gender')),
         data.get('activity_level', p.get('activity_level')),
         data.get('goal', p.get('goal')),
         new_target,
         data.get('timezone', p.get('timezone')),
         now_iso(), p['id'], current_user_id()), commit=True)
    return get_profile()

def calc_tdee(profile: dict) -> dict:
    """Harris-Benedict BMR → TDEE with goal adjustment.
    Returns empty dict if mandatory fields (weight, height, age, gender) are missing."""
    w   = profile.get('weight_kg')
    h   = profile.get('height_cm')
    a   = profile.get('age')
    g   = profile.get('gender')
    act = profile.get('activity_level', 'moderate')
    goal = profile.get('goal', 'maintain')

    # Can't calculate without these four
    if any(v is None for v in (w, h, a, g)):
        return {
            'bmr': None, 'tdee': None, 'target_calories': None,
            'protein_g': None, 'carbs_g': None, 'fat_g': None,
            'fiber_g': 30, 'water_ml': None,
        }

    w, h, a = float(w), float(h), int(a)

    # BMR
    if g == 'male':
        bmr = 88.362 + (13.397 * w) + (4.799 * h) - (5.677 * a)
    else:
        bmr = 447.593 + (9.247 * w) + (3.098 * h) - (4.330 * a)

    act_mult = {'sedentary':1.2,'light':1.375,'moderate':1.55,'active':1.725,'very_active':1.9}
    tdee = bmr * act_mult.get(act, 1.55)

    goal_adj = {'lose_fast':-500,'lose':-250,'maintain':0,'gain':250,'gain_fast':500}
    target_cal = tdee + goal_adj.get(goal, 0)

    # Macro targets (g)
    protein_g  = round(w * (1.6 if goal in ('gain','gain_fast') else 1.2))
    fat_g      = round(target_cal * 0.28 / 9)
    carbs_g    = round((target_cal - protein_g*4 - fat_g*9) / 4)

    return {
        'bmr': round(bmr),
        'tdee': round(tdee),
        'target_calories': round(target_cal),
        'protein_g': protein_g,
        'carbs_g': max(carbs_g, 50),
        'fat_g': fat_g,
        'fiber_g': 30,
        'water_ml': round(w * 35)
    }

# ── Food Logs ─────────────────────────────────────────────────────────────────

def log_food(data: dict) -> dict:
    fid = new_id()
    execute("""INSERT INTO food_logs
        (id,food_id,food_name,meal_type,date_key,quantity_g,
         calories,protein,carbs,fat,fiber,sugar,sodium,nutrients,logged_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, data.get('food_id','custom'), data.get('food_name',''),
         data.get('meal_type','lunch'), data.get('date_key', today_iso()),
         float(data.get('quantity_g',100)),
         float(data.get('calories',0)), float(data.get('protein',0)),
         float(data.get('carbs',0)), float(data.get('fat',0)),
         float(data.get('fiber',0)), float(data.get('sugar',0)),
         float(data.get('sodium',0)), jdump(data.get('nutrients',{})),
         now_iso(), current_user_id()), commit=True)
    r = execute("SELECT * FROM food_logs WHERE id=?", (fid,), fetchone=True)
    return _fmt_food_log(r)

def get_food_logs(date_key: str) -> list:
    rows = execute(
        "SELECT * FROM food_logs WHERE date_key=? AND user_id=? ORDER BY logged_at",
        (date_key, current_user_id()), fetchall=True)
    return [_fmt_food_log(r) for r in rows]

def delete_food_log(lid: str):
    execute("DELETE FROM food_logs WHERE id=? AND user_id=?",
            (lid, current_user_id()), commit=True)

def _fmt_food_log(r) -> dict:
    d = dict(r)
    d['nutrients'] = jload(d.get('nutrients','{}'), {})
    return d

def get_nutrition_summary(date_key: str) -> dict:
    logs = get_food_logs(date_key)
    totals = {'calories':0,'protein':0,'carbs':0,'fat':0,'fiber':0,'sugar':0,'sodium':0,
              'vit_a':0,'vit_c':0,'vit_d':0,'vit_b12':0,'iron':0,'calcium':0,'magnesium':0}
    by_meal = {}
    for log in logs:
        for k in totals:
            n = log.get('nutrients', {})
            if isinstance(n, str):
                n = jload(n, {})
            totals[k] += log.get(k, 0) or n.get(k, 0)
        mt = log.get('meal_type','other')
        if mt not in by_meal:
            by_meal[mt] = {'calories':0,'protein':0,'carbs':0,'fat':0,'items':[]}
        by_meal[mt]['calories'] += log.get('calories',0)
        by_meal[mt]['protein']  += log.get('protein',0)
        by_meal[mt]['carbs']    += log.get('carbs',0)
        by_meal[mt]['fat']      += log.get('fat',0)
        by_meal[mt]['items'].append(log)
    return {'totals': {k: round(v, 1) for k,v in totals.items()},
            'by_meal': by_meal, 'log_count': len(logs)}

def get_weekly_nutrition(days: int = 7) -> list:
    import datetime as dt
    result = []
    for i in range(days - 1, -1, -1):
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        summary = get_nutrition_summary(d)
        result.append({'date': d, **summary['totals']})
    return result

def save_custom_food(data: dict) -> dict:
    fid = new_id()
    execute("""INSERT INTO custom_foods
        (id,name,category,emoji,serving_g,calories,protein,carbs,fat,fiber,created_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, data['name'], data.get('category','Custom'), data.get('emoji','🍽️'),
         float(data.get('serving_g',100)), float(data['calories']),
         float(data.get('protein',0)), float(data.get('carbs',0)),
         float(data.get('fat',0)), float(data.get('fiber',0)), now_iso(),
         current_user_id()), commit=True)
    r = execute("SELECT * FROM custom_foods WHERE id=?", (fid,), fetchone=True)
    return dict(r)

def list_custom_foods() -> list:
    rows = execute("SELECT * FROM custom_foods WHERE user_id=? ORDER BY name",
                   (current_user_id(),), fetchall=True)
    return [dict(r) for r in rows]


# ── User timezone ─────────────────────────────────────────────────────────────

MAX_THOUGHTS_PER_DAY = 10

def get_user_timezone() -> str:
    """Return the user's stored timezone, or None."""
    p = get_profile()
    return p.get('timezone') if p else None
