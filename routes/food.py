"""routes/food.py — Food logging, nutrition DB, custom foods, profile."""
from db.food import get_user_timezone
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from auth import require_auth
import os, json as json_mod
from db import *
from config import Config

try:
    from food_data import search_food, get_food, CATEGORIES, FOOD_DB, FOOD_BY_ID
except ImportError as _e:
    import sys, os
    # food_data.py may have a stale relative import — load it directly
    import importlib.util as _ilu
    _path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'food_data.py')
    _spec = _ilu.spec_from_file_location('food_data', _path)
    _mod  = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    search_food = _mod.search_food
    get_food    = _mod.get_food
    CATEGORIES  = _mod.CATEGORIES
    FOOD_DB     = _mod.FOOD_DB
    FOOD_BY_ID  = _mod.FOOD_BY_ID

try:
    from food_nlp import parse_food_phrase
except ImportError:
    import importlib.util as _ilu2
    _p2 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'food_nlp.py')
    _s2 = _ilu2.spec_from_file_location('food_nlp', _p2)
    _m2 = _ilu2.module_from_spec(_s2); _s2.loader.exec_module(_m2)
    parse_food_phrase = _m2.parse_food_phrase

bp = Blueprint("food", __name__)


# ── Apple Health (no OAuth — file upload based) ───────────────────────────────
# See /api/fitness/apple/import above

# ══════════════════════════════════════════════════════════════════════════════
# Food Tracker Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/food/db')
@require_auth
def food_database():
    query  = request.args.get('q', '')
    cat    = request.args.get('category', '')
    limit  = to_int(request.args.get('limit', 80), 80, lo=1, hi=500)
    custom = list_custom_foods()

    # Diet preference: an explicit ?diet= override wins, else the saved profile
    # preference. It restricts suggestions so a vegetarian never sees chicken.
    diet = request.args.get('diet')
    if diet is None:
        diet = (get_profile() or {}).get('diet_pref')

    # Use the fixed search_food with query, category, and diet filter
    results = search_food(query=query, category=cat, limit=limit, diet=diet)
    # `source` is provenance metadata for the DB only — never expose it to the
    # client. Strip it into copies so the shared FOOD_DB dicts stay intact.
    results = [{k: v for k, v in f.items() if k != 'source'} for f in results]

    # Tag and filter custom foods (kept regardless of diet — the user made them)
    custom_results = []
    for c in custom:
        if query and query.lower() not in c['name'].lower():
            continue
        c['is_custom'] = True
        c.setdefault('emoji', '⭐')
        c.setdefault('category', 'My Foods')
        custom_results.append(c)

    return jsonify({
        'foods':      results,
        'custom':     custom_results,
        'categories': CATEGORIES,
        'diet_pref':  diet or None,   # so the picker can show the active filter
        # What this user actually puts on the plate, per food — so the portion
        # picker can default to their serving instead of a generic average.
        'usual_portions': usual_portions(),
    })

