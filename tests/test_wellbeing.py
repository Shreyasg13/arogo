"""Questionnaires, donations, symptom duration and leaving on time.

The questionnaire tests carry most of the weight here. PHQ-9 and GAD-7 are
published instruments with fixed wording and published cut-offs, which is
exactly why they belong in an app that refuses to invent clinical content —
nothing in the output is Arogo's opinion.

Two things must hold no matter what else changes: the app never turns a score
into a diagnosis, and a non-zero answer to PHQ-9 item 9 — thoughts of self-harm
— is never treated as just a number.
"""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today
from db import questionnaires as q
from db import donations as dn

PW = "well-pw-123456"


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


# ── Scoring is arithmetic, not judgement ────────────────────────────────────

def test_phq9_scores_against_the_published_cutoffs():
    assert q.score_only("phq9", [0] * 9)["score"] == 0
    assert q.score_only("phq9", [0] * 9)["band"] == "Minimal"
    assert q.score_only("phq9", [3] * 9)["score"] == 27
    assert q.score_only("phq9", [3] * 9)["band"] == "Severe"
    # 10 → moderate; the boundary is where a mis-set band would show first.
    assert q.score_only("phq9", [2, 2, 2, 2, 2, 0, 0, 0, 0])["score"] == 10
    assert q.score_only("phq9", [2, 2, 2, 2, 2, 0, 0, 0, 0])["band"] == "Moderate"
    assert q.score_only("phq9", [1, 1, 1, 1, 1, 0, 0, 0, 0])["band"] == "Mild"


def test_gad7_scores_against_the_published_cutoffs():
    assert q.score_only("gad7", [0] * 7)["band"] == "Minimal"
    assert q.score_only("gad7", [3] * 7)["score"] == 21
    assert q.score_only("gad7", [3] * 7)["band"] == "Severe"
    assert q.score_only("gad7", [2, 2, 1, 0, 0, 0, 0])["score"] == 5
    assert q.score_only("gad7", [2, 2, 1, 0, 0, 0, 0])["band"] == "Mild"


def test_the_instruments_have_the_right_number_of_items():
    assert len(q.PHQ9_ITEMS) == 9
    assert len(q.GAD7_ITEMS) == 7
    assert len(q.CHOICES) == 4


def test_a_partial_questionnaire_is_refused_not_scored():
    """Treating blanks as zero reads as "not at all" and quietly lowers the
    result — the one direction a mood screen must never drift."""
    with pytest.raises(ValueError):
        q.score_only("phq9", [1, 2, 3])
    with pytest.raises(ValueError):
        q.score_only("phq9", [1] * 8 + [None])
    with pytest.raises(ValueError):
        q.score_only("phq9", [1] * 8 + [9])          # out of the 0–3 scale


# ── It is never a diagnosis ─────────────────────────────────────────────────

def test_every_result_carries_the_not_a_diagnosis_line(app):
    c, uid = _uid(app, "well1@medeasy.test")
    r = c.post("/api/questionnaires/phq9", json={"answers": [3] * 9}).get_json()
    assert r["success"] is True
    assert "not a diagnosis" in r["not_a_diagnosis"].lower()


def test_the_output_never_names_a_condition(app):
    """A band describes the answers. It must not say someone HAS anything."""
    result = q.score_only("phq9", [3] * 9)
    blob = " ".join(str(v) for v in result.values()).lower()
    for claim in ("you have depression", "diagnosed", "you are depressed",
                  "disorder", "you suffer"):
        assert claim not in blob, f"the result claims {claim!r}"


def test_past_runs_are_moments_not_a_trend(app):
    """Two scores a week apart are two days. People make decisions about
    medication on a sentence like "you're improving"."""
    c, uid = _uid(app, "well2@medeasy.test")
    with user_context(uid):
        q.save_run("phq9", [2] * 9, taken_on="2026-08-01")
        q.save_run("phq9", [1] * 9, taken_on="2026-08-20")
        runs = q.list_runs("phq9")
    assert len(runs) == 2
    for r in runs:
        for forbidden in ("trend", "direction", "change", "improving", "worse"):
            assert forbidden not in r, f"a run reports a {forbidden}"


