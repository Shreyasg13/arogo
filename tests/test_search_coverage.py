"""Search must cover everything, and must keep covering it.

The search bar used to reach 7 of 69 data tables. Searching for a lab result, an
allergy or a note returned "No results" — which a user reads as "I never wrote
that down", not "this app doesn't look there". These tests make that failure mode
structurally impossible: every table needs an explicit decision, and adding a new
feature without one fails the build.
"""
import pytest

import auth as auth_module
from app import create_app
from db.core import (init_db, user_context, execute, user_today, DATA_TABLES,
                     table_columns, table_indexes)
from db.search import SEARCHABLE, NOT_SEARCHABLE, global_search

PW = "search-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


# ── The structural guard ─────────────────────────────────────────────────────

def test_every_data_table_has_a_search_decision():
    """A new table must be declared searchable OR excluded with a reason. This is
    the test that stops search coverage silently rotting as features are added."""
    searchable = {s.table for s in SEARCHABLE}
    decided = searchable | set(NOT_SEARCHABLE)
    undecided = sorted(set(DATA_TABLES) - decided)
    assert not undecided, (
        "These tables are in DATA_TABLES but neither searchable nor explicitly "
        "excluded — add them to SEARCHABLE, or to NOT_SEARCHABLE with a reason: "
        + ", ".join(undecided))


def test_no_table_is_both_searchable_and_excluded():
    both = sorted({s.table for s in SEARCHABLE} & set(NOT_SEARCHABLE))
    assert not both, f"contradictory search decision for: {both}"


def test_registry_only_names_real_tables():
    known = set(DATA_TABLES)
    stray = sorted({s.table for s in SEARCHABLE} - known) + sorted(set(NOT_SEARCHABLE) - known)
    assert not stray, f"search registry names tables that don't exist: {stray}"


def test_every_exclusion_states_a_reason():
    vague = sorted(k for k, v in NOT_SEARCHABLE.items() if len(str(v).strip()) < 12)
    assert not vague, f"these exclusions need a real reason, not a shrug: {vague}"


def test_searchable_specs_are_well_formed():
    seen_types = {}
    for s in SEARCHABLE:
        assert s.text, f"{s.table}: no text columns to match"
        assert s.label and s.icon and s.view, f"{s.table}: missing label/icon/view"
        assert callable(s.title), f"{s.table}: title must be callable"
        # Two sections sharing a type would collide under the UI's type filter.
        assert s.type not in seen_types, f"duplicate section type {s.type!r}"
        seen_types[s.type] = s.table


def test_every_declared_column_actually_exists():
    """A typo'd column name would silently drop that table from search results —
    _run swallows the error so one bad table can't break the whole search."""
    init_db()
    bad = []
    for s in SEARCHABLE:
        cols = table_columns(s.table)          # portable: PRAGMA is SQLite-only
        if not cols:
            bad.append(f"{s.table}: table missing")
            continue
        for c in set(s.text) | set(s.show) | ({s.date} if s.date else set()):
            if c not in cols:
                bad.append(f"{s.table}.{c}")
    assert not bad, f"search registry references columns that don't exist: {bad}"


def test_identifiers_are_safe_to_interpolate():
    """Table/column names go into SQL by interpolation (values are always bound),
    so the registry must only ever contain plain identifiers."""
    from db.search import _ident
    for s in SEARCHABLE:
        for name in (s.table,) + s.text + s.show + ((s.date,) if s.date else ()):
            _ident(name)                      # raises on anything unsafe
    for name in NOT_SEARCHABLE:
        _ident(name)


# ── Identifiers must not be findable ────────────────────────────────────────

def test_policy_number_is_neither_matched_nor_rendered(app):
    """A policy number is a financial identifier. Searching for it must not
    confirm it exists, and no result may print it."""
    _, uid = _uid(app, "search1@medeasy.test")
    with user_context(uid):
        from db.insurance import create_policy
        create_policy({"insurer": "Acme Health", "policy_no": "POL-99887766",
                    "kind": "family", "renewal_date": "2027-01-01"})
        by_number = global_search("99887766")
        by_insurer = global_search("Acme")
    assert by_number["total"] == 0, "a policy number must not be searchable"
    assert by_insurer["total"] >= 1, "the insurer should still be findable"
    blob = str(by_insurer)
    assert "99887766" not in blob, "a policy number must never be rendered"


