"""
db/food.py — Food logging, nutrition summary, custom foods, user profile, TDEE.

All queries are scoped to the authenticated user via current_user_id().
"""
from __future__ import annotations

from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id, to_num, to_int


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

# Categories in food_data.py whose items are drinks. Liquids are ~1g per ml,
# so the logged grams are the fluid volume.
BEVERAGE_CATEGORIES = {'beverages', 'indian beverages'}


def _beverage_ml(food_id: str, quantity_g) -> int:
    """Fluid this food contributes, or 0 if it isn't a drink."""
    try:
        from food_data import FOOD_BY_ID
        f = FOOD_BY_ID.get(food_id or '')
        if f and str(f.get('category', '')).strip().lower() in BEVERAGE_CATEGORIES:
            return to_int(quantity_g, 0, lo=0, hi=10000)
    except Exception:
        pass
    return 0


def log_food(data: dict) -> dict:
    fid = new_id()
    execute("""INSERT INTO food_logs
        (id,food_id,food_name,meal_type,date_key,quantity_g,
         calories,protein,carbs,fat,fiber,sugar,sodium,nutrients,logged_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, data.get('food_id','custom'), data.get('food_name',''),
         data.get('meal_type','lunch'), data.get('date_key', today_iso()),
         to_num(data.get('quantity_g'), 100, lo=0, hi=100000),
         to_num(data.get('calories'), 0, lo=0, hi=100000), to_num(data.get('protein'), 0, lo=0),
         to_num(data.get('carbs'), 0, lo=0), to_num(data.get('fat'), 0, lo=0),
         to_num(data.get('fiber'), 0, lo=0), to_num(data.get('sugar'), 0, lo=0),
         to_num(data.get('sodium'), 0, lo=0), jdump(data.get('nutrients',{})),
         now_iso(), current_user_id()), commit=True)

    # A logged drink is fluid the user already told us about — count it toward
    # hydration instead of making them log the same latte twice. Attributed by
    # name and linked to this food log, so it stays honest (and is removed if
    # the food log is deleted). Never invents water the user didn't log.
    ml = _beverage_ml(data.get('food_id', ''), data.get('quantity_g'))
    if ml >= 30:
        from .wellness import log_hydration
        log_hydration(ml, data.get('food_name') or 'Drink',
                      data.get('date_key', today_iso()), source_id=fid)

    r = execute("SELECT * FROM food_logs WHERE id=?", (fid,), fetchone=True)
    return _fmt_food_log(r)

def _sync_beverage_credit(lid: str, food_id: str, food_name: str,
                          date_key: str, quantity_g) -> None:
    """Keep the hydration credited from a drink equal to the drink.

    The credit is derived data: it has to follow the food log it came from or
    it silently drifts. Correct a 200ml chai down to a 100ml cup and the day
    would otherwise still count 200ml of water — for a drink that no longer
    exists at that size.
    """
    from .wellness import log_hydration
    uid = current_user_id()
    ml  = _beverage_ml(food_id or '', quantity_g)
    existing = execute("SELECT id FROM hydration_logs WHERE source_id=? AND user_id=?",
                       (lid, uid), fetchone=True)
    if ml >= 30:
        if existing:
            execute("""UPDATE hydration_logs SET amount_ml=?, drink_type=?, date_key=?
                       WHERE id=? AND user_id=?""",
                    (to_int(ml, 0, lo=0, hi=10000), food_name or 'Drink', date_key,
                     existing['id'], uid), commit=True)
        else:
            # Wasn't credited before (e.g. edited up from a sip below the
            # threshold) — start crediting it now.
            log_hydration(ml, food_name or 'Drink', date_key, source_id=lid)
    elif existing:
        # Fell below the threshold, or isn't a drink any more: the credit no
        # longer represents anything the user did.
        execute("DELETE FROM hydration_logs WHERE source_id=? AND user_id=?",
                (lid, uid), commit=True)


def update_food_log(lid: str, new_qty) -> dict:
    """Rescale a food log to a corrected portion.

    Lives here, next to log_food, on purpose: this has to mirror it exactly.
    The route used to do the arithmetic itself and scaled only the five macros
    the UI happened to show — so halving a portion halved the calories while
    sugar, sodium and every micronutrient stayed put, permanently over-reporting
    them. For someone tracking sodium because of their blood pressure, a
    downward correction that leaves sodium untouched is the wrong direction to
    fail in. It also never touched the drink's hydration credit.

    Returns the updated log, or None if it isn't the user's / doesn't exist.
    Raises ValueError on a non-positive quantity.
    """
    uid = current_user_id()
    row = execute("SELECT * FROM food_logs WHERE id=? AND user_id=?",
                  (lid, uid), fetchone=True)
    if not row:
        return None

    qty = to_num(new_qty, 0, lo=0, hi=100000)
    if qty <= 0:
        raise ValueError('Quantity must be greater than zero')
    old_qty = to_num(row['quantity_g'], 0, lo=0, hi=100000) or 100
    scale   = qty / old_qty

    # Every per-portion nutrient, including the JSON blob — get_nutrition_summary
    # sums both the columns and the blob, so anything missed here shows up in
    # the day's totals and drives the nutrition advice.
    nutrients = _load_nutrients(row['nutrients'])
    scaled    = {k: round(to_num(v, 0) * scale, 2) for k, v in nutrients.items()}

    execute("""UPDATE food_logs
                  SET quantity_g=?, calories=?, protein=?, carbs=?, fat=?,
                      fiber=?, sugar=?, sodium=?, nutrients=?
                WHERE id=? AND user_id=?""",
            (qty,
             round(to_num(row['calories'], 0) * scale, 1),
             round(to_num(row['protein'],  0) * scale, 1),
             round(to_num(row['carbs'],    0) * scale, 1),
             round(to_num(row['fat'],      0) * scale, 1),
             round(to_num(row['fiber'],    0) * scale, 1),
             round(to_num(row['sugar'],    0) * scale, 1),
             round(to_num(row['sodium'],   0) * scale, 1),
             jdump(scaled), lid, uid), commit=True)

    _sync_beverage_credit(lid, row['food_id'], row['food_name'], row['date_key'], qty)

    r = execute("SELECT * FROM food_logs WHERE id=?", (lid,), fetchone=True)
    return _fmt_food_log(r)


def usual_portions() -> dict:
    """{food_id: grams} — the portion the user habitually eats of each food,
    learned from their own logs. The food DB's serving_g is a generic average;
    this is what *they* actually put on the plate, so the picker can default to
    it instead of making them re-type '2 rotis' every time."""
    rows = execute("""SELECT food_id, quantity_g, COUNT(*) AS n
                      FROM food_logs
                      WHERE user_id=? AND quantity_g > 0
                      GROUP BY food_id, quantity_g
                      ORDER BY food_id, n DESC""",
                   (current_user_id(),), fetchall=True)
    out = {}
    for r in rows:            # rows are grouped by food, most-frequent first
        fid = r['food_id']
        if fid and fid not in out:
            out[fid] = int(round(to_num(r['quantity_g'], 0, lo=0, hi=100000)))
    return out


def get_food_logs(date_key: str) -> list:
    rows = execute(
        "SELECT * FROM food_logs WHERE date_key=? AND user_id=? ORDER BY logged_at",
        (date_key, current_user_id()), fetchall=True)
    return [_fmt_food_log(r) for r in rows]

def delete_food_log(lid: str) -> bool:
    """Delete a user-owned food log. Returns True if a row was actually
    removed, False if nothing matched (missing / another user's) so the
    route can answer an honest 404."""
    uid = current_user_id()
    exists = execute("SELECT id FROM food_logs WHERE id=? AND user_id=?",
                     (lid, uid), fetchone=True)
    if not exists:
        return False
    execute("DELETE FROM food_logs WHERE id=? AND user_id=?", (lid, uid), commit=True)
    # Remove any hydration credited from this drink, so the day's total doesn't
    # keep counting water from a meal the user just deleted.
    execute("DELETE FROM hydration_logs WHERE source_id=? AND user_id=?",
            (lid, uid), commit=True)
    return True

def _load_nutrients(v) -> dict:
    """Always a dict, even for rows written before the double-encode fix.

    The food route used to json.dumps() the nutrients dict before handing it to
    log_food, which jdump()s it again — so the column held a string inside a
    string and one jload() gave back a string. get_nutrition_summary papered
    over it with an isinstance check; every other reader would have broken on
    it. Unwrap once more when we find that shape, so old rows read the same as
    new ones.
    """
    out = jload(v, {}) if v else {}
    if isinstance(out, str):
        out = jload(out, {})
    return out if isinstance(out, dict) else {}


def _fmt_food_log(r) -> dict:
    d = dict(r)
    d['nutrients'] = _load_nutrients(d.get('nutrients'))
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
    uid = current_user_id()
    name = str(data.get('name', '')).strip()
    if not name:
        raise ValueError('Food name is required')
    barcode = (data.get('barcode') or '').strip() or None
    vals = dict(
        name=name[:120], category=data.get('category', 'Custom'),
        emoji=data.get('emoji', '🍽️'), serving_g=to_num(data.get('serving_g'), 100, lo=0, hi=100000),
        calories=to_num(data.get('calories'), 0, lo=0, hi=100000), protein=to_num(data.get('protein'), 0, lo=0),
        carbs=to_num(data.get('carbs'), 0, lo=0), fat=to_num(data.get('fat'), 0, lo=0),
        fiber=to_num(data.get('fiber'), 0, lo=0), sugar=to_num(data.get('sugar'), 0, lo=0),
        sodium=to_num(data.get('sodium'), 0, lo=0), barcode=barcode)

    # Re-scanning a barcode updates the saved entry instead of duplicating it
    existing = get_custom_food_by_barcode(barcode) if barcode else None
    if existing:
        execute("""UPDATE custom_foods SET
                     name=?,category=?,emoji=?,serving_g=?,calories=?,protein=?,
                     carbs=?,fat=?,fiber=?,sugar=?,sodium=?
                   WHERE id=? AND user_id=?""",
                (vals['name'], vals['category'], vals['emoji'], vals['serving_g'],
                 vals['calories'], vals['protein'], vals['carbs'], vals['fat'],
                 vals['fiber'], vals['sugar'], vals['sodium'],
                 existing['id'], uid), commit=True)
        return get_custom_food_by_barcode(barcode)

    fid = new_id()
    execute("""INSERT INTO custom_foods
        (id,name,category,emoji,serving_g,calories,protein,carbs,fat,fiber,
         sugar,sodium,barcode,created_at,user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, vals['name'], vals['category'], vals['emoji'], vals['serving_g'],
         vals['calories'], vals['protein'], vals['carbs'], vals['fat'],
         vals['fiber'], vals['sugar'], vals['sodium'], vals['barcode'],
         now_iso(), uid), commit=True)
    r = execute("SELECT * FROM custom_foods WHERE id=?", (fid,), fetchone=True)
    return dict(r)

def get_custom_food_by_barcode(barcode: str) -> dict | None:
    """A previously scanned+saved food, for instant re-scan lookup."""
    if not barcode:
        return None
    r = execute("SELECT * FROM custom_foods WHERE barcode=? AND user_id=? LIMIT 1",
                (str(barcode), current_user_id()), fetchone=True)
    return dict(r) if r else None

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
