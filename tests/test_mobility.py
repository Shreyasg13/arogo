"""Falls, hearing and rehab — and mostly, what none of them is allowed to say.

These three features sit closer to clinical judgement than most of the app, and
each has one specific temptation:

  Falls invite a risk score. Fall-risk assessment is a validated instrument
  administered by someone trained; a number invented here would look exactly
  like one and mean nothing.

  Hearing invites reading an audiogram. That is a measurement taken with
  calibrated equipment, and interpreting it is an audiologist's job.

  Rehab invites telling someone whether to push on. Pain after exercise is the
  first thing a physiotherapist asks and the last thing an app should have an
  opinion about.

Most of what follows tests that none of that happens.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today
from db import falls as fl
from db import hearing as hr
from db import rehab as rb

PW = "mob-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,),
                           fetchone=True))["id"]


def _days_ago(n):
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=n)).isoformat()


# ════════════════════════════════════════════════════════════════════════════
# FALLS
# ════════════════════════════════════════════════════════════════════════════

def test_a_fall_is_recorded_as_entered(app):
    c, uid = _uid(app, "mob1@medeasy.test")
    with user_context(uid):
        f = fl.add_fall(fell_on="2026-08-01", time_of_day="night",
                        place="bathroom", what_happened="Slipped on a wet floor",
                        injured=1, injury="Bruised hip", got_up_alone=0)
    assert f["fell_on"] == "2026-08-01"
    assert f["place_label"] == "Bathroom"
    assert f["time_label"] == "Night"
    assert f["injured"] is True
    assert f["got_up_alone"] is False


def test_not_recorded_is_different_from_no(app):
    """Collapsing an unanswered question into "no" would turn every blank into
    "they got up on their own"."""
    c, uid = _uid(app, "mob2@medeasy.test")
    with user_context(uid):
        blank = fl.add_fall(fell_on="2026-08-01")
        said_no = fl.add_fall(fell_on="2026-08-02", got_up_alone=0)
        said_yes = fl.add_fall(fell_on="2026-08-03", got_up_alone=1)
    assert blank["got_up_alone"] is None
    assert said_no["got_up_alone"] is False
    assert said_yes["got_up_alone"] is True


def test_a_place_in_the_users_own_words_is_kept(app):
    """An unrecognised place is what the person actually typed, not "Other"."""
    c, uid = _uid(app, "mob3@medeasy.test")
    with user_context(uid):
        f = fl.add_fall(fell_on="2026-08-01", place="On the bus")
    assert f["place_label"] == "On the bus"


def test_a_missing_date_becomes_today_not_nothing(app):
    c, uid = _uid(app, "mob4@medeasy.test")
    with user_context(uid):
        f = fl.add_fall()
    assert f["fell_on"] == user_today()


def test_the_summary_never_produces_a_score(app):
    """The single most important assertion in this file."""
    c, uid = _uid(app, "mob5@medeasy.test")
    with user_context(uid):
        for i in range(4):
            fl.add_fall(fell_on=_days_ago(i * 10), place="stairs", injured=1)
        s = fl.summary()
    # The disclaimer is the one place these words are allowed, because there it
    # says the opposite. Checking the whole payload including it would pass or
    # fail on the wording of the denial rather than on the data.
    disclaimer = s.pop('not_a_score')
    assert 'does not rate fall risk' in disclaimer.lower()
    blob = str(s).lower()
    for word in ("risk", "score", "high", "moderate", "severe", "grade",
                 "likelihood", "probability", "you should", "recommend"):
        assert word not in blob, f"the fall summary produces a {word!r}"


def test_an_empty_summary_says_nothing_was_written_down(app):
    """"0 falls" reads as "you are not falling". The app only knows that
    nothing was recorded."""
    c, uid = _uid(app, "mob6@medeasy.test")
    with user_context(uid):
        s = fl.summary()
    assert s["has_any"] is False
    assert "not the same as no falls" in s["note"]


def test_the_summary_counts_by_place_and_time(app):
    c, uid = _uid(app, "mob7@medeasy.test")
    with user_context(uid):
        fl.add_fall(fell_on=_days_ago(1), place="bathroom", time_of_day="night")
        fl.add_fall(fell_on=_days_ago(2), place="bathroom", time_of_day="morning")
        fl.add_fall(fell_on=_days_ago(3), place="stairs", time_of_day="night")
        s = fl.summary()
    assert s["total"] == 3
    top = s["by_place"][0]
    assert top["label"] == "Bathroom" and top["count"] == 2


def test_the_summary_never_claims_a_cause(app):
    """Three falls in the bathroom is arithmetic. "Because of the bathroom" is
    a claim needing evidence this app does not have."""
    c, uid = _uid(app, "mob8@medeasy.test")
    with user_context(uid):
        for i in range(3):
            fl.add_fall(fell_on=_days_ago(i), place="bathroom")
        s = fl.summary()
    blob = str(s).lower()
    for word in ("because", "caused", "due to", "leads to", "responsible for"):
        assert word not in blob, f"the summary claims a cause: {word!r}"


def test_falls_are_scoped_per_user(app):
    ca, ua = _uid(app, "mob9a@medeasy.test")
    cb, ub = _uid(app, "mob9b@medeasy.test")
    with user_context(ua):
        fl.add_fall(fell_on="2026-08-01", place="stairs")
    with user_context(ub):
        assert fl.list_falls() == []


def test_deleting_a_fall_sends_it_to_the_trash(app):
    c, uid = _uid(app, "mob10@medeasy.test")
    with user_context(uid):
        f = fl.add_fall(fell_on="2026-08-01", place="garden")
        assert fl.delete_fall(f["id"]) is True
        assert fl.get_fall(f["id"]) is None
        from db.trash import list_trash
        assert any(i["kind"] == "Fall" for i in list_trash())


def test_the_fall_routes_work_end_to_end(app):
    c, uid = _uid(app, "mob11@medeasy.test")
    r = c.post("/api/falls", json={"fell_on": "2026-08-01", "place": "kitchen",
                                   "injured": True, "injury": "Cut hand"})
    assert r.status_code == 200 and r.get_json()["success"] is True
    fid = r.get_json()["fall"]["id"]
    assert c.get("/api/falls").get_json()["falls"][0]["id"] == fid
    assert c.get("/api/falls/summary").get_json()["total"] == 1
    assert c.patch(f"/api/falls/{fid}", json={"place": "garden"}).get_json()["fall"]["place_label"] == "Garden or yard"
    assert c.delete(f"/api/falls/{fid}").get_json()["success"] is True


def test_another_users_fall_is_not_editable(app):
    ca, ua = _uid(app, "mob12a@medeasy.test")
    cb, ub = _uid(app, "mob12b@medeasy.test")
    fid = ca.post("/api/falls", json={"fell_on": "2026-08-01"}).get_json()["fall"]["id"]
    assert cb.patch(f"/api/falls/{fid}", json={"place": "stairs"}).status_code == 404
    assert cb.delete(f"/api/falls/{fid}").status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# HEARING
# ════════════════════════════════════════════════════════════════════════════

def test_a_hearing_test_stores_the_finding_as_reported(app):
    c, uid = _uid(app, "mob13@medeasy.test")
    with user_context(uid):
        r = hr.add_record(kind="test", record_date="2026-06-01",
                          provider="City Audiology",
                          left_ear="Mild loss at high frequencies",
                          right_ear="Normal",
                          finding="Recommended a review in two years")
    assert r["left_ear"] == "Mild loss at high frequencies"
    assert r["finding"].startswith("Recommended")


def test_the_app_never_interprets_a_hearing_result(app):
    c, uid = _uid(app, "mob14@medeasy.test")
    with user_context(uid):
        hr.add_record(kind="test", record_date="2026-06-01",
                      left_ear="40dB at 4kHz")
        o = hr.overview()
    blob = str(o).lower()
    for word in ("severity", "moderate loss", "you have", "diagnosed",
                 "normal hearing", "impaired"):
        assert word not in blob, f"the overview interprets: {word!r}"


def test_an_aid_keeps_the_boring_details(app):
    """Battery type and service date are the whole point — they are what nobody
    can find at the moment the aid stops working."""
    c, uid = _uid(app, "mob15@medeasy.test")
    with user_context(uid):
        r = hr.add_record(kind="aid", record_date="2026-01-15",
                          device="Phonak Audeo", battery="size 312",
                          serviced_on="2026-05-01", next_check="2026-11-01")
    assert r["device"] == "Phonak Audeo"
    assert r["battery"] == "size 312"
    assert r["serviced_on"] == "2026-05-01"


def test_a_bad_date_is_dropped_rather_than_stored(app):
    c, uid = _uid(app, "mob16@medeasy.test")
    with user_context(uid):
        r = hr.add_record(kind="aid", record_date="2026-01-15",
                          serviced_on="not-a-date", next_check="31/02/2026")
    assert r["serviced_on"] == ""
    assert r["next_check"] == ""


def test_overview_reports_only_dates_the_user_entered(app):
    """Nothing here invents a recommended interval — how often a hearing test is
    worth repeating depends on the person."""
    c, uid = _uid(app, "mob17@medeasy.test")
    with user_context(uid):
        hr.add_record(kind="test", record_date="2026-06-01")
        o = hr.overview()
    assert o["due"] == [], "an interval was invented for a record with no next check"


def test_overview_marks_a_passed_date_overdue(app):
    c, uid = _uid(app, "mob18@medeasy.test")
    with user_context(uid):
        hr.add_record(kind="aid", record_date="2020-01-01", device="Old aid",
                      next_check="2020-06-01")
        o = hr.overview()
    assert o["due"] and o["due"][0].get("overdue") is True


def test_hearing_is_scoped_and_trashable(app):
    ca, ua = _uid(app, "mob19a@medeasy.test")
    cb, ub = _uid(app, "mob19b@medeasy.test")
    with user_context(ua):
        rec = hr.add_record(kind="test", record_date="2026-06-01")
    with user_context(ub):
        assert hr.list_records() == []
        assert hr.get_record(rec["id"]) is None
    with user_context(ua):
        assert hr.delete_record(rec["id"]) is True


def test_the_hearing_routes_work_end_to_end(app):
    c, uid = _uid(app, "mob20@medeasy.test")
    r = c.post("/api/hearing", json={"kind": "aid", "record_date": "2026-02-01",
                                     "device": "Oticon", "battery": "rechargeable"})
    rid = r.get_json()["record"]["id"]
    assert c.get("/api/hearing").get_json()["records"][0]["device"] == "Oticon"
    assert c.get("/api/hearing/overview").get_json()["counts"]["aids"] == 1
    assert c.patch(f"/api/hearing/{rid}", json={"battery": "size 13"}).get_json()["record"]["battery"] == "size 13"
    assert c.delete(f"/api/hearing/{rid}").get_json()["success"] is True


# ════════════════════════════════════════════════════════════════════════════
# REHAB
# ════════════════════════════════════════════════════════════════════════════

def test_a_plan_is_whatever_the_physio_gave(app):
    c, uid = _uid(app, "mob21@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Knee exercises", times_per_day=3,
                        prescribed_by="Ms Rao", started_on="2026-08-01",
                        instructions="10 straight-leg raises each side")
    assert p["times_per_day"] == 3
    assert "straight-leg raises" in p["instructions"]


def test_a_plan_needs_a_name(app):
    c, uid = _uid(app, "mob22@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            rb.add_plan(name="   ")


def test_a_silly_frequency_is_clamped_not_stored(app):
    """A typo must not make every adherence figure meaningless."""
    c, uid = _uid(app, "mob23@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Typo", times_per_day=500)
        assert p["times_per_day"] == rb.MAX_TIMES_PER_DAY
        p2 = rb.add_plan(name="Zero", times_per_day=0)
        assert p2["times_per_day"] == 1


def test_adherence_is_done_over_scheduled_with_the_window_stated(app):
    c, uid = _uid(app, "mob24@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Daily", times_per_day=1, started_on=_days_ago(6))
        for i in range(4):
            rb.log_session(p["id"], date_key=_days_ago(i))
        a = rb.adherence(p["id"], days=7)
    assert a["scheduled"] == 7 and a["done"] == 4
    assert a["pct"] == 57
    assert a["from"] and a["to"], "the window must be stated"


def test_adherence_never_reports_a_target(app):
    """"You are at 60%" is a fact. "You should be at 90%" is not ours."""
    c, uid = _uid(app, "mob25@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Plan", started_on=_days_ago(3))
        rb.log_session(p["id"])
        a = rb.adherence(p["id"])
    blob = str(a).lower()
    for word in ("target", "goal", "should", "expected", "behind", "on track"):
        assert word not in blob, f"adherence reports a {word!r}"


def test_the_window_is_clipped_to_the_plan(app):
    """Counting days before a plan started as missed sessions would make every
    new plan look abandoned on day one."""
    c, uid = _uid(app, "mob26@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Started today", times_per_day=2,
                        started_on=user_today())
        rb.log_session(p["id"])
        rb.log_session(p["id"])
        a = rb.adherence(p["id"], days=30)
    assert a["scheduled"] == 2, "days before the plan started were counted"
    assert a["pct"] == 100


def test_a_finished_course_is_not_counted_past_its_end(app):
    c, uid = _uid(app, "mob27@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Six weeks", times_per_day=1,
                        started_on=_days_ago(10), until_date=_days_ago(5))
        for i in range(5, 11):
            rb.log_session(p["id"], date_key=_days_ago(i))
        a = rb.adherence(p["id"], days=14)
    assert a["to"] == _days_ago(5), "the window ran past the end of the plan"
    assert a["pct"] == 100


def test_extra_sessions_do_not_exceed_one_hundred(app):
    """130% reads as a data error, not as enthusiasm."""
    c, uid = _uid(app, "mob28@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Keen", times_per_day=1, started_on=user_today())
        for _ in range(4):
            rb.log_session(p["id"])
        a = rb.adherence(p["id"])
    assert a["pct"] == 100


def test_a_window_with_nothing_scheduled_reports_none_not_a_hundred(app):
    """Dividing by zero into a reassuring 100% is the worst available answer."""
    c, uid = _uid(app, "mob29@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Future", started_on="2099-01-01")
        a = rb.adherence(p["id"])
    assert a["pct"] is None
    assert a["scheduled"] == 0


def test_pain_is_recorded_and_never_judged(app):
    c, uid = _uid(app, "mob30@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Shoulder", started_on=_days_ago(3))
        rb.log_session(p["id"], date_key=_days_ago(2), pain_after=7)
        rb.log_session(p["id"], date_key=_days_ago(0), pain_after=3)
        trail = rb.pain_trail(p["id"])
    assert [x["pain"] for x in trail] == [7, 3]
    blob = str(trail).lower()
    for word in ("improving", "worse", "better", "trend", "direction", "good"):
        assert word not in blob, f"the pain trail claims {word!r}"


def test_pain_is_clamped_to_its_scale(app):
    c, uid = _uid(app, "mob31@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Clamp", started_on=user_today())
        assert rb.log_session(p["id"], pain_after=99)["pain_after"] == 10
        assert rb.log_session(p["id"], pain_after=-4)["pain_after"] == 0
        assert rb.log_session(p["id"], pain_after="nonsense")["pain_after"] is None


def test_a_session_without_pain_is_still_a_session(app):
    """Making the number required would turn a log into an interrogation."""
    c, uid = _uid(app, "mob32@medeasy.test")
    with user_context(uid):
        p = rb.add_plan(name="Optional", started_on=user_today())
        s = rb.log_session(p["id"])
        assert s["pain_after"] is None
        assert rb.adherence(p["id"])["done"] == 1


def test_a_session_cannot_be_logged_against_someone_elses_plan(app):
    ca, ua = _uid(app, "mob33a@medeasy.test")
    cb, ub = _uid(app, "mob33b@medeasy.test")
    with user_context(ua):
        p = rb.add_plan(name="Mine", started_on=user_today())
    with user_context(ub):
        with pytest.raises(ValueError):
            rb.log_session(p["id"])
    assert cb.post(f"/api/rehab/{p['id']}/log", json={}).status_code == 404


def test_the_rehab_routes_work_end_to_end(app):
    c, uid = _uid(app, "mob34@medeasy.test")
    pid = c.post("/api/rehab", json={"name": "Back", "times_per_day": 2,
                                     "started_on": user_today()}).get_json()["plan"]["id"]
    assert c.post(f"/api/rehab/{pid}/log", json={"pain_after": 4}).get_json()["success"] is True
    got = c.get("/api/rehab").get_json()["plans"][0]
    assert got["adherence"]["done"] == 1
    s = c.get(f"/api/rehab/{pid}/sessions").get_json()
    assert len(s["sessions"]) == 1 and s["pain"][0]["pain"] == 4
    lid = s["sessions"][0]["id"]
    assert c.delete(f"/api/rehab/session/{lid}").get_json()["success"] is True
    assert c.get(f"/api/rehab/{pid}/sessions").get_json()["sessions"] == []
    assert c.delete(f"/api/rehab/{pid}").get_json()["success"] is True


def test_another_users_session_cannot_be_deleted(app):
    ca, ua = _uid(app, "mob35a@medeasy.test")
    cb, ub = _uid(app, "mob35b@medeasy.test")
    pid = ca.post("/api/rehab", json={"name": "Mine", "started_on": user_today()}).get_json()["plan"]["id"]
    ca.post(f"/api/rehab/{pid}/log", json={})
    lid = ca.get(f"/api/rehab/{pid}/sessions").get_json()["sessions"][0]["id"]
    assert cb.delete(f"/api/rehab/session/{lid}").status_code == 404


# ── All three, together ─────────────────────────────────────────────────────

def test_none_of_the_three_gives_advice(app):
    """No "install a grab rail", no "review your medicines", no "keep going".
    All may be excellent ideas and none is this app's to give."""
    c, uid = _uid(app, "mob36@medeasy.test")
    with user_context(uid):
        fl.add_fall(fell_on=user_today(), place="stairs", injured=1)
        hr.add_record(kind="test", record_date=user_today())
        p = rb.add_plan(name="Plan", started_on=user_today())
        rb.log_session(p["id"], pain_after=8)
        blob = " ".join(str(x) for x in
                        (fl.summary(), hr.overview(), rb.adherence(p["id"]),
                         rb.pain_trail(p["id"]))).lower()
    for advice in ("you should", "we recommend", "try to", "make sure you",
                   "consider ", "it is important that you", "keep going",
                   "stop doing", "talk to your doctor about"):
        assert advice not in blob, f"advice given: {advice!r}"


def test_all_three_require_a_signed_in_user(app):
    anon = app.test_client()
    for path in ("/api/falls", "/api/falls/summary", "/api/falls/meta",
                 "/api/hearing", "/api/hearing/overview", "/api/rehab"):
        assert anon.get(path).status_code == 401, path


def test_none_of_the_three_is_walled_from_a_caregiver():
    """Falls, hearing aids and physiotherapy are exactly what a caregiver is
    there to help with. The private wall is for mood, journal and cycle —
    subjects where being managed is the problem rather than the point."""
    from auth import _is_private_while_acting
    for path in ("/api/falls", "/api/hearing", "/api/rehab"):
        assert not _is_private_while_acting(path), path
