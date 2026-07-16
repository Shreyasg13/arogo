"""
tests/test_lab_parse.py — Reading vitals out of an uploaded lab report.

The happy path here is the easy part. The tests that earn their keep are the
traps: a lab report is dense with numbers that *look* like results and aren't
— reference bands, printed targets, sample IDs, ages. Proposing one of those
puts a wrong number in someone's health chart, which is worse than proposing
nothing at all. So most of this file asserts that we stay quiet.

The other invariant under test: the endpoint only ever *proposes*. Asking for
a report's readings must never write a vital.

Run:  pytest tests/test_lab_parse.py -v
"""
import io
import os
os.environ["MEDEASY_DB"] = ":memory:"

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

import auth as auth_module
import lab_parse
from db.core import init_db
from app import create_app

PW = "lab-pw-123456"
EMAIL = "lab@medeasy.test"

# A digitally-generated lab report, columns flattened the way PDF text
# extraction actually emits them.
REPORT = """SUNRISE DIAGNOSTICS PVT LTD
Patient: A GUPTA   Age: 34 Y   Sex: M
Lab No: 20260714-88213      Report Date: 14/07/2026

TEST                        RESULT      UNITS       REFERENCE RANGE
Glucose, Fasting            104         mg/dL       70 - 100
Haemoglobin                 14.2        g/dL        13.0 - 17.0
Total Cholesterol           186         mg/dL       < 200
Blood Pressure              128/84      mmHg        < 120/80
Pulse Rate                  76          bpm         60 - 100
SpO2                        97          %           95 - 100
Temperature                 36.8        C
"""


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def user(app):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": EMAIL, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code in (200, 201)
    return c


def found(text):
    return {r["type"]: r for r in lab_parse.find_readings(text)}


def make_pdf(lines):
    """A minimal but genuinely digital one-page PDF — real text operators, so
    this exercises the actual pypdf path rather than a stubbed string."""
    body = "BT /F1 10 Tf 40 750 Td 14 TL\n"
    for l in lines:
        body += "({}) Tj T*\n".format(l)
    body += "ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        "<< /Length {} >>\nstream\n{}\nendstream".format(len(body), body),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += "{} 0 obj\n{}\nendobj\n".format(i, o)
    xref = len(out)
    out += "xref\n0 {}\n0000000000 65535 f \n".format(len(objs) + 1)
    for off in offsets:
        out += "{:010d} 00000 n \n".format(off)
    out += "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n".format(
        len(objs) + 1, xref)
    return out.encode("latin-1")


PDF_LINES = [
    "SUNRISE DIAGNOSTICS PVT LTD",
    "Patient: A GUPTA   Age: 34 Y   Sex: M",
    "TEST                RESULT    UNITS    REFERENCE RANGE",
    "Glucose, Fasting    104       mg/dL    70 - 100",
    "Haemoglobin         14.2      g/dL     13.0 - 17.0",
    "Blood Pressure      128/84    mmHg     < 120/80",
    "Pulse Rate          76        bpm      60 - 100",
]


# ══════════════════════════════════════════════════════════════════════════════
# What it should read
# ══════════════════════════════════════════════════════════════════════════════

class TestReadsRealReports:
    def test_pulls_every_tracked_vital_off_a_real_report(self):
        r = found(REPORT)
        assert r["blood_sugar"]["value1"] == 104        # the result, not the 70-100 band
        assert (r["blood_pressure"]["value1"],
                r["blood_pressure"]["value2"]) == (128, 84)
        assert r["heart_rate"]["value1"] == 76
        assert r["spo2"]["value1"] == 97
        assert r["temperature"]["value1"] == 36.8
        assert r["temperature"]["unit"] == "°C"

    def test_ignores_labs_the_app_doesnt_track(self):
        # Haemoglobin and cholesterol are in the report; the app has nowhere
        # to put them, so they must not surface as some other vital.
        assert set(found(REPORT)) == {"blood_sugar", "blood_pressure",
                                      "heart_rate", "spo2", "temperature"}

    def test_every_reading_quotes_its_source_line(self):
        # The user can only confirm a reading if we show them where it came from.
        for r in lab_parse.find_readings(REPORT):
            assert r["context"], f"{r['type']} has no source line to check against"
        assert "104" in found(REPORT)["blood_sugar"]["context"]

    def test_mmol_glucose_is_converted_not_taken_at_face_value(self):
        # Non-US labs report mmol/L. An unconverted 5.6 would sail through as a
        # plausible-looking mg/dL number and land in the chart as a fake reading.
        r = found("Fasting glucose 5.6 mmol/L")["blood_sugar"]
        assert r["value1"] == 101 and r["unit"] == "mg/dL"
        assert "mmol" in r["note"]

    def test_fahrenheit_and_celsius_both_land_on_the_right_scale(self):
        assert found("Temperature 98.6 F")["temperature"]["unit"] == "°F"
        assert found("Temperature 37.1 C")["temperature"]["unit"] == "°C"

    def test_label_abbreviations_labs_actually_use(self):
        assert found("FBS 96 mg/dL")["blood_sugar"]["value1"] == 96
        assert found("B.P. 118/76")["blood_pressure"]["value1"] == 118


# ══════════════════════════════════════════════════════════════════════════════
# What it must refuse to read — a wrong number is worse than no number
# ══════════════════════════════════════════════════════════════════════════════

