# -*- coding: utf-8 -*-
"""Diet-preference filtering for the food picker.

Safety-critical direction: a stricter diet must NEVER be shown a food that
violates it (a vegetarian must never see chicken; a vegan must never see paneer).
Over-restriction (hiding a borderline-OK food) is acceptable; under-restriction
is not.
"""
import food_data as fd


def _by_id(fid):
    f = fd.FOOD_BY_ID.get(fid)
    assert f is not None, f"fixture food missing: {fid}"
    return f


# ── Every food is classified with a valid diet + jain flag ──────────────────
def test_all_foods_have_valid_diet_and_jain():
    valid = {'nonveg', 'egg', 'veg', 'vegan'}
    for f in fd.FOOD_DB:
        assert f.get('diet') in valid, f"{f['id']} has bad diet {f.get('diet')!r}"
        assert isinstance(f.get('jain'), bool), f"{f['id']} jain not bool"


def test_source_never_leaks_but_diet_does_not_affect_that():
    # diet field lives alongside source; source stays server-side (asserted
    # elsewhere) — here we only confirm diet is present to serve to clients.
    assert all('diet' in f for f in fd.FOOD_DB)


# ── diet_allows monotonicity ────────────────────────────────────────────────
def test_no_pref_and_nonveg_allow_everything():
    for f in fd.FOOD_DB:
        assert fd.diet_allows(f, '')
        assert fd.diet_allows(f, None)
        assert fd.diet_allows(f, 'nonveg')


def test_veg_hides_all_nonveg_and_egg():
    for f in fd.FOOD_DB:
        if f['diet'] in ('nonveg', 'egg'):
            assert not fd.diet_allows(f, 'veg'), f"{f['id']} leaked to veg"


def test_vegan_hides_everything_but_vegan():
    for f in fd.FOOD_DB:
        if f['diet'] != 'vegan':
            assert not fd.diet_allows(f, 'vegan'), f"{f['id']} leaked to vegan"


def test_egg_pref_allows_egg_veg_vegan_only():
    for f in fd.FOOD_DB:
        allowed = fd.diet_allows(f, 'egg')
        assert allowed == (f['diet'] in ('egg', 'veg', 'vegan')), f['id']


def test_jain_pref_only_shows_jain_flagged():
    for f in fd.FOOD_DB:
        assert fd.diet_allows(f, 'jain') == bool(f.get('jain')), f['id']


# ── Custom / unclassified foods are never hidden ────────────────────────────
def test_unclassified_food_is_always_allowed():
    custom = {'id': 'x', 'name': 'My food', 'category': 'Custom'}  # no diet key
    for pref in ('veg', 'vegan', 'egg'):
        assert fd.diet_allows(custom, pref)
    # jain still requires an explicit flag, so it's hidden without one
    assert not fd.diet_allows(custom, 'jain')


# ── search_food end-to-end filtering ────────────────────────────────────────
def test_search_veg_excludes_meat_dishes():
    veg = {f['id'] for f in fd.search_food(diet='veg', limit=2000)}
    for meat in ('butter_chicken', 'cheeseburger', 'kimchi', 'eggs_benedict',
                 'bibimbap', 'panna_cotta', 'collagen_peptides', 'hot_dog'):
        if meat in fd.FOOD_BY_ID:
            assert meat not in veg, f"{meat} shown to vegetarian"


def test_search_vegan_excludes_dairy_and_egg():
    vegan = {f['id'] for f in fd.search_food(diet='vegan', limit=2000)}
    for fid in ('ghee', 'butter', 'omelette', 'creme_brulee'):
        if fid in fd.FOOD_BY_ID:
            assert fid not in vegan, f"{fid} shown to vegan"


def test_search_egg_pref_includes_omelette_excludes_meat():
    egg = {f['id'] for f in fd.search_food(diet='egg', limit=2000)}
    if 'omelette' in fd.FOOD_BY_ID:
        assert 'omelette' in egg
    if 'butter_chicken' in fd.FOOD_BY_ID:
        assert 'butter_chicken' not in egg


def test_specific_reclassifications_locked():
    # These were fixed by web-audit verification agents; lock them so a future
    # DB rebuild can't silently regress a safety-critical label.
    expect = {
        'cheeseburger': 'nonveg', 'kimchi': 'nonveg', 'panna_cotta': 'nonveg',
        'eggs_benedict': 'nonveg', 'collagen_peptides': 'nonveg',
        'bibimbap': 'nonveg', 'hot_dog': 'nonveg', 'chili_con_carne': 'nonveg',
        'omelette': 'egg', 'creme_brulee': 'egg', 'shakshuka': 'egg',
        'oat_milk': 'vegan', 'oreo': 'vegan',
    }
    for fid, diet in expect.items():
        if fid in fd.FOOD_BY_ID:
            assert fd.FOOD_BY_ID[fid]['diet'] == diet, \
                f"{fid} regressed to {fd.FOOD_BY_ID[fid]['diet']}, expected {diet}"
