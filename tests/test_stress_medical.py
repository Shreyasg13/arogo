"""
tests/test_stress_medical.py — QA stress suite for the MEDICINES + MEDICAL domain.

Scope: /api/medicines* (CRUD, dose log, adherence, streaks, stock),
/api/upload + /api/reports* + /uploads/* (medical documents),
/api/symptoms*, /api/vitals*, /api/emergency.

Two kinds of tests:
  1. Hard guarantees (isolation, ownership, upload sanitization) — assert
     strictly; a failure here is a regression.
  2. Known bugs found during the audit — marked @BUG (non-strict xfail).
     Each asserts the DESIRED behaviour, so today it registers as xfail
     and flips to XPASS once the bug is fixed. Fix list:
       - insert_medicine / log_vital / log_symptom raise KeyError/ValueError
         on malformed payloads -> HTTP 500 instead of 400
       - `times` accepted as any JSON type: a string yields one phantom
         dose per character; a number 500s /api/medicines/today
       - int(request.args['days']) unguarded on adherence/symptoms routes
       - /api/medicines/streaks?days=0 -> IndexError (empty date_range)
       - get_adherence_stats ignores start_date: a medicine added today
         with every dose taken reports ~3% over the 30-day window
       - get_today_doses ignores end_date: finished courses still demand
         doses every day
       - /api/upload: a fully non-ASCII filename ("рецепт.pdf") makes
         secure_filename() return "pdf" -> IndexError 500 AFTER the file
         was already written to disk (orphan file, no DB row)
       - stock accepts negative pill counts and non-numeric input 500s

Run:  pytest tests/test_stress_medical.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import datetime
import io
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
import auth as auth_module
from db.core import init_db, execute
from app import create_app

TODAY     = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
PW        = "stress-pw-12345"

# Desired behaviour asserted; currently fails (see module docstring).
BUG = pytest.mark.xfail(strict=False)

MED = {"name": "Metformin", "dosage": "500", "unit": "mg",
       "frequency": "twice_daily", "times": ["08:00", "20:00"]}


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    application = create_app()
    application.config["TESTING"] = True
    # Let the JSON 500 handler answer instead of re-raising into the test —
    # several tests assert on the HTTP status of crashing endpoints.
    application.config["PROPAGATE_EXCEPTIONS"] = False
    # Keep stress-test uploads out of the repo's real uploads/ folder.
    application.config["UPLOAD_FOLDER"] = str(tmp_path_factory.mktemp("uploads"))
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


@pytest.fixture(autouse=True)
def clean_domain(app):
    yield
    for t in ["medicines", "dose_logs", "reports", "symptoms", "vitals",
              "emergency_info", "notification_log"]:
        try:
            execute("DELETE FROM %s" % t, commit=True)
        except Exception:
            pass


def _authed(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201)
    return c


@pytest.fixture(scope="module")
def alice(app):
    return _authed(app, "stress.alice@medeasy.test")


@pytest.fixture(scope="module")
def bob(app):
    return _authed(app, "stress.bob@medeasy.test")


# ── Helpers ────────────────────────────────────────────────────────────────────

def mk_med(client, **over):
    body = dict(MED)
    body.update(over)
    r = client.post("/api/medicines", json=body)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["medicine"]


def upload(client, filename, content=b"%PDF-1.4 stress", **form):
    data = {"file": (io.BytesIO(content), filename)}
    data.update(form)
    return client.post("/api/upload", data=data,
                       content_type="multipart/form-data")


def dose_log_count():
    return execute("SELECT COUNT(*) AS n FROM dose_logs", fetchone=True)["n"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. MEDICINES — malformed / hostile input
# ══════════════════════════════════════════════════════════════════════════════

class TestMedicineInputValidation:
    def test_missing_name_is_client_error(self, alice):
        """FIXED: a missing name is rejected with 400, not a KeyError 500."""
        r = alice.post("/api/medicines", json={})
        assert 400 <= r.status_code < 500

    def test_missing_dosage_is_accepted_as_optional(self, alice):
        """Dosage is optional (schema DEFAULT ''): a name-only medicine is
        accepted, not rejected — the reminder still works without a dose label."""
        r = alice.post("/api/medicines", json={"name": "NoDose"})
        assert r.status_code == 200
        assert r.get_json()["medicine"]["name"] == "NoDose"

    def test_times_as_string_no_phantom_doses(self, alice):
        """times='08:00' (string, not list) is stored verbatim; the today
        view then iterates the string CHARACTER BY CHARACTER and shows five
        phantom doses ('0','8',':','0','0'). Want: 1 dose or a 400."""
        r = alice.post("/api/medicines",
                       json={"name": "StrTimes", "dosage": "1", "times": "08:00"})
        assert r.status_code in (200, 400)
        doses = alice.get("/api/medicines/today").get_json()
        assert len(doses) <= 1

    def test_times_as_number_does_not_break_today_view(self, alice):
        """times=800 -> TypeError in get_today_doses -> the WHOLE today
        view (all medicines) 500s until the row is deleted."""
        alice.post("/api/medicines",
                   json={"name": "IntTimes", "dosage": "1", "times": 800})
        r = alice.get("/api/medicines/today")
        assert r.status_code == 200

    def test_unicode_and_html_name_round_trips(self, alice):
        """API must store hostile names verbatim (frontend escapes via
        escHtml); no server-side mangling, no crash."""
        evil = "पैरासिटामोल <script>alert('x')</script> 💊 'quote\" &amp;"
        med = mk_med(alice, name=evil)
        listed = alice.get("/api/medicines").get_json()
        assert any(m["name"] == evil for m in listed)
        assert med["name"] == evil

    def test_empty_times_list_defaults_to_trackable_dose(self, alice):
        """FIXED product gap: times=[] used to create an untracked ghost
        medicine. _clean_times now falls back to a single 08:00 dose so the
        medicine is visible on the timeline and counts toward adherence."""
        mk_med(alice, name="Ghost", times=[])
        doses = alice.get("/api/medicines/today").get_json()
        assert len(doses) == 1
        assert doses[0]["time"] == "08:00"

    def test_many_time_slots_capped(self, alice):
        """FIXED: the schedule is de-duped and capped at 24 distinct slots so a
        pathological payload can't bloat the today view."""
        times = ["%02d:%02d" % (h, m) for h in range(10) for m in (0, 10, 20, 30, 40)]
        mk_med(alice, name="Many", times=times)
        r = alice.get("/api/medicines/today")
        assert r.status_code == 200
        assert len(r.get_json()) == 24


