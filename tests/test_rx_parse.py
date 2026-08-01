"""Prescription parsing: pull recognisable medicines + dose + frequency out of
text, and the parse route that proposes (never saves) them."""
import io

import pytest

import auth as auth_module
import rx_parse
from app import create_app
from db.core import init_db

PW = "rx-pw-12345"

SAMPLE = """
Dr. A. Sharma — City Clinic
Rx
1. Tab Paracetamol 500 mg   TDS   x 5 days (after food)
2. Cap Amoxicillin 250mg    1-0-1
3. Tab Azithromycin 500 mg  OD    x 3 days
   Please rest and drink fluids.
"""


def test_finds_known_medicines_with_dose_and_frequency():
    meds = {m['name']: m for m in rx_parse.find_medicines(SAMPLE)}
    assert 'Paracetamol' in meds
    assert meds['Paracetamol']['dosage'] == '500' and meds['Paracetamol']['unit'] == 'mg'
    assert meds['Paracetamol']['frequency'] == 'thrice_daily'          # TDS
    assert meds['Amoxicillin']['dosage'] == '250'
    assert meds['Amoxicillin']['frequency'] == 'twice_daily'           # 1-0-1
    assert meds['Azithromycin']['frequency'] == 'once_daily'           # OD


def test_ignores_unknown_words_and_dedupes():
    meds = rx_parse.find_medicines("Take some rest and soup. Paracetamol 500 mg. Paracetamol again.")
    names = [m['name'] for m in meds]
    assert names == ['Paracetamol']            # unknown words dropped, deduped


def test_empty_input():
    assert rx_parse.find_medicines('') == []
    assert rx_parse.find_medicines(None) == []


def test_frequency_defaults_to_once_daily():
    m = rx_parse.find_medicines("Tab Paracetamol 650 mg")[0]
    assert m['frequency'] == 'once_daily'


# ── route ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    app = create_app(); app.config["TESTING"] = True; init_db()
    c = app.test_client()
    c.post("/auth/register", json={"email": "rx@medeasy.test", "password": PW})
    return c


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def test_parse_route_proposes_but_does_not_save(client):
    data = {'file': (io.BytesIO(SAMPLE.encode()), 'rx.txt')}
    r = client.post('/api/medicines/parse-rx', data=data, content_type='multipart/form-data')
    assert r.status_code == 200
    d = r.get_json()
    names = {m['name'] for m in d['medicines']}
    assert {'Paracetamol', 'Amoxicillin', 'Azithromycin'} <= names
    assert 'ocr_available' in d
    # It only proposes — the user's medicine list is still empty.
    assert client.get('/api/medicines').get_json() == []


def test_parse_route_rejects_bad_type(client):
    data = {'file': (io.BytesIO(b'x'), 'evil.exe')}
    r = client.post('/api/medicines/parse-rx', data=data, content_type='multipart/form-data')
    assert r.status_code == 400
