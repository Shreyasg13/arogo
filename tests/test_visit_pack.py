"""The appointment pack — one visit, everything to bring, on one page.

The risk with this feature is not that it breaks. It is that it reads as a
summary of someone's health while being an index of what one app happens to
hold, and gets handed to a clinician who reasonably assumes otherwise. So the
tests here spend most of their effort on what the page claims rather than on
whether it renders:

  An empty section must still appear, saying it is empty. Silently dropping
  "Allergies" because none are recorded turns "nothing is written down here"
  into "there are none", which is the one substitution that can hurt someone.

  Nothing may be interpreted. No section ranks, flags, judges or concludes.

  The private diary — mood, journal, cycle, menopause — must never reach a page
  built to be printed and handed over.
"""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db import visit_pack as vp

PW = "pack-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    row = execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True)
    return c, dict(row)["id"]


def _appt(uid, date, title="Check-up", aid=None):
    aid = aid or new_id()
    execute("""INSERT INTO appointments (id, user_id, title, kind, date, created_at)
               VALUES (?,?,?,?,?,?)""",
            (aid, uid, title, "doctor", date, now_iso()), commit=True)
    return aid


def _med(uid, name, active=1, dosage="500", unit="mg"):
    mid = new_id()
    execute("""INSERT INTO medicines (id, user_id, name, dosage, unit, active, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (mid, uid, name, dosage, unit, active, now_iso()), commit=True)
    return mid


# ── The window ──────────────────────────────────────────────────────────────

def test_the_window_starts_at_the_previous_appointment(app):
    """"Since we last saw you" is the actual question, so the range has to be
    the gap between visits — not a fixed number of days."""
    c, uid = _uid(app, "pack1@medeasy.test")
    with user_context(uid):
        _appt(uid, "2026-05-10", "First")
        second = _appt(uid, "2026-08-01", "Second")
        pack = vp.build_pack(second)
    assert pack["window"]["since"] == "2026-05-10"
    assert pack["window"]["anchor"]["kind"] == "appointment"
    assert pack["window"]["anchor"]["title"] == "First"


def test_with_no_earlier_appointment_it_says_which_window_it_used(app):
    """A range on a printed page must never be a mystery."""
    c, uid = _uid(app, "pack2@medeasy.test")
    with user_context(uid):
        only = _appt(uid, "2026-08-01", "Only visit")
        pack = vp.build_pack(only)
    w = pack["window"]
    assert w["anchor"]["kind"] == "default_window"
    assert w["window_days"] == vp.DEFAULT_WINDOW_DAYS
    assert w["since"] == w["anchor"]["date"]


def test_the_window_runs_to_today_for_a_future_appointment(app):
    """A pack printed the night before a visit must include what was logged
    that morning — ending the window on the appointment date would drop it."""
    c, uid = _uid(app, "pack3@medeasy.test")
    with user_context(uid):
        _appt(uid, "2020-01-01", "Old")
        future = _appt(uid, "2099-12-31", "Future")
        pack = vp.build_pack(future)
    assert pack["window"]["until"] >= user_today()


def test_an_appointment_does_not_anchor_to_itself(app):
    c, uid = _uid(app, "pack4@medeasy.test")
    with user_context(uid):
        a = _appt(uid, "2026-08-01", "Same day A")
        b = _appt(uid, "2026-08-01", "Same day B")
        pack = vp.build_pack(b)
    # Both are on the same date, so neither is "earlier" — it must fall back
    # rather than pick its sibling and produce a zero-length window.
    assert pack["window"]["anchor"]["kind"] == "default_window"
    assert pack["window"]["since"] < "2026-08-01"


# ── Scoping ─────────────────────────────────────────────────────────────────

def test_another_users_appointment_is_not_readable(app):
    ca, ua = _uid(app, "pack5a@medeasy.test")
    cb, ub = _uid(app, "pack5b@medeasy.test")
    with user_context(ua):
        aid = _appt(ua, "2026-08-01", "Private")
    with user_context(ub):
        assert vp.build_pack(aid) is None
    assert cb.get("/api/visit-pack?appointment=" + aid).status_code == 404


def test_the_pack_only_contains_the_callers_data(app):
    ca, ua = _uid(app, "pack6a@medeasy.test")
    cb, ub = _uid(app, "pack6b@medeasy.test")
    with user_context(ua):
        _med(ua, "Someone-elses-medicine")
    with user_context(ub):
        aid = _appt(ub, "2026-08-01")
        pack = vp.build_pack(aid)
    names = [m["name"] for m in pack["medicines"]]
    assert "Someone-elses-medicine" not in names


# ── Absence is stated, never implied ────────────────────────────────────────

REQUIRED_SECTIONS = ["medicines", "changes", "allergies", "labs", "symptoms",
                     "vitals", "questions", "window", "not_captured"]


def test_every_section_is_present_even_when_empty(app):
    """The failure this prevents: a page with no Allergies heading reads as "no
    allergies" to someone skimming it in a consult."""
    c, uid = _uid(app, "pack7@medeasy.test")
    with user_context(uid):
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    for key in REQUIRED_SECTIONS:
        assert key in pack, f"an empty pack dropped {key}"
    assert pack["medicines"] == []
    assert pack["allergies"] == []
    assert pack["labs"]["items"] == []


def test_the_pack_says_what_it_cannot_see(app):
    c, uid = _uid(app, "pack8@medeasy.test")
    with user_context(uid):
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    note = pack["not_captured"].lower()
    assert "not logged" in note
    assert "does not mean it did not happen" in note


# ── Content rules ───────────────────────────────────────────────────────────

def test_only_active_medicines_are_listed(app):
    c, uid = _uid(app, "pack9@medeasy.test")
    with user_context(uid):
        _med(uid, "Current", active=1)
        _med(uid, "Stopped", active=0)
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    names = [m["name"] for m in pack["medicines"]]
    assert "Current" in names and "Stopped" not in names


def test_a_dose_is_printed_as_it_was_entered(app):
    """Restating a dose in a form the prescriber did not write is exactly the
    kind of helpfulness that causes a medication error."""
    c, uid = _uid(app, "pack10@medeasy.test")
    with user_context(uid):
        _med(uid, "Metformin", dosage="500", unit="mg")
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    med = [m for m in pack["medicines"] if m["name"] == "Metformin"][0]
    assert med["dose"] == "500 mg"


def test_allergies_are_never_windowed(app):
    """An allergy recorded years ago is still an allergy. This is the one
    section where dropping something old is dangerous."""
    c, uid = _uid(app, "pack11@medeasy.test")
    with user_context(uid):
        execute("""INSERT INTO allergies (id, user_id, allergen, reaction, severity, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), uid, "Penicillin", "Rash", "severe", "2001-01-01T00:00:00"),
                commit=True)
        _appt(uid, "2026-05-01", "Earlier")
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    assert [a["allergen"] for a in pack["allergies"]] == ["Penicillin"]


def test_symptoms_are_grouped_with_counts_and_never_averaged(app):
    """A count and a range are facts. An average of a self-assigned 1–10 scale
    reads as a measurement and is not one."""
    c, uid = _uid(app, "pack12@medeasy.test")
    with user_context(uid):
        for day, sev in [("2026-06-02", 4), ("2026-06-09", 8), ("2026-06-20", 3)]:
            execute("""INSERT INTO symptoms (id, user_id, name, severity, date_key, logged_at)
                       VALUES (?,?,?,?,?,?)""",
                    (new_id(), uid, "Headache", sev, day, day + "T09:00:00"), commit=True)
        _appt(uid, "2026-06-01", "Earlier")
        aid = _appt(uid, "2026-07-01")
        pack = vp.build_pack(aid)
    items = pack["symptoms"]["items"]
    assert len(items) == 1
    g = items[0]
    assert g["count"] == 3 and g["worst"] == 8
    assert g["first"] == "2026-06-02" and g["last"] == "2026-06-20"
    assert "average" not in g and "mean" not in g


def test_vitals_are_not_converted_on_the_server(app):
    """Units convert at the display layer everywhere else in the app. A printed
    page is the worst possible place to introduce a second conversion path."""
    c, uid = _uid(app, "pack13@medeasy.test")
    with user_context(uid):
        execute("""INSERT INTO vitals (id, user_id, date_key, type, value1, value2, unit, logged_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id(), uid, "2026-06-15", "blood_pressure", 128, 82, "mmHg",
                 "2026-06-15T08:00:00"), commit=True)
        _appt(uid, "2026-06-01", "Earlier")
        aid = _appt(uid, "2026-07-01")
        pack = vp.build_pack(aid)
    bp = [v for v in pack["vitals"] if v["type"] == "blood_pressure"][0]
    assert bp["readings"][0]["value1"] == 128
    assert bp["readings"][0]["value2"] == 82


def test_nothing_in_the_pack_interprets_anything(app):
    """No section may rank, flag, judge or conclude. The page reports."""
    c, uid = _uid(app, "pack14@medeasy.test")
    with user_context(uid):
        _med(uid, "Metformin")
        execute("""INSERT INTO lab_results (id, user_id, lab_key, name, value, unit,
                                            date_key, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id(), uid, "hba1c", "HbA1c", 9.4, "%", "2026-06-10", now_iso()),
                commit=True)
        _appt(uid, "2026-06-01", "Earlier")
        aid = _appt(uid, "2026-07-01")
        pack = vp.build_pack(aid)
    blob = str(pack).lower()
    for word in ("abnormal", "high risk", "concerning", "you should", "worrying",
                 "poorly controlled", "normal range", "warning", "recommend"):
        assert word not in blob, f"the pack interprets: {word!r}"


PRIVATE = ("mood", "journal", "cycle", "menopause", "pregnan", "thought")


def test_the_private_diary_never_reaches_the_pack(app):
    """This page is built to be printed and handed to someone. Mood and journal
    entries are walled off from caregivers elsewhere in the app for the same
    reason they must not be here."""
    c, uid = _uid(app, "pack15@medeasy.test")
    with user_context(uid):
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    keys = str(sorted(pack.keys())).lower()
    for word in PRIVATE:
        assert word not in keys, f"the pack has a {word} section"


# ── The route ───────────────────────────────────────────────────────────────

def test_the_route_falls_back_when_there_are_no_appointments(app):
    """Having nothing booked is a normal state, not an error — the page still
    has to show something useful."""
    c, uid = _uid(app, "pack16@medeasy.test")
    r = c.get("/api/visit-pack").get_json()
    assert r["success"] is True
    assert r.get("no_appointments") is True
    assert r["pack"]["appointment"] is None
    assert "medicines" in r["pack"]


def test_the_route_picks_the_soonest_upcoming_appointment(app):
    c, uid = _uid(app, "pack17@medeasy.test")
    with user_context(uid):
        _appt(uid, "2098-01-01", "Later")
        soon = _appt(uid, "2097-01-01", "Sooner")
    r = c.get("/api/visit-pack").get_json()
    assert r["pack"]["appointment"]["id"] == soon


def test_a_date_range_pack_needs_no_appointment(app):
    """Not every visit is booked through Arogo, and a walk-in still deserves
    the page."""
    c, uid = _uid(app, "pack18@medeasy.test")
    r = c.get("/api/visit-pack?since=2026-01-01&until=2026-06-30").get_json()
    assert r["success"] is True
    assert r["pack"]["appointment"] is None
    assert r["pack"]["window"]["since"] == "2026-01-01"
    assert r["pack"]["window"]["until"] == "2026-06-30"


def test_a_nonsense_date_range_does_not_crash_or_invent(app):
    c, uid = _uid(app, "pack19@medeasy.test")
    r = c.get("/api/visit-pack?since=not-a-date&until=13/45/9999").get_json()
    assert r["success"] is True
    w = r["pack"]["window"]
    assert len(w["since"]) == 10 and len(w["until"]) == 10


def test_a_backwards_date_range_is_straightened_not_silently_empty(app):
    """since > until matches nothing, and an empty page reads as "nothing
    happened" rather than "that range is impossible"."""
    c, uid = _uid(app, "pack19b@medeasy.test")
    r = c.get("/api/visit-pack?since=2026-06-30&until=2026-01-01").get_json()
    w = r["pack"]["window"]
    assert w["since"] == "2026-01-01" and w["until"] == "2026-06-30"


def test_the_appointment_list_puts_upcoming_first(app):
    c, uid = _uid(app, "pack20@medeasy.test")
    with user_context(uid):
        _appt(uid, "2020-01-01", "Long past")
        _appt(uid, "2097-06-01", "Coming up")
    items = c.get("/api/visit-pack/appointments").get_json()["appointments"]
    assert items[0]["title"] == "Coming up"
    assert items[0]["upcoming"] is True


def test_the_appointment_list_is_scoped_per_user(app):
    ca, ua = _uid(app, "pack21a@medeasy.test")
    cb, ub = _uid(app, "pack21b@medeasy.test")
    with user_context(ua):
        _appt(ua, "2097-01-01", "Mine")
    items = cb.get("/api/visit-pack/appointments").get_json()["appointments"]
    assert [i["title"] for i in items] == []


def test_the_pack_needs_a_signed_in_user(app):
    assert app.test_client().get("/api/visit-pack").status_code == 401


# ── It agrees with the reconciliation page ──────────────────────────────────

def test_changes_come_from_the_reconciliation_module_not_a_second_query(app):
    """Two surfaces answering "what changed" differently would be worse than
    either one being wrong, because there'd be no way to tell which to believe."""
    import inspect
    src = inspect.getsource(vp._changes)
    assert "changes_between" in src
    assert "medicine_events" not in src, "the pack re-derives changes itself"


def test_a_unit_with_no_number_is_not_printed_as_a_dose(app):
    """"Paracetamol mg" on a page a clinician reads looks like a transcription
    error. With no dosage recorded, the honest rendering is nothing at all."""
    c, uid = _uid(app, "pack22@medeasy.test")
    with user_context(uid):
        _med(uid, "Paracetamol", dosage="", unit="mg")
        _med(uid, "Metformin", dosage="500", unit="mg")
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    by_name = {m["name"]: m for m in pack["medicines"]}
    assert by_name["Paracetamol"]["dose"] == ""
    assert by_name["Metformin"]["dose"] == "500 mg"


def test_a_dose_with_no_unit_still_shows_the_number(app):
    """The number is the part that matters; a missing unit must not swallow it."""
    c, uid = _uid(app, "pack23@medeasy.test")
    with user_context(uid):
        _med(uid, "Something", dosage="2 tablets", unit="")
        aid = _appt(uid, "2026-08-01")
        pack = vp.build_pack(aid)
    assert pack["medicines"][0]["dose"] == "2 tablets"