# ══════════════════════════════════════════════════════════════════════════════
# 2. DOSE LOGGING — contract + isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestDoseLogging:
    def test_double_log_upserts_single_row(self, alice):
        mid = mk_med(alice)["id"]
        for _ in range(3):
            alice.post("/api/medicines/%s/log" % mid,
                       json={"date": TODAY, "time": "08:00", "taken": True})
        assert dose_log_count() == 1

    def test_untake_dose_via_taken_false(self, alice):
        mid = mk_med(alice)["id"]
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": True})
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": False})
        doses = alice.get("/api/medicines/today").get_json()
        slot = next(d for d in doses if d["time"] == "08:00")
        assert slot["taken"] is False

    def test_cannot_log_dose_on_other_users_medicine(self, alice, bob):
        mid = mk_med(alice)["id"]
        r = bob.post("/api/medicines/%s/log" % mid,
                     json={"date": TODAY, "time": "08:00", "taken": True})
        # FIXED: logging against a medicine you don't own is now an honest 404,
        # and still a no-op (no row written).
        assert r.status_code == 404
        assert dose_log_count() == 0

    def test_malformed_time_is_now_rejected(self, alice):
        """RESOLVED (was a documented API contract smell): logging time='99:99'
        used to return success and write a row no view would ever surface. The
        /log route now validates a HH:MM slot server-side and rejects a
        malformed time with 400, so junk slots can't accrete and skew the
        responsiveness / skip-reason scans. A missing or empty time stays
        lenient (it's inert in the math — see test_api's 'scheduled'-key call)."""
        mid = mk_med(alice)["id"]
        r = alice.post("/api/medicines/%s/log" % mid,
                       json={"date": TODAY, "time": "99:99", "taken": True})
        assert r.status_code == 400
        doses = alice.get("/api/medicines/today").get_json()
        assert all(not d["taken"] for d in doses)   # nothing written

    def test_taking_dose_decrements_pill_stock(self, alice):
        """FIXED: taking a dose now consumes stock (pills_per_dose), un-taking
        restores it, and a double-log doesn't double-count — so 'days left'
        tracks reality instead of drifting up."""
        mid = mk_med(alice)["id"]
        alice.post("/api/medicines/%s/stock" % mid,
                   json={"pill_count": 30, "pills_per_dose": 2, "refill_threshold": 7})

        def stock():
            return next(m for m in alice.get("/api/medicines").get_json()
                        if m["id"] == mid)["pill_count"]

        # Take -> consume 2 (pills_per_dose)
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": True})
        assert stock() == 28
        # Re-take the same slot -> no double count (idempotent on the transition)
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": True})
        assert stock() == 28
        # Un-take -> restore 2
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": False})
        assert stock() == 30

    def test_today_doses_follow_the_users_timezone_not_the_servers(self, alice):
        """The app and service worker write dose rows keyed to the DEVICE's
        local day. If the server reads them back on its own day, the two
        disagree at the edges: a user in IST taps "✓ Taken" at 00:30, the row
        lands on their today, the server still sees the dose unlogged — and
        escalates it to their family as missed. Same day, both sides."""
        import datetime as _dt
        from db.core import user_today, today_iso

        # Kiritimati is UTC+14: its "today" is ahead of any server's for most
        # of the day, so this fails loudly if we ever read the server's date.
        alice.post("/api/food/profile", json={"timezone": "Pacific/Kiritimati"})
        their_today = _dt.datetime.now(
            __import__("zoneinfo").ZoneInfo("Pacific/Kiritimati")).date().isoformat()

        mid = mk_med(alice, times=["08:00"])["id"]
        # Log the dose on THEIR day, exactly as the service worker would.
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": their_today, "time": "08:00", "taken": True})

        doses = [d for d in alice.get("/api/medicines/today").get_json()
                 if d["med_id"] == mid]
        assert doses, "the medicine should appear in today's doses"
        assert doses[0]["taken"], (
            "a dose logged on the user's own day reads back as untaken — "
            "their family would be alerted about a dose they took")

    def test_un_taking_a_dose_never_invents_pills(self, alice):
        """Stock must be conservative: an un-take gives back exactly what the
        take removed. The old arithmetic floored the consume side at 0 but
        restored unconditionally, so a user who was out of pills could tap
        Taken then correct it and end up with a pill that never existed —
        and inflated stock silently suppresses the low-stock refill nudge."""
        mid = mk_med(alice)["id"]
        alice.post("/api/medicines/%s/stock" % mid,
                   json={"pill_count": 0, "pills_per_dose": 1, "refill_threshold": 7})

        def stock():
            return next(m for m in alice.get("/api/medicines").get_json()
                        if m["id"] == mid)["pill_count"]

        # Out of pills: taking consumes nothing, so un-taking restores nothing.
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": True})
        assert stock() == 0
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": False})
        assert stock() == 0, "un-taking a dose at zero stock invented a pill"

    def test_take_untake_round_trip_is_conservative(self, alice):
        """One pill, two scheduled doses: taking both can only consume the one
        pill that exists, so un-taking both must return to exactly one — not
        two. The floor made the operation non-reversible and inflated stock."""
        mid = mk_med(alice, times=["08:00", "20:00"])["id"]
        alice.post("/api/medicines/%s/stock" % mid,
                   json={"pill_count": 1, "pills_per_dose": 1, "refill_threshold": 7})

        def stock():
            return next(m for m in alice.get("/api/medicines").get_json()
                        if m["id"] == mid)["pill_count"]

        for t in ("08:00", "20:00"):
            alice.post("/api/medicines/%s/log" % mid,
                       json={"date": TODAY, "time": t, "taken": True})
        assert stock() == 0
        for t in ("08:00", "20:00"):
            alice.post("/api/medicines/%s/log" % mid,
                       json={"date": TODAY, "time": t, "taken": False})
        assert stock() == 1, "take/un-take round trip inflated the pill count"

    def test_taking_dose_without_stock_tracking_is_noop(self, alice):
        """A medicine that tracks no stock (pill_count NULL) must not error or
        materialise a phantom count when a dose is taken."""
        mid = mk_med(alice)["id"]
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": True})
        med = next(m for m in alice.get("/api/medicines").get_json()
                   if m["id"] == mid)
        assert med["pill_count"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. ADHERENCE + STREAKS — query params and date-range math
# ══════════════════════════════════════════════════════════════════════════════

class TestAdherenceAndStreaks:
    def test_adherence_days_param_non_numeric(self, alice):
        """FIXED: a non-numeric ?days is coerced to the default (30) instead of
        crashing on int() — the endpoint returns a clean 200."""
        r = alice.get("/api/medicines/adherence?days=abc")
        assert r.status_code == 200

    def test_adherence_negative_days_is_sane(self, alice):
        mk_med(alice)
        r = alice.get("/api/medicines/adherence?days=-5")
        assert r.status_code == 200
        assert r.get_json()["total"] == 0

    def test_streaks_days_zero_does_not_crash(self, alice):
        """?days=0 with >=1 active medicine -> empty date_range ->
        date_range[0] IndexError -> 500."""
        mk_med(alice)
        r = alice.get("/api/medicines/streaks?days=0")
        assert r.status_code == 200

    def test_new_medicine_not_penalized_for_days_before_it_existed(self, alice):
        """get_adherence_stats ignores start_date: a medicine created today
        with today's dose taken reports 1/30 = 3.3%, not 100%. Demoralizing
        and wrong — the number the dashboard shows a brand-new user."""
        mid = mk_med(alice, times=["08:00"], frequency="once_daily")["id"]
        alice.post("/api/medicines/%s/log" % mid,
                   json={"date": TODAY, "time": "08:00", "taken": True})
        stats = alice.get("/api/medicines/adherence?days=30").get_json()
        assert stats["pct"] == 100.0

    def test_finished_course_not_in_today_view(self, alice):
        """end_date is stored but never checked: a course that ended in
        2020 still demands doses today (and drags adherence down forever
        unless the user remembers to pause it manually)."""
        mk_med(alice, name="Expired", end_date="2020-01-01")
        doses = alice.get("/api/medicines/today").get_json()
        assert all(d["med_name"] != "Expired" for d in doses)

    def test_adherence_route_registered_once(self, app, alice):
        """RESOLVED (2026-08 route-dedup): the dead wellness duplicate of GET
        /api/medicines/adherence (which returned a different {'medicines': [...]}
        shape) was removed. Now a single registration serves the stats dict."""
        rules = [r for r in app.url_map.iter_rules()
                 if str(r) == "/api/medicines/adherence"]
        assert len(rules) == 1
        d = alice.get("/api/medicines/adherence").get_json()
        assert set(d.keys()) == {"total", "taken", "pct"}


# ══════════════════════════════════════════════════════════════════════════════
# 4. PILL STOCK
# ══════════════════════════════════════════════════════════════════════════════

class TestStock:
    def test_non_numeric_pill_count_coerced(self, alice):
        """FIXED: a non-numeric pill_count is coerced to 0 (never a 500)."""
        mid = mk_med(alice)["id"]
        r = alice.post("/api/medicines/%s/stock" % mid, json={"pill_count": "lots"})
        assert r.status_code == 200
        assert r.get_json()["medicine"]["pill_count"] == 0

    def test_negative_pill_count_rejected_or_clamped(self, alice):
        """-50 pills is accepted and low-stock reports days_left = -50.0."""
        mid = mk_med(alice)["id"]
        r = alice.post("/api/medicines/%s/stock" % mid, json={"pill_count": -50})
        if r.status_code == 200:
            med = next(m for m in alice.get("/api/medicines").get_json()
                       if m["id"] == mid)
            assert (med["pill_count"] or 0) >= 0
        else:
            assert 400 <= r.status_code < 500

    def test_zero_pills_per_dose_does_not_divide_by_zero(self, alice):
        mid = mk_med(alice)["id"]
        alice.post("/api/medicines/%s/stock" % mid,
                   json={"pill_count": 10, "pills_per_dose": 0})
        r = alice.get("/api/medicines/low-stock")
        assert r.status_code == 200

    def test_cannot_set_stock_on_other_users_medicine(self, alice, bob):
        mid = mk_med(bob, name="BobsMed")["id"]
        r = alice.post("/api/medicines/%s/stock" % mid, json={"pill_count": 1})
        assert r.status_code == 200          # responds success (smell) but…
        med = next(m for m in bob.get("/api/medicines").get_json()
                   if m["id"] == mid)
        assert med["pill_count"] is None     # …must not have changed Bob's row


# ══════════════════════════════════════════════════════════════════════════════
# 5. MEDICAL REPORTS — upload hardening + ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestReportUploads:
    def test_upload_list_download_roundtrip(self, alice, app):
        r = upload(alice, "blood_test.pdf", report_type="Blood Test",
                   patient_name="Alice", severity="attention")
        assert r.status_code == 200
        rep = r.get_json()["report"]
        assert rep["file_ext"] == "pdf"
        assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], rep["filename"]))
        dl = alice.get("/uploads/%s" % rep["filename"])
        assert dl.status_code == 200
        assert dl.data == b"%PDF-1.4 stress"

    def test_disallowed_extension_rejected(self, alice):
        assert upload(alice, "malware.exe").status_code == 400

    def test_double_extension_rejected(self, alice):
        assert upload(alice, "report.pdf.exe").status_code == 400

    def test_no_file_field_rejected(self, alice):
        r = alice.post("/api/upload", data={}, content_type="multipart/form-data")
        assert r.status_code == 400

    def test_path_traversal_is_neutralized(self, alice, app):
        r = upload(alice, "../../evil.pdf")
        assert r.status_code == 200
        stored = r.get_json()["report"]["filename"]
        assert ".." not in stored and "/" not in stored and "\\" not in stored
        assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], stored))
        # nothing escaped the upload folder
        assert not os.path.exists(os.path.join(ROOT, "evil.pdf"))

    def test_fully_non_ascii_filename(self, alice, app):
        """secure_filename('рецепт.pdf') strips every char to 'pdf' (no dot);
        rsplit('.')[1] then IndexErrors -> 500 — AFTER f.save() already ran,
        leaving an orphaned file on disk with no DB row pointing at it."""
        before = set(os.listdir(app.config["UPLOAD_FOLDER"]))
        r = upload(alice, u"рецепт.pdf")
        assert r.status_code in (200, 400)
        if r.status_code == 400:
            new_files = set(os.listdir(app.config["UPLOAD_FOLDER"])) - before
            assert not new_files, "rejected upload must not leave files behind"

    def test_oversized_upload_rejected(self, alice):
        blob = b"x" * (16 * 1024 * 1024 + 1024)   # MAX_CONTENT_LENGTH is 16 MB
        assert upload(alice, "huge.pdf", content=blob).status_code == 413

    def test_cross_user_download_blocked(self, alice, bob):
        rep = upload(alice, "private.pdf").get_json()["report"]
        assert bob.get("/uploads/%s" % rep["filename"]).status_code == 404
        assert alice.get("/uploads/%s" % rep["filename"]).status_code == 200

    def test_cross_user_delete_blocked_and_file_survives(self, alice, bob, app):
        rep = upload(alice, "keep.pdf").get_json()["report"]
        r = bob.delete("/api/reports/%s" % rep["id"])
        assert r.status_code == 404
        assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], rep["filename"]))
        assert any(x["id"] == rep["id"] for x in alice.get("/api/reports").get_json())

    def test_deleting_a_report_keeps_its_file_until_the_record_is_purged(self, alice, app):
        """Deleting a report used to erase its file at once. Records are now
        recoverable for thirty days, and restoring one that points at a file
        already deleted would be worse than not restoring it — so the trash owns
        the file and removes it when the entry is purged.

        The disk still has to come back to zero: a "deleted" scan that lives on
        the server forever is the failure this replaced, not an improvement."""
        rep = upload(alice, "gone.pdf").get_json()["report"]
        path = os.path.join(app.config["UPLOAD_FOLDER"], rep["filename"])
        assert os.path.exists(path)

        assert alice.delete("/api/reports/%s" % rep["id"]).status_code == 200
        assert os.path.exists(path), "the file must survive while the record can be restored"

        item = next(i for i in alice.get("/api/trash").get_json()["items"]
                    if i["kind"] == "Medical record")
        assert alice.delete("/api/trash/%s" % item["id"]).status_code == 200
        assert not os.path.exists(path), "purging the record must take its file"

    def test_report_search_special_chars_safe(self, alice):
        upload(alice, "notes.txt", report_type="General",
               patient_name="O'Brien %_")
        r = alice.get("/api/reports?search=O'Brien %25_")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 6. SYMPTOMS / VITALS / EMERGENCY CARD