# ── Item 9 is never just a number ───────────────────────────────────────────

def test_a_nonzero_self_harm_answer_raises_the_flag():
    zero = q.score_only("phq9", [0] * 9)
    assert zero["risk_flag"] is False
    for level in (1, 2, 3):
        flagged = q.score_only("phq9", [0] * 8 + [level])
        assert flagged["risk_flag"] is True, f"item 9 = {level} must flag"


def test_the_flag_does_not_depend_on_the_total(app):
    """A low total with a positive item 9 is exactly the case that must not slip
    through — the score reads reassuring and the answer does not."""
    r = q.score_only("phq9", [0] * 8 + [1])
    assert r["score"] == 1
    assert r["band"] == "Minimal"
    assert r["risk_flag"] is True


def test_the_route_attaches_guidance_when_flagged(app):
    c, uid = _uid(app, "well3@medeasy.test")
    r = c.post("/api/questionnaires/phq9", json={"answers": [0] * 8 + [2]}).get_json()
    assert r["risk_flag"] is True
    risk = r["risk"]
    assert risk["headline"] and risk["ask"] and risk["urgent"]
    assert "tell someone today" in risk["ask"].lower()


def test_no_guidance_when_not_flagged(app):
    c, uid = _uid(app, "well4@medeasy.test")
    r = c.post("/api/questionnaires/phq9", json={"answers": [1] * 8 + [0]}).get_json()
    assert r["risk_flag"] is False
    assert "risk" not in r


def test_gad7_has_no_risk_item():
    assert q.INSTRUMENTS["gad7"]["risk_item"] is None
    assert q.score_only("gad7", [3] * 7)["risk_flag"] is False


def test_crisis_numbers_come_from_the_shipped_table_never_invented():
    """A wrong number is worse than no number to someone dialling it at 3am."""
    known = q.risk_response("IN")
    assert known["numbers"], "a listed country must offer its real numbers"
    assert any(n["number"] == "112" for n in known["numbers"])
    assert known["no_numbers_note"] is None

    # An unrecognised or unset country must yield NO numbers. The shared
    # emergency helper silently falls back to the app's default country, which
    # is fine on a health-ID card and dangerous here — it would print one
    # country's ambulance number to someone in another.
    for unknown_country in ("ZZ", "", None):
        unknown = q.risk_response(unknown_country)
        assert unknown["numbers"] == [], f"{unknown_country!r} produced numbers"
        assert "does not have emergency numbers" in unknown["no_numbers_note"].lower()


def test_questionnaires_are_walled_from_a_caregiver():
    """A PHQ-9 run is a record of someone's mood, item by item."""
    from auth import _is_private_while_acting
    assert _is_private_while_acting("/api/questionnaires")
    assert _is_private_while_acting("/api/v1/questionnaires")


def test_runs_are_scoped_per_user(app):
    ca, _ = _uid(app, "well5a@medeasy.test")
    cb, _ = _uid(app, "well5b@medeasy.test")
    ca.post("/api/questionnaires/gad7", json={"answers": [1] * 7})
    assert cb.get("/api/questionnaires/runs").get_json()["runs"] == []


# ── Blood donations ─────────────────────────────────────────────────────────

def test_eligibility_is_a_date_not_a_verdict(app):
    """Illness, medication, travel and iron levels all affect whether someone
    can give, and none of it is knowable from a donation log."""
    c, uid = _uid(app, "well6@medeasy.test")
    with user_context(uid):
        dn.add_donation({"kind": "whole", "donated_on": "2026-06-01"})
        e = dn.next_eligible()
    whole = next(k for k in e["kinds"] if k["kind"] == "whole")
    assert whole["eligible_from"] == "2026-08-30"        # 90 days on
    assert "eligible" not in str(whole.get("can_donate", ""))
    assert "can_donate" not in whole
    assert "decides that" in e["note"]