class TestStaysQuietRatherThanGuess:
    def test_blank_result_column_does_not_yield_the_reference_floor(self):
        # The trap: with the result column empty, the first number on the row is
        # the reference band's floor — and a floor is *always* a plausible-looking
        # result, so no downstream range check would ever catch it.
        assert found("Glucose, Fasting            mg/dL       70 - 100") == {}

    def test_reference_band_written_with_to(self):
        assert found("Blood sugar   70 to 100 mg/dL") == {}

    def test_printed_target_is_not_a_measurement(self):
        # "< 120/80" on the form is the goal, not what the patient measured.
        assert found("Blood Pressure    < 120/80 mmHg") == {}
        assert found("Blood sugar less than 100 mg/dL") == {}

    def test_ids_ages_and_invoice_numbers(self):
        assert found("Lab No: 20260714-88213\nInvoice 4412 Age: 34") == {}

    def test_prose_that_merely_names_a_vital(self):
        assert found("Patient advised to monitor blood pressure at home.") == {}

    def test_clinically_impossible_values_are_dropped(self):
        assert found("Pulse Rate 999 bpm") == {}

    def test_ambiguous_temperature_says_nothing(self):
        # 20 is neither a plausible °C nor °F body temperature — refuse to guess.
        assert found("Temperature 20") == {}

    def test_reversed_blood_pressure_is_not_silently_accepted(self):
        assert found("Blood Pressure 80/128 mmHg") == {}

    def test_a_decoy_row_doesnt_stop_us_finding_the_real_value(self):
        # Rejecting a candidate must not mean giving up on the whole document.
        r = found("Glucose, Fasting     mg/dL   70 - 100\nRandom glucose  142  mg/dL")
        assert r["blood_sugar"]["value1"] == 142

    def test_empty_and_garbage_input(self):
        for junk in ("", None, "\x00\x01\x02", "no numbers here at all"):
            assert lab_parse.find_readings(junk) == []


# ══════════════════════════════════════════════════════════════════════════════
# The endpoint: proposes, never writes
# ══════════════════════════════════════════════════════════════════════════════

class TestReadingsEndpoint:
    def _upload(self, user, name, body):
        r = user.post("/api/upload", content_type="multipart/form-data",
                      data={"file": (io.BytesIO(body), name),
                            "report_date": "2026-07-14"})
        assert r.status_code == 200
        return r.get_json()["report"]["id"]

    def test_reads_an_uploaded_text_report(self, user):
        rid = self._upload(user, "labs.txt", REPORT.encode())
        d = user.get(f"/api/reports/{rid}/readings").get_json()
        types = {r["type"] for r in d["readings"]}
        assert {"blood_sugar", "blood_pressure", "heart_rate"} <= types

    def test_readings_are_dated_to_the_test_not_the_upload(self, user):
        # A reading from a report dated last week belongs on last week's chart.
        rid = self._upload(user, "labs.txt", REPORT.encode())
        assert user.get(f"/api/reports/{rid}/readings").get_json()["date_key"] == "2026-07-14"

    def test_asking_for_readings_never_writes_a_vital(self, user):
        # The whole safety model: extraction proposes, the user disposes.
        before = len(user.get("/api/vitals?days=3650").get_json())
        rid = self._upload(user, "labs.txt", REPORT.encode())
        assert user.get(f"/api/reports/{rid}/readings").get_json()["readings"]
        assert len(user.get("/api/vitals?days=3650").get_json()) == before

    def test_reads_a_real_digital_pdf(self, user):
        # The format that actually matters: lab portals email digital PDFs.
        rid = self._upload(user, "labs.pdf", make_pdf(PDF_LINES))
        d = user.get(f"/api/reports/{rid}/readings").get_json()
        r = {x["type"]: x for x in d["readings"]}
        assert r["blood_sugar"]["value1"] == 104
        assert (r["blood_pressure"]["value1"], r["blood_pressure"]["value2"]) == (128, 84)
        assert r["heart_rate"]["value1"] == 76

    def test_scanned_pdf_is_called_a_scan_not_an_empty_report(self, user):
        # A scan is a picture in a PDF wrapper: the page yields a few stray
        # letterhead characters. Saying "no readings found" would imply we read
        # it — we couldn't, and the difference is what the user should do next.
        rid = self._upload(user, "scan.pdf", make_pdf(["Sunrise Diagnostics"]))
        d = user.get(f"/api/reports/{rid}/readings").get_json()
        assert d["readings"] == [] and "scan" in d["reason"].lower()

    def test_damaged_pdf_fails_gracefully(self, user):
        rid = self._upload(user, "broken.pdf", b"%PDF-1.4\nthis is not really a pdf")
        r = user.get(f"/api/reports/{rid}/readings")
        assert r.status_code == 200 and r.get_json()["readings"] == []

    def test_photo_says_why_instead_of_looking_empty(self, user):
        # "No readings found" would imply we read it and it had none. We can't
        # read photos at all, and the user deserves to know which it is.
        rid = self._upload(user, "scan.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        d = user.get(f"/api/reports/{rid}/readings").get_json()
        assert d["readings"] == [] and "photo" in d["reason"].lower()

    def test_report_with_no_tracked_readings_says_so(self, user):
        rid = self._upload(user, "note.txt", b"Referral letter. Please see attached.")
        d = user.get(f"/api/reports/{rid}/readings").get_json()
        assert d["readings"] == [] and d["reason"]

    def test_requires_auth(self, app):
        assert app.test_client().get("/api/reports/whatever/readings").status_code == 401

    def test_cannot_read_someone_elses_report(self, app, user):
        rid = self._upload(user, "labs.txt", REPORT.encode())
        other = app.test_client()
        other.post("/auth/register", json={"email": "nosy@medeasy.test", "password": PW})
        assert other.get(f"/api/reports/{rid}/readings").status_code == 404

    def test_unknown_report_is_404_not_a_crash(self, user):
        assert user.get("/api/reports/does-not-exist/readings").status_code == 404