# ══════════════════════════════════════════════════════════════════════════════

class TestMedicalRecords:
    def test_symptom_missing_name_is_client_error(self, alice):
        r = alice.post("/api/symptoms", json={"severity": 5})
        assert 400 <= r.status_code < 500

    def test_symptom_non_numeric_severity_coerced(self, alice):
        """FIXED: a non-numeric severity is coerced to the default (5), clamped
        to 1..10 — logging succeeds instead of 500ing."""
        r = alice.post("/api/symptoms", json={"name": "Headache",
                                              "severity": "very bad"})
        assert r.status_code == 200
        assert r.get_json()["symptom"]["severity"] == 5

    def test_symptoms_days_param_non_numeric(self, alice):
        """FIXED: a non-numeric ?days is coerced to the default (14), 200."""
        r = alice.get("/api/symptoms?days=abc")
        assert r.status_code == 200

    def test_vital_missing_type_is_client_error(self, alice):
        r = alice.post("/api/vitals", json={"value1": 120})
        assert 400 <= r.status_code < 500

    def test_vital_non_numeric_value_is_client_error(self, alice):
        r = alice.post("/api/vitals", json={"type": "heart_rate", "value1": "fast"})
        assert 400 <= r.status_code < 500

    def test_vital_bp_roundtrip(self, alice):
        r = alice.post("/api/vitals", json={"type": "blood_pressure",
                                            "value1": 118, "value2": 76,
                                            "unit": "mmHg", "date_key": TODAY})
        assert r.status_code == 200
        v = r.get_json()["vital"]
        assert v["value1"] == 118 and v["value2"] == 76

    def test_implausible_vital_is_rejected(self, alice):
        """FIXED: a gross typo (9,000,000 bpm) is rejected with a 400 so it
        can't poison every trend/insight computed from vitals."""
        r = alice.post("/api/vitals", json={"type": "heart_rate",
                                            "value1": 9000000, "date_key": TODAY})
        assert 400 <= r.status_code < 500
        assert alice.get("/api/vitals").get_json() == []

    def test_abnormal_but_plausible_vital_is_accepted(self, alice):
        """The plausibility bounds are WIDE, not clinical: a genuinely high
        blood pressure (160/100) or fever must still log fine — we only catch
        physically-impossible typos, never abnormal-but-real readings."""
        r = alice.post("/api/vitals", json={"type": "blood_pressure",
                                            "value1": 160, "value2": 100,
                                            "date_key": TODAY})
        assert r.status_code == 200
        r2 = alice.post("/api/vitals", json={"type": "temperature",
                                             "value1": 101.5, "unit": "°F",
                                             "date_key": TODAY})
        assert r2.status_code == 200   # 101.5 °F fever accepted despite °C ranges

    def test_cross_user_vital_delete_is_noop(self, alice, bob):
        vid = alice.post("/api/vitals", json={
            "type": "blood_sugar", "value1": 95, "date_key": TODAY
        }).get_json()["vital"]["id"]
        bob.delete("/api/vitals/%s" % vid)   # returns success but must no-op
        assert any(v["id"] == vid for v in alice.get("/api/vitals").get_json())

    def test_emergency_card_isolated_between_users(self, alice, bob):
        alice.post("/api/emergency", json={"blood_type": "AB-",
                                           "allergies": "stress-marker-penicillin"})
        b = bob.get("/api/emergency").get_json()
        assert b.get("allergies") != "stress-marker-penicillin"
        a = alice.get("/api/emergency").get_json()
        assert a["blood_type"] == "AB-"

    def test_emergency_giant_payload_roundtrips(self, alice):
        """No length limits anywhere (documented) — 100 KB of allergies is
        accepted and returned whole. Fine for SQLite; worth a cap someday."""
        big = "peanut," * 15000            # ~100 KB
        r = alice.post("/api/emergency", json={"allergies": big})
        assert r.status_code == 200
        assert alice.get("/api/emergency").get_json()["allergies"] == big


