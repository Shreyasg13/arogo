"""M3 symptom photo journal — attach photos to follow how a rash/wound looks
over time. Images only, user-scoped, and the files are reachable only through
the ownership-checked /uploads route (never another user's)."""
import io

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "symph-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


# A 1x1 PNG.
_PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
        b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


def _upload(c, label="Left forearm rash", date="2026-08-10", ext="png"):
    data = {'label': label, 'taken_date': date,
            'file': (io.BytesIO(_PNG), f'rash.{ext}')}
    return c.post("/api/symptom-photos", data=data, content_type='multipart/form-data')


def test_upload_and_list(app):
    c = _reg(app, "symph1@medeasy.test")
    r = _upload(c)
    assert r.status_code == 200 and r.get_json()["success"] is True
    photos = c.get("/api/symptom-photos").get_json()["photos"]
    assert len(photos) == 1
    assert photos[0]["label"] == "Left forearm rash" and photos[0]["taken_date"] == "2026-08-10"
    assert photos[0]["filename"].startswith("sym_")


def test_non_image_rejected(app):
    c = _reg(app, "symph2@medeasy.test")
    data = {'label': 'x', 'file': (io.BytesIO(b'not an image'), 'notes.txt')}
    r = c.post("/api/symptom-photos", data=data, content_type='multipart/form-data')
    assert r.status_code == 400


def test_photo_served_only_to_owner(app):
    owner = _reg(app, "symph3@medeasy.test")
    other = _reg(app, "symph4@medeasy.test")
    fn = _upload(owner).get_json()["photo"]["filename"]
    # Owner can fetch it; another logged-in user gets 404 (ownership-checked route).
    assert owner.get(f"/uploads/{fn}").status_code == 200
    assert other.get(f"/uploads/{fn}").status_code == 404


def test_list_is_user_scoped(app):
    a = _reg(app, "symph5@medeasy.test")
    b = _reg(app, "symph6@medeasy.test")
    _upload(a, label="A's private photo")
    assert b.get("/api/symptom-photos").get_json()["photos"] == []


def test_delete_removes_row_and_blocks_access(app):
    c = _reg(app, "symph7@medeasy.test")
    p = _upload(c).get_json()["photo"]
    c.delete(f"/api/symptom-photos/{p['id']}")
    assert c.get("/api/symptom-photos").get_json()["photos"] == []
    assert c.get(f"/uploads/{p['filename']}").status_code == 404


def test_bad_date_defaults_to_today(app):
    c = _reg(app, "symph8@medeasy.test")
    data = {'label': 'wound', 'taken_date': 'garbage',
            'file': (io.BytesIO(_PNG), 'w.png')}
    r = c.post("/api/symptom-photos", data=data, content_type='multipart/form-data')
    assert r.status_code == 200
    # A real ISO date was substituted, not the string "garbage".
    assert r.get_json()["photo"]["taken_date"][:4].isdigit()


def test_requires_auth(app):
    anon = app.test_client()
    assert anon.get("/api/symptom-photos").status_code in (401, 403)