@bp.route('/api/food/log', methods=['POST'])
@require_auth
def add_food_log():
    data = request.json or {}
    if 'date_key' in data and not valid_date(data.get('date_key')):
        return jsonify({'success': False, 'error': 'Invalid date'}), 400
    qty  = to_num(data.get('quantity_g', 100), 100, lo=0, hi=100000)

    # JS always sends pre-calculated macros. Fall back to DB lookup if missing.
    if data.get('calories') is not None:
        # Use the macros the JS already calculated (correct for any serving size)
        food_item = get_food(data.get('food_id', ''))
        nutrients = {}
        if food_item:
            scale = qty / 100.0
            nutrients = {
                'vit_a':   round(food_item.get('vit_a',   0) * scale, 1),
                'vit_c':   round(food_item.get('vit_c',   0) * scale, 1),
                'vit_d':   round(food_item.get('vit_d',   0) * scale, 1),
                'vit_b12': round(food_item.get('vit_b12', 0) * scale, 1),
                'iron':    round(food_item.get('iron',    0) * scale, 1),
                'calcium': round(food_item.get('calcium', 0) * scale, 1),
            }
        entry = {
            'food_id':   data.get('food_id', 'custom'),
            'food_name': data.get('food_name', 'Food'),
            'meal_type': data.get('meal_type', 'lunch'),
            'date_key':  data.get('date_key', today_iso(get_user_timezone())),
            'quantity_g': qty,
            'calories':  to_num(data.get('calories', 0), 0, lo=0, hi=100000),
            'protein':   to_num(data.get('protein',  0), 0, lo=0),
            'carbs':     to_num(data.get('carbs',    0), 0, lo=0),
            'fat':       to_num(data.get('fat',      0), 0, lo=0),
            'fiber':     to_num(data.get('fiber',    0), 0, lo=0),
            'sugar':     to_num(data.get('sugar',    0), 0, lo=0),
            'sodium':    to_num(data.get('sodium',   0), 0, lo=0),
            # A dict: log_food jdump()s it. Passing a JSON string here
            # double-encoded it into a string-inside-a-string.
            'nutrients': nutrients,
        }
    else:
        # Legacy: look up from FOOD_BY_ID by food_id
        food_item = get_food(data.get('food_id', ''))
        if not food_item:
            return jsonify({'success': False, 'error': 'Food not found'}), 404
        scale = qty / 100.0
        entry = {
            'food_id':   food_item['id'],
            'food_name': food_item['name'],
            'meal_type': data.get('meal_type', 'lunch'),
            'date_key':  data.get('date_key', today_iso(get_user_timezone())),
            'quantity_g': qty,
            'calories':  round(food_item.get('calories', food_item.get('cal', 0)) * scale, 1),
            'protein':   round(food_item.get('protein', 0) * scale, 1),
            'carbs':     round(food_item.get('carbs',   0) * scale, 1),
            'fat':       round(food_item.get('fat',     0) * scale, 1),
            'fiber':     round(food_item.get('fiber',   0) * scale, 1),
            'sugar':     round(food_item.get('sugar',   0) * scale, 1),
            'sodium':    round(food_item.get('sodium',  0) * scale, 1),
            'nutrients': ({
                'vit_a':    round(food_item.get('vit_a',    0) * scale, 1),
                'vit_c':    round(food_item.get('vit_c',    0) * scale, 1),
                'vit_d':    round(food_item.get('vit_d',    0) * scale, 1),
                'vit_b12':  round(food_item.get('vit_b12',  0) * scale, 1),
                'vit_b6':   round(food_item.get('vit_b6',   0) * scale, 1),
                'folate':   round(food_item.get('folate',   0) * scale, 1),
                'iron':     round(food_item.get('iron',     0) * scale, 1),
                'calcium':  round(food_item.get('calcium',  0) * scale, 1),
                'magnesium':round(food_item.get('magnesium',0) * scale, 1),
                'zinc':     round(food_item.get('zinc',     0) * scale, 1),
            }),
        }

    result = log_food(entry)
    return jsonify({'success': True, 'log': result})


@bp.route('/api/food/parse', methods=['POST'])
@require_auth
def parse_food():
    """Turn a natural-language phrase into a food-log PREVIEW (never logs).

    The client shows the preview and only POSTs to /api/food/log on confirm, so
    a wrong match is always seen and cancellable — never written silently.
    """
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'items': [], 'unmatched': [], 'meal': 'snack', 'meal_explicit': False})
    hour = data.get('hour')
    try:
        hour = int(hour) if hour is not None else None
        if hour is not None and not (0 <= hour <= 23):
            hour = None
    except (TypeError, ValueError):
        hour = None
    return jsonify(parse_food_phrase(text, now_hour=hour))


@bp.route('/api/food/log/<date_key>')
@require_auth
def get_food_log(date_key):
    summary = get_nutrition_summary(date_key)
    profile = get_profile()
    targets = calc_tdee(profile)
    suggestions = generate_nutrition_suggestions(summary['totals'], targets, profile)
    return jsonify({
        'date': date_key,
        'summary': summary,
        'targets': targets,
        'profile': profile,
        'suggestions': suggestions
    })


@bp.route('/api/food/log/<lid>', methods=['PATCH'])
@require_auth
def api_update_food_log(lid):
    d = request.json or {}
    try:
        log = update_food_log(lid, d.get('quantity_g', 0))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if not log:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'success': True, 'log': log})

@bp.route('/api/food/log/<lid>', methods=['DELETE'])
@require_auth
def del_food_log(lid):
    if not delete_food_log(lid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True})

@bp.route('/api/food/weekly')
@require_auth
def weekly_nutrition():
    return jsonify(get_weekly_nutrition(7))

@bp.route('/api/food/profile', methods=['GET'])
@require_auth
def get_user_profile():
    p = get_profile()
    t = calc_tdee(p)
    return jsonify({'profile': p, 'targets': t})

@bp.route('/api/food/profile', methods=['POST'])
@require_auth
def save_profile():
    data = request.json or {}
    p = update_profile(data)
    t = calc_tdee(p)
    return jsonify({'success': True, 'profile': p, 'targets': t})