def test_never_donated_means_no_date_rather_than_today(app):
    c, uid = _uid(app, "well7@medeasy.test")
    with user_context(uid):
        e = dn.next_eligible()
    for k in e["kinds"]:
        assert k["last_donated"] is None
        assert k["eligible_from"] is None, "with no history there is nothing to compute"


def test_a_future_donation_date_is_refused(app):
    c, uid = _uid(app, "well8@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            dn.add_donation({"donated_on": "2099-01-01"})


def test_a_deleted_donation_is_recoverable(app):
    c, uid = _uid(app, "well9@medeasy.test")
    with user_context(uid):
        from db.trash import list_trash
        d = dn.add_donation({"kind": "plasma", "donated_on": "2026-07-01",
                             "place": "City centre"})
        dn.delete_donation(d["id"])
        assert any(i["kind"] == "Blood donation" for i in list_trash())


# ── Symptom duration ────────────────────────────────────────────────────────

def test_a_symptom_records_when_it_actually_started(app):
    """"How long has this been going on?" is asked at every appointment, and the
    app could only answer "when did you first tell me"."""
    c, uid = _uid(app, "well10@medeasy.test")
    with user_context(uid):
        from db.health import log_symptom
        s = log_symptom({"name": "Back pain", "severity": 6,
                         "date_key": "2026-08-20", "started_on": "2026-07-15",
                         "ongoing": True})
    assert s["started_on"] == "2026-07-15"
    assert s["ongoing"] == 1


def test_a_start_date_after_the_log_date_is_dropped(app):
    c, uid = _uid(app, "well11@medeasy.test")
    with user_context(uid):
        from db.health import log_symptom
        s = log_symptom({"name": "Nonsense", "severity": 3,
                         "date_key": "2026-08-20", "started_on": "2026-09-01"})
    assert s["started_on"] is None, "a symptom cannot start after it was logged"


def test_ongoing_is_unknown_rather_than_false_when_not_asked(app):
    """A gap in the log means nothing was written down, not that it stopped."""
    c, uid = _uid(app, "well12@medeasy.test")
    with user_context(uid):
        from db.health import log_symptom
        s = log_symptom({"name": "Quiet", "severity": 3, "date_key": user_today()})
    assert s["ongoing"] is None


# ── Leaving on time ─────────────────────────────────────────────────────────

def test_leave_by_uses_the_travel_time_the_user_entered():
    from db.health import leave_by
    assert leave_by({"time": "09:30", "travel_minutes": 45}) == "08:45"


def test_leave_by_says_when_it_falls_on_the_previous_day():
    from db.health import leave_by
    assert leave_by({"time": "00:20", "travel_minutes": 60}) == "the night before, 23:20"


def test_no_travel_time_means_no_leave_by():
    """A leave-by derived from a guessed journey is worse than none — it makes
    someone late to an appointment they waited weeks for."""
    from db.health import leave_by
    assert leave_by({"time": "09:30"}) is None
    assert leave_by({"travel_minutes": 45}) is None
    assert leave_by({"time": "", "travel_minutes": 45}) is None


def test_an_appointment_stores_the_travel_time(app):
    c, uid = _uid(app, "well13@medeasy.test")
    with user_context(uid):
        from db.health import create_appointment, leave_by
        a = create_appointment({"title": "Dentist", "date": "2026-09-10",
                                "time": "14:00", "travel_minutes": 30})
    assert a["travel_minutes"] == 30
    assert leave_by(a) == "13:30"


# ── Routes ──────────────────────────────────────────────────────────────────

def test_routes_require_auth(app):
    anon = app.test_client()
    for path in ("/api/questionnaires", "/api/questionnaires/runs",
                 "/api/donations", "/api/donations/eligibility"):
        assert anon.get(path).status_code == 401, path
    assert anon.post("/api/questionnaires/phq9", json={"answers": [0] * 9}).status_code == 401


def test_an_unknown_instrument_is_refused(app):
    c, _ = _uid(app, "well14@medeasy.test")
    r = c.post("/api/questionnaires/made-up", json={"answers": [0]})
    assert r.status_code == 400