# ══════════════════════════════════════════════════════════════════════════════
# 7. API SURFACE — auth sweep, aliases, honesty of responses
# ══════════════════════════════════════════════════════════════════════════════

class TestApiSurface:
    def test_every_medical_endpoint_requires_auth(self, app):
        anon = app.test_client()
        gets = ["/api/medicines", "/api/medicines/today",
                "/api/medicines/adherence", "/api/medicines/low-stock",
                "/api/medicines/streaks", "/api/reports", "/api/stats",
                "/api/symptoms", "/api/symptoms/patterns",
                "/api/vitals", "/api/vitals/trend", "/api/emergency",
                "/uploads/anything.pdf"]
        for url in gets:
            assert anon.get(url).status_code == 401, url
        posts = ["/api/medicines", "/api/medicines/x/log",
                 "/api/medicines/x/stock", "/api/upload",
                 "/api/symptoms", "/api/vitals", "/api/emergency"]
        for url in posts:
            assert anon.post(url, json={}).status_code == 401, url

    def test_v1_alias_mirrors_medicines(self, alice):
        mk_med(alice, name="AliasMed")
        v1 = alice.get("/api/v1/medicines")
        assert v1.status_code == 200
        assert any(m["name"] == "AliasMed" for m in v1.get_json())

    def test_mutations_on_nonexistent_ids_return_404(self, alice):
        """FIXED: toggle/delete/log against an id that doesn't exist (or was
        already deleted) now answers an honest 404, so the client can tell
        'done' from 'silently ignored' and resync."""
        assert alice.post("/api/medicines/no-such-id/toggle").status_code == 404
        assert alice.delete("/api/medicines/no-such-id").status_code == 404
        r = alice.post("/api/medicines/no-such-id/log",
                       json={"date": TODAY, "time": "08:00"})
        assert r.status_code == 404
        assert dose_log_count() == 0