@bp.route('/api/food/recent-meals')
@require_auth
def api_recent_meals():
    """
    Return recent meal combos from the last 14 days.
    Groups items by (date, meal_type) into combos.
    Returns ranked by frequency — most repeated combos first.
    Also returns yesterday's full log for the "copy yesterday" shortcut.
    """
    import datetime as dt
    from collections import defaultdict
    from db.core import execute

    today     = dt.date.today()
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    start     = (today - dt.timedelta(days=14)).isoformat()

    from db.core import current_user_id
    rows = execute(
        """SELECT id, food_id, food_name, meal_type, date_key,
                  quantity_g, calories, protein, carbs, fat, fiber
           FROM food_logs
           WHERE date_key >= ? AND date_key < ? AND user_id=?
           ORDER BY date_key DESC, logged_at ASC""",
        (start, today.isoformat(), current_user_id()), fetchall=True)

    # Group by (date_key, meal_type)
    combos_raw = defaultdict(list)
    for r in rows:
        key = (r['date_key'], r['meal_type'])
        combos_raw[key].append({
            'food_id':   r['food_id'],
            'food_name': r['food_name'],
            'meal_type': r['meal_type'],
            'quantity_g':r['quantity_g'],
            'calories':  round(r['calories'] or 0, 1),
            'protein':   round(r['protein']  or 0, 1),
            'carbs':     round(r['carbs']    or 0, 1),
            'fat':       round(r['fat']      or 0, 1),
            'fiber':     round(r['fiber']    or 0, 1),
        })

    # Build unique combos — key by sorted food_name list so duplicates merge
    seen_signatures = {}
    combos_list = []
    for (date_key, meal_type), items in sorted(combos_raw.items(), reverse=True):
        sig = meal_type + '|' + '|'.join(
            sorted(f'{i["food_name"]}:{i["quantity_g"]}' for i in items)
        )
        if sig in seen_signatures:
            seen_signatures[sig]['count'] += 1
        else:
            total_cal  = sum(i['calories'] for i in items)
            total_prot = round(sum(i['protein']  for i in items), 1)
            total_carb = round(sum(i['carbs']    for i in items), 1)
            total_fat  = round(sum(i['fat']      for i in items), 1)
            entry = {
                'meal_type':   meal_type,
                'items':       items,
                'item_count':  len(items),
                'total_cal':   round(total_cal, 1),
                'total_prot':  total_prot,
                'total_carb':  total_carb,
                'total_fat':   total_fat,
                'last_eaten':  date_key,
                'count':       1,
                'label':       ', '.join(i['food_name'] for i in items[:2])
                               + (f' +{len(items)-2} more' if len(items) > 2 else ''),
            }
            seen_signatures[sig] = entry
            combos_list.append(entry)

    # Sort by count desc, then recency
    combos_list.sort(key=lambda x: (x['count'], x['last_eaten']), reverse=True)

    # Yesterday's log for "copy yesterday" shortcut
    yesterday_rows = execute(
        """SELECT id, food_id, food_name, meal_type, date_key,
                  quantity_g, calories, protein, carbs, fat, fiber
           FROM food_logs WHERE date_key = ? AND user_id=? ORDER BY meal_type, logged_at""",
        (yesterday, current_user_id()), fetchall=True)

    yesterday_by_meal = defaultdict(list)
    for r in yesterday_rows:
        yesterday_by_meal[r['meal_type']].append({
            'food_id':   r['food_id'],
            'food_name': r['food_name'],
            'meal_type': r['meal_type'],
            'quantity_g':r['quantity_g'],
            'calories':  round(r['calories'] or 0, 1),
            'protein':   round(r['protein']  or 0, 1),
            'carbs':     round(r['carbs']    or 0, 1),
            'fat':       round(r['fat']      or 0, 1),
            'fiber':     round(r['fiber']    or 0, 1),
        })

    return jsonify({
        'combos':    combos_list[:12],   # top 12 combos
        'yesterday': dict(yesterday_by_meal),
        'yesterday_total_cal': round(sum(r['calories'] or 0 for r in yesterday_rows), 0),
        'yesterday_date': yesterday,
    })

@bp.route('/api/food/custom', methods=['POST'])
@require_auth
def add_custom_food():
    data = request.json or {}
    if not data.get('name'):
        return jsonify({'success': False, 'error': 'Name required'}), 400
    f = save_custom_food(data)
    return jsonify({'success': True, 'food': f})


@bp.route('/api/food/barcode/<code>')
@require_auth
def api_food_barcode(code):
    """Scan a food barcode. Returns the user's previously-saved entry
    instantly if they've scanned it before ('saved'); otherwise looks it
    up on Open Food Facts ('openfoodfacts'). 404 if nothing is found."""
    import food_barcode
    if not food_barcode.valid_barcode(code):
        return jsonify({'error': 'Invalid barcode'}), 400

    saved = get_custom_food_by_barcode(code)
    if saved:
        saved['source'] = 'saved'
        return jsonify({'found': True, 'food': saved})

    product = food_barcode.lookup_barcode(code)
    if not product:
        return jsonify({'found': False,
                        'error': 'No product found for that barcode. '
                                 'You can still add it manually.',
                        'barcode': code}), 404
    return jsonify({'found': True, 'food': product})

