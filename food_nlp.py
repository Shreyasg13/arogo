"""
food_nlp.py — turn a typed/spoken phrase into a food-log preview.

Parses things like "2 rotis and dal for lunch" or "a banana and 3 eggs" into
structured items resolved against FOOD_DB, with quantities converted to grams
and nutrients scaled. It NEVER logs anything — it returns a preview so the UI
can show the user exactly what will be recorded and let them confirm or cancel.
A bad guess is surfaced (either as a low-confidence match the user can see, or
in `unmatched`), never silently written as if it were the user's own data.

Public API:
    parse_food_phrase(text, now_hour=None) -> {
        meal, meal_explicit, items[], unmatched[]
    }
"""
import re

try:
    from food_data import FOOD_DB
except Exception:  # pragma: no cover - mirror routes/food.py import robustness
    import importlib.util, os
    _spec = importlib.util.spec_from_file_location(
        "food_data", os.path.join(os.path.dirname(__file__), "food_data.py"))
    _fd = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_fd)
    FOOD_DB = _fd.FOOD_DB

# ── vocabulary ──────────────────────────────────────────────────────────────
_MEAL_WORDS = {
    "breakfast": "breakfast", "brekkie": "breakfast", "brunch": "breakfast",
    "lunch": "lunch",
    "dinner": "dinner", "supper": "dinner",
    "snack": "snack", "snacks": "snack",
}
# words that carry no matching signal and should be dropped from a food name
_FILLER = {"a", "an", "some", "of", "the", "with", "and", "plus", "my",
           "had", "ate", "eat", "eaten", "having", "log", "logged", "few",
           "little", "bit", "for", "just", "only", "today", "now"}
# unit word -> canonical unit token
_UNITS = {
    "g": "g", "gram": "g", "grams": "g", "gm": "g", "gms": "g",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml",
    "cup": "cup", "cups": "cup", "glass": "cup", "glasses": "cup",
    "bowl": "bowl", "bowls": "bowl", "plate": "plate", "plates": "plate",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "spoon": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "scoop": "scoop", "scoops": "scoop",
    "piece": "piece", "pieces": "piece", "pcs": "piece", "pc": "piece",
    "slice": "piece", "slices": "piece",
}
# spelled-out small numbers
_WORD_NUM = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half": 0.5,
    "dozen": 12, "couple": 2,
}


