"""Tests for food_nlp.parse_food_phrase — natural-language food logging.

The parser must never silently mislog: a good phrase resolves to the obvious
foods with correct quantities; a bad phrase surfaces in `unmatched` rather than
guessing. These tests pin the behaviour that the confirm-before-log UI relies on.
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "food_nlp", os.path.join(os.path.dirname(__file__), "..", "food_nlp.py"))
food_nlp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(food_nlp)
parse = food_nlp.parse_food_phrase


def _names(r):
    return [i["food_name"] for i in r["items"]]


def test_multi_item_with_explicit_meal():
    r = parse("2 rotis and dal for lunch", now_hour=13)
    assert r["meal"] == "lunch" and r["meal_explicit"] is True
    assert len(r["items"]) == 2
    roti, dal = r["items"]
    assert "Roti" in roti["food_name"] and roti["qty"] == 2
    assert roti["grams"] == 80          # 2 x 40 g per roti
    assert "Dal" in dal["food_name"]
    assert not r["unmatched"]


def test_bare_count_prefers_countable_food_not_dish():
    # "3 eggs" must be boiled eggs, never "Egg Curry"
    r = parse("3 eggs", now_hour=8)
    assert len(r["items"]) == 1
    it = r["items"][0]
    assert it["food_id"] == "egg_boiled"
    assert it["grams"] == 150           # 3 x 50 g


def test_glued_number_and_unit():
    r = parse("250g chicken tikka", now_hour=20)
    assert len(r["items"]) == 1
    it = r["items"][0]
    assert it["grams"] == 250
    assert it["calories"] > 0


def test_volume_units_convert():
    r = parse("500ml milk", now_hour=9)
    it = r["items"][0]
    assert it["food_id"] == "milk"      # alias -> full-fat cow's milk
    assert it["grams"] == 500


def test_aliases_pick_sensible_default():
    assert parse("dal", now_hour=13)["items"][0]["food_id"] == "dal_tarka"
    assert parse("a cup of chai", now_hour=8)["items"][0]["food_id"] == "masala_chai"
    assert parse("curd", now_hour=13)["items"][0]["food_id"] == "dahi"


def test_meal_inferred_from_hour_when_not_stated():
    assert parse("1 apple", now_hour=8)["meal"] == "breakfast"
    assert parse("1 apple", now_hour=13)["meal"] == "lunch"
    assert parse("1 apple", now_hour=21)["meal"] == "dinner"
    assert parse("1 apple", now_hour=13)["meal_explicit"] is False


def test_fractional_quantity():
    r = parse("half apple", now_hour=16)
    it = r["items"][0]
    assert it["qty"] == 0.5
    assert "0.5" in it["amount_label"]


def test_gibberish_is_unmatched_not_guessed():
    r = parse("blah blah nonsense zzzq", now_hour=12)
    assert r["items"] == []
    assert r["unmatched"]


def test_empty_input():
    r = parse("", now_hour=10)
    assert r["items"] == [] and r["unmatched"] == []


def test_aliases_never_point_at_missing_food():
    ids = {f["id"] for f in food_nlp.FOOD_DB}
    for food in food_nlp._ALIASES.values():
        assert food["id"] in ids


def test_preview_carries_scaled_macros():
    it = parse("2 rotis", now_hour=13)["items"][0]
    for k in ("calories", "protein", "carbs", "fat", "fiber"):
        assert k in it
    assert it["calories"] > 0