def generate_nutrition_suggestions(totals, targets, profile):
    suggestions = []
    cal   = totals.get('calories', 0)
    prot  = totals.get('protein', 0)
    carbs = totals.get('carbs', 0)
    fat   = totals.get('fat', 0)
    fiber = totals.get('fiber', 0)
    iron  = totals.get('iron', 0)
    vit_c = totals.get('vit_c', 0)
    vit_d = totals.get('vit_d', 0)
    calcium = totals.get('calcium', 0)
    # These are None until the profile has weight/height/age/gender. They used
    # to fall back to 2000/56/65/250 — population averages — and then this
    # function told the user they were "1,500 kcal below target" and offered to
    # fix it. Advice against a target nobody set isn't personalised; it's just
    # confident. Everything keyed off them is gated on has_targets below.
    t_cal  = targets.get('target_calories')
    t_prot = targets.get('protein_g')
    goal   = profile.get('goal') or 'maintain'
    gender = profile.get('gender') or 'other'
    has_targets = bool(t_cal)

    if cal == 0:
        suggestions.append({'type':'info','icon':'🍽️','text':'Log your meals to see personalised nutrition insights.','priority':0})
        return suggestions

    if has_targets:
        # Calorie balance
        deficit = t_cal - cal
        if deficit > 500:
            suggestions.append({'type':'warning','icon':'⚠️','text':"You're " + str(int(deficit)) + " kcal below target. Add a protein-rich meal like dal or paneer.",'priority':1})
        elif deficit < -300:
            suggestions.append({'type':'warning','icon':'🔴','text':"You're " + str(int(-deficit)) + " kcal over target. Consider a lighter dinner tonight.",'priority':1})
        elif 0 <= deficit <= 200:
            suggestions.append({'type':'success','icon':'✅','text':f"Great calorie balance! Only {int(deficit)} kcal left for today.",'priority':5})

        # Protein
        if t_prot and prot < t_prot * 0.7:
            lacking = round(t_prot - prot, 1)
            fix = 'Add chicken tikka, paneer, or a whey shake' if goal in ('gain','gain_fast') else 'Add a bowl of dal or 2 boiled eggs'
            suggestions.append({'type':'warning','icon':'💪','text':f"Protein low ({prot}g of {t_prot}g target). {fix} to add ~{lacking}g.",'priority':2})
        elif t_prot and prot >= t_prot * 0.9:
            suggestions.append({'type':'success','icon':'💪','text':f"Excellent protein intake ({prot}g)! Muscles will thank you.",'priority':5})
    else:
        # Say what's missing and how to get it, instead of inventing a target
        # to measure them against. The advice below this needs no target —
        # fibre/iron/vitamins are general reference intakes, not personal goals.
        suggestions.append({'type':'info','icon':'🎯',
                            'text':'Add your height, weight, age and gender to get calorie and protein targets.',
                            'priority':1})

    # Fiber
    if fiber < 15:
        suggestions.append({'type':'info','icon':'🥬','text':f"Only {fiber}g fiber today. Add a bowl of salad, bhindi, or fruits like guava.",'priority':3})

    # Iron
    iron_rda = 18 if gender == 'female' else 8
    if iron < iron_rda * 0.5:
        suggestions.append({'type':'warning','icon':'🩸','text':f"Iron is low ({iron}mg). Eat spinach, rajma, or fortified foods. Pair with Vitamin C to boost absorption.",'priority':2})

    # Vitamin D
    if vit_d < 5:
        suggestions.append({'type':'info','icon':'☀️','text':'Vitamin D is low. Spend 15–20 min in morning sunlight and consider eggs or fortified milk.','priority':3})

    # Vitamin C
    if vit_c < 30:
        suggestions.append({'type':'info','icon':'🍊','text':f"Vitamin C low ({vit_c}mg). Add a guava, papaya, or tomato to boost immunity.",'priority':3})

    # Calcium
    cal_rda = 1000
    if calcium < cal_rda * 0.5:
        suggestions.append({'type':'info','icon':'🥛','text':f"Calcium is low ({calcium}mg). Have a glass of milk, dahi, or paneer.",'priority':3})

    # Hydration reminder — only quote a number if it's derived from their body;
    # the old `water_ml, 2500` default was one more invented personal goal.
    water_ml = targets.get('water_ml')
    suggestions.append({'type':'info','icon':'💧',
                        'text': (f"Drink at least {water_ml}ml water today. Coconut water is a great electrolyte boost."
                                 if water_ml else
                                 "Keep your water up through the day. Coconut water is a great electrolyte boost."),
                        'priority':4})

    suggestions.sort(key=lambda x: x['priority'])
    return suggestions[:6]




# ══════════════════════════════════════════════════════════════════════════════
# Medicine Stock / Refill
# ══════════════════════════════════════════════════════════════════════════════