def _singular(word):
    """Best-effort singularizer for food words (rotis->roti, berries->berry)."""
    w = word
    if len(w) <= 3:
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "xes", "sses", "zzes")):
        return w[:-2]
    if w.endswith("oes"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _norm_words(text):
    """Lowercase, split on non-letters, drop filler, singularize."""
    words = re.findall(r"[a-z]+", text.lower())
    return [_singular(w) for w in words if w not in _FILLER]


# Pre-normalized FOOD_DB index for matching.
def _build_index():
    idx = []
    for f in FOOD_DB:
        core = f["name"].split("(")[0].strip().lower()
        words = _norm_words(core)
        idx.append({
            "food": f,
            "core": core,
            "norm": " ".join(words),
            "words": words,
            "has_piece": bool(f.get("piece") and f["piece"].get("g")),
            "is_supp": f.get("category") == "Supplements",
        })
    return idx


_INDEX = _build_index()


# Common single words are genuinely ambiguous ("milk" matches oat/whole/skimmed
# equally). Pin each to a sensible default so a bare word logs the obvious thing.
# Targets are resolved to real FOOD_DB ids at import; unknown targets are dropped
# so this can never point at a food that doesn't exist.
_ALIAS_TARGETS = {
    "milk": "full fat milk", "egg": "boiled egg", "chapati": "roti",
    "chai": "masala chai", "tea": "masala chai", "coffee": "black coffee",
    "curd": "dahi", "yogurt": "dahi", "yoghurt": "dahi", "dahi": "dahi",
    "daal": "dal tarka", "dhal": "dal tarka", "dal": "dal tarka",
    "lassi": "sweet lassi", "rice": "white rice", "chawal": "white rice",
    "roti": "roti", "paneer": "paneer",
}


def _resolve_aliases():
    out = {}
    for alias, target in _ALIAS_TARGETS.items():
        food = None
        for e in _INDEX:                       # exact core-name, then startswith
            if e["core"] == target:
                food = e["food"]; break
        if food is None:
            for e in _INDEX:
                if e["core"].startswith(target):
                    food = e["food"]; break
        if food is not None:
            out[_singular(alias)] = food
    return out


_ALIASES = _resolve_aliases()


def _score(query_words, entry):
    """Higher = better match of query_words (already normalized) to a food."""
    if not query_words:
        return 0
    q = " ".join(query_words)
    fwords = entry["words"]
    fset = set(fwords)
    if q == entry["norm"]:
        return 100
    # every query word is a whole word in the food name
    if all(w in fset for w in query_words):
        # richer when the food name isn't padded with extra words
        extra = len(fwords) - len(query_words)
        return 75 - min(extra, 6) * 3
    # food name starts with the query
    if entry["norm"].startswith(q):
        return 55
    # substring of the joined name
    if q in entry["norm"]:
        return 40
    # partial: fraction of query words found
    found = sum(1 for w in query_words if w in fset)
    if found:
        return int(30 * found / len(query_words))
    return 0


def _best_match(name_words, prefer_piece=False):
    """Return (food, score) for the best FOOD_DB match, or (None, 0).

    prefer_piece: the user gave a bare count ("3 eggs"), so a countable food
    (Boiled Egg) should win over a dish that merely contains the word (Egg Curry).
    """
    best, best_score = None, 0
    for entry in _INDEX:
        s = _score(name_words, entry)
        if s <= 0:
            continue
        # tie-breakers, expressed as a tiny fractional bonus so they never
        # outweigh a real score difference
        tie = 0.0
        if not entry["is_supp"]:
            tie += 0.4                         # prefer real foods over powders
        if len(entry["words"]) <= 2:
            tie += 0.3                         # prefer the plain/generic item
        if prefer_piece and entry["has_piece"]:
            tie += 0.6                         # a count implies a countable food
        tie -= min(len(entry["core"]), 40) * 0.002  # nudge toward shorter names
        if s + tie > best_score:
            best, best_score = entry, s + tie
    if best is None:
        return None, 0
    return best, best_score


def _grams_for(food, qty, unit):
    """Convert an entered quantity+unit into grams for this food."""
    serving = food.get("serving_g") or 100
    piece = food.get("piece") if (food.get("piece") and food["piece"].get("g")) else None
    if unit == "g" or unit == "ml":
        return qty
    if unit == "cup":
        return qty * 240
    if unit == "tbsp":
        return qty * 15
    if unit == "tsp":
        return qty * 5
    if unit in ("bowl", "plate", "scoop"):
        return qty * serving
    if unit == "piece":
        return qty * (piece["g"] if piece else serving)
    # no explicit unit: a count of pieces if countable, else a count of servings
    if piece:
        return qty * piece["g"]
    return qty * serving


def _round(x, nd=1):
    r = round(float(x), nd)
    return int(r) if r == int(r) else r


def _scale_item(food, grams):
    s = grams / 100.0
    return {
        "calories": _round((food.get("calories") or 0) * s, 0),
        "protein": _round((food.get("protein") or 0) * s),
        "carbs": _round((food.get("carbs") or 0) * s),
        "fat": _round((food.get("fat") or 0) * s),
        "fiber": _round((food.get("fiber") or 0) * s),
    }


def _infer_meal(now_hour):
    if now_hour is None:
        return "snack"
    h = int(now_hour) % 24
    if 4 <= h <= 10:
        return "breakfast"
    if 11 <= h <= 15:
        return "lunch"
    if 16 <= h <= 18:
        return "snack"
    return "dinner"          # 19:00–03:59


def _extract_meal(text):
    """Pull a trailing/embedded meal word out; return (meal or None, text)."""
    for word, meal in _MEAL_WORDS.items():
        # "for lunch", "lunch:", "at dinner", or a standalone meal word
        pat = re.compile(r"\b(?:for|at|as|in)?\s*" + re.escape(word) + r"\b", re.I)
        if pat.search(text):
            text = pat.sub(" ", text, count=1)
            return meal, text
    return None, text


def _split_items(text):
    """Split a food phrase into per-item chunks on connectors."""
    parts = re.split(r"\s*(?:,|\band\b|\+|&|\bwith\b|\bplus\b)\s*", text, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def _parse_qty(chunk):
    """Return (qty, unit, name_words) for one chunk like '2 rotis' or 'a cup of tea'."""
    words = chunk.strip().split()
    if not words:
        return 1.0, None, []
    qty, unit, had_number = None, None, False
    i = 0
    # leading numeric quantity, optionally with a glued unit: "2", "1.5",
    # "1/2", "250g", "500ml", "2cups"
    m = re.match(r"^(\d+(?:\.\d+)?)(?:/(\d+))?([a-z]+)?$", words[0].lower())
    if m:
        qty = float(m.group(1))
        if m.group(2):
            qty = qty / float(m.group(2))
        if m.group(3) and m.group(3) in _UNITS:
            unit = _UNITS[m.group(3)]
        i = 1
        had_number = True
    elif words[0].lower() in _WORD_NUM:
        qty = float(_WORD_NUM[words[0].lower()])
        i = 1
        had_number = True
    # optional standalone unit word right after the quantity
    if unit is None and i < len(words) and words[i].lower() in _UNITS:
        unit = _UNITS[words[i].lower()]
        i += 1
    if qty is None:
        qty = 1.0
    name_words = _norm_words(" ".join(words[i:]))
    return qty, unit, name_words, had_number


# minimum score to accept a match; below this the chunk is "unmatched"
_MIN_SCORE = 40


def parse_food_phrase(text, now_hour=None):
    """Parse a natural-language food phrase into a loggable preview."""
    text = (text or "").strip()
    if not text:
        return {"meal": _infer_meal(now_hour), "meal_explicit": False,
                "items": [], "unmatched": []}

    meal, rest = _extract_meal(text)
    items, unmatched = [], []
    for chunk in _split_items(rest)[:8]:
        qty, unit, name_words, had_number = _parse_qty(chunk)
        if not name_words:
            continue
        # a curated alias wins outright; else fuzzy-match (a bare count like
        # "3 eggs" implies a countable food, not a dish)
        alias_food = _ALIASES.get(" ".join(name_words))
        if alias_food is not None:
            food, score = alias_food, 100
        else:
            entry, score = _best_match(name_words, prefer_piece=had_number and not unit)
            if not entry or score < _MIN_SCORE:
                unmatched.append(" ".join(name_words))
                continue
            food = entry["food"]
        grams = _grams_for(food, qty, unit)
        if grams <= 0:
            unmatched.append(" ".join(name_words))
            continue
        macro = _scale_item(food, grams)
        # how to phrase the amount back to the user
        piece = food.get("piece") if (food.get("piece") and food["piece"].get("g")) else None
        if unit in ("g", "ml"):
            amount = "%s%s" % (_round(qty, 0), unit)
        elif unit:
            amount = "%s %s" % (_round(qty, 1), unit + ("s" if qty > 1 else ""))
        elif piece:
            u = piece.get("unit") or "piece"
            amount = "%s %s" % (_round(qty, 1), u + ("s" if qty > 1 else ""))
        else:
            amount = "%s serving%s" % (_round(qty, 1), "" if qty <= 1 else "s")
        items.append({
            "food_id": food["id"],
            "food_name": food["name"],
            "emoji": food.get("emoji", "🍽️"),
            "qty": _round(qty, 2),
            "unit": unit or "",
            "grams": _round(grams, 1),
            "amount_label": amount,
            "confident": score >= 55,
            **macro,
        })

    return {
        "meal": meal or _infer_meal(now_hour),
        "meal_explicit": meal is not None,
        "items": items,
        "unmatched": unmatched,
    }