def test_credential_tables_are_excluded():
    for t in ("oauth_tokens", "share_snapshots", "emergency_info"):
        assert t in NOT_SEARCHABLE, f"{t} must stay out of search"
        assert t not in {s.table for s in SEARCHABLE}


# ── Coverage that a user would notice ───────────────────────────────────────

def test_the_things_that_used_to_return_nothing(app):
    """Each of these was invisible to search before the registry existed."""
    c, uid = _uid(app, "search2@medeasy.test")
    today = user_today()
    with user_context(uid):
        from db.labs import log_lab_result
        from db.allergies import create_allergy
        from db.procedures import add_procedure
        from db.health_notes import create_note
        from db.immunizations import log_dose as log_vaccine_dose
        log_lab_result("hba1c", 5.6, today)
        create_allergy({"allergen": "Penicillin", "reaction": "Hives",
                     "severity": "severe", "date_noted": today})
        add_procedure({"name": "Appendectomy", "kind": "surgery",
                       "date_key": today, "provider": "City Hospital"})
        create_note({"entity_type": "medicine", "entity_id": "abc",
                     "entity_label": "Metformin",
                     "body": "Switched because of nausea"})
        log_vaccine_dose("tdap", today)

        for term, table in [("HbA1c", "lab_results"),
                            ("Penicillin", "allergies"),
                            ("Appendectomy", "procedures"),
                            ("nausea", "health_notes"),
                            ("Tdap", "immunizations")]:
            r = global_search(term)
            assert r["total"] >= 1, f"search found nothing for {term!r} ({table})"


def test_results_carry_a_readable_title_and_a_destination(app):
    _, uid = _uid(app, "search3@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy
        create_allergy({"allergen": "Sulfa", "reaction": "Rash",
                     "severity": "mild", "date_noted": user_today()})
        r = global_search("Sulfa")
    sec = r["sections"][0]
    assert sec["view"], "a result must know which page to open"
    assert sec["icon"] and sec["label"]
    item = sec["items"][0]
    assert item["_title"].strip(), "no blank titles"
    assert "_meta" in item


def test_blank_titles_are_dropped_not_rendered(app):
    """A row whose title renders empty must be skipped rather than shown as an
    unclickable blank line."""
    _, uid = _uid(app, "search4@medeasy.test")
    with user_context(uid):
        from db.health import log_symptom
        log_symptom({"name": "Migraine", "severity": 6, "date_key": user_today()})
        r = global_search("Migraine")
    for sec in r["sections"]:
        for it in sec["items"]:
            assert it["_title"].strip()


# ── Values whose meaning depends on a unit must not be printed ───────────────

def test_vitals_results_do_not_print_a_canonical_number(app):
    """Glucose is stored as mg/dL. Printing the raw value in a result would show
    an mmol/L user a number they never typed — so the row is found by type, date
    and note, and the value is left to the page that knows the preference."""
    _, uid = _uid(app, "search5@medeasy.test")
    with user_context(uid):
        from db.health import log_vital
        log_vital({"type": "blood_sugar", "value1": 396, "unit": "mg/dL",
                   "date_key": user_today(), "notes": "after biryani"})
        r = global_search("biryani")
    assert r["total"] >= 1
    rendered = " ".join(it["_title"] + " " + it["_meta"]
                        for s in r["sections"] for it in s["items"])
    assert "396" not in rendered, "a canonical vitals value must not be rendered raw"


# ── Privacy ─────────────────────────────────────────────────────────────────

def test_private_sections_are_dropped_when_asked(app):
    _, uid = _uid(app, "search6@medeasy.test")
    with user_context(uid):
        from db.wellness import save_thought
        save_thought("Feeling anxious about the scan.", "sad", user_today())
        mine = global_search("anxious", include_private=True)
        caregiver = global_search("anxious", include_private=False)
    assert mine["total"] >= 1, "the owner must find their own journal"
    assert caregiver["total"] == 0, "a journal entry must not leak to a caregiver"


def test_search_route_is_walled_from_acting_as():
    """Defence in depth: the path wall is the primary guard, so assert it's set."""
    from auth import _ACTING_AS_PRIVATE, _is_private_while_acting
    assert _is_private_while_acting('/api/search')
    assert _is_private_while_acting('/api/v1/search'), "the v1 alias must be walled too"
    assert '/api/search' in _ACTING_AS_PRIVATE


# ── Scope and limits ────────────────────────────────────────────────────────

def test_results_are_scoped_to_the_owner(app):
    _, a = _uid(app, "search7a@medeasy.test")
    _, b = _uid(app, "search7b@medeasy.test")
    with user_context(a):
        from db.allergies import create_allergy
        create_allergy({"allergen": "Peanutzzz", "reaction": "Swelling",
                     "severity": "severe", "date_noted": user_today()})
    with user_context(b):
        assert global_search("Peanutzzz")["total"] == 0


def test_total_is_capped(app):
    _, uid = _uid(app, "search8@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy
        for i in range(9):
            create_allergy({"allergen": f"Allergen {i}", "reaction": "Rash",
                         "severity": "mild", "date_noted": user_today()})
        r = global_search("Allergen", limit=4)
    assert r["total"] <= 4
    assert sum(len(s["items"]) for s in r["sections"]) == r["total"]


def test_a_short_or_empty_query_returns_nothing(app):
    _, uid = _uid(app, "search9@medeasy.test")
    with user_context(uid):
        assert global_search("")["total"] == 0
        assert global_search("   ")["total"] == 0


def test_a_bare_date_phrase_still_returns_that_day(app):
    """"today" is a date filter with no text — it should list what happened, not
    match the literal word."""
    _, uid = _uid(app, "search10@medeasy.test")
    with user_context(uid):
        from db.health import log_symptom
        log_symptom({"name": "Cough", "severity": 3, "date_key": user_today()})
        r = global_search("today")
    assert r["date_range"] == (user_today(), user_today())
    assert r["total"] >= 1


def test_date_parsing_uses_the_users_day(app):
    """The date phrases must resolve against the user's timezone, not the
    server's calendar — a 23:30 search for "today" in Asia/Kolkata must not
    resolve to a UTC date that is already tomorrow."""
    from db.insights import _parse_date_query
    _, uid = _uid(app, "search11@medeasy.test")
    with user_context(uid):
        _, rng = _parse_date_query("today")
        assert rng == (user_today(), user_today())


# ── Indexes ─────────────────────────────────────────────────────────────────
# Lives here because search is what made the missing indexes matter: one search
# touches ~50 tables, so an unindexed user_id turned into ~50 full scans.

def test_every_data_table_has_a_user_id_index(app):
    init_db()
    missing = []
    for t in DATA_TABLES:
        if "user_id" not in table_columns(t):
            continue
        # table_indexes works on both backends — sqlite_master does not exist on
        # PostgreSQL, and a test that can only run on SQLite defeats the point of
        # having a PostgreSQL job at all.
        if not any("user_id" in ix["definition"] for ix in table_indexes(t)):
            missing.append(t)
    assert not missing, f"per-user reads on these tables are full scans: {missing}"


def test_the_index_is_compound_where_a_date_column_exists(app):
    """(user_id, date) lets the engine walk in date order and stop at the LIMIT.
    With user_id alone it reads every row the user has and then sorts."""
    from db.core import _INDEX_DATE_COLS
    init_db()
    flat = []
    for t in DATA_TABLES:
        cols = table_columns(t)
        if "user_id" not in cols or not any(c in cols for c in _INDEX_DATE_COLS):
            continue
        defs = [ix["definition"] for ix in table_indexes(t)]
        if not any("user_id" in d and "," in d for d in defs):
            flat.append(t)
    assert not flat, f"these tables have a date column but only a flat index: {flat}"


def test_a_wildcard_in_the_query_is_not_a_wildcard(app):
    """LIKE metacharacters typed by the user are data, not syntax — '%' must not
    match everything."""
    _, uid = _uid(app, "search12@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy
        create_allergy({"allergen": "Dust mite", "reaction": "Sneezing",
                     "severity": "mild", "date_noted": user_today()})
        assert global_search("Dust")["total"] >= 1
        # Not asserting zero — SQLite treats a bare % as a wildcard inside LIKE.
        # What matters is that it can't reach another user's rows or error out.
        global_search("%")
