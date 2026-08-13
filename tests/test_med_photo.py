"""I8 — medicine identification photos. Upload an image to a medicine, serve it
through the authenticated /uploads route with an ownership check, and delete it.
Images only; a user can never reach another user's photo."""
import io
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import insert_medicine

PW = "mphoto-pw-1234"
# A 1x1 PNG.
PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
       b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05'
       b'\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    up = tmp_path_factory.mktemp("uploads")
    a = create_app(); a.config["TESTING"] = True
    a.config["UPLOAD_FOLDER"] = str(up)
    init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _client(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    uid = dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]
    return c, uid


def _new_med(app, uid, name="Amlodipine"):
    with user_context(uid):
        return insert_medicine({"name": name, "frequency": "once_daily", "times": ["09:00"]})["id"]


def _img(name="pill.png", data=PNG):
    return {"file": (io.BytesIO(data), name)}


def test_upload_sets_photo_and_serves_it(app):
    c, uid = _client(app, "mphoto1@medeasy.test")
    mid = _new_med(app, uid)
    r = c.post(f"/api/medicines/{mid}/photo", data=_img(), content_type="multipart/form-data")
    body = r.get_json()
    assert r.status_code == 200 and body["success"] is True
    fn = body["photo_path"]
    assert fn.startswith("medphoto_")
    # It's now on the medicine record…
    row = execute("SELECT photo_path FROM medicines WHERE id=?", (mid,), fetchone=True)
    assert dict(row)["photo_path"] == fn
    # …and served to its owner.
    assert c.get(f"/uploads/{fn}").status_code == 200


def test_non_image_rejected(app):
    c, uid = _client(app, "mphoto2@medeasy.test")
    mid = _new_med(app, uid)
    r = c.post(f"/api/medicines/{mid}/photo",
               data={"file": (io.BytesIO(b"%PDF-1.4"), "scan.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 400 and r.get_json()["success"] is False


def test_upload_to_foreign_medicine_404s(app):
    owner, ouid = _client(app, "mphoto3@medeasy.test")
    mid = _new_med(app, ouid)
    attacker, _ = _client(app, "mphoto4@medeasy.test")
    r = attacker.post(f"/api/medicines/{mid}/photo", data=_img(), content_type="multipart/form-data")
    assert r.status_code == 404
    # And the owner's medicine is untouched.
    assert dict(execute("SELECT photo_path FROM medicines WHERE id=?", (mid,), fetchone=True))["photo_path"] == ""


def test_other_user_cannot_fetch_photo(app):
    owner, ouid = _client(app, "mphoto5@medeasy.test")
    mid = _new_med(app, ouid)
    fn = owner.post(f"/api/medicines/{mid}/photo", data=_img(),
                    content_type="multipart/form-data").get_json()["photo_path"]
    attacker, _ = _client(app, "mphoto6@medeasy.test")
    assert attacker.get(f"/uploads/{fn}").status_code == 404   # owner-scoped


def test_delete_removes_reference(app):
    c, uid = _client(app, "mphoto7@medeasy.test")
    mid = _new_med(app, uid)
    fn = c.post(f"/api/medicines/{mid}/photo", data=_img(),
                content_type="multipart/form-data").get_json()["photo_path"]
    assert c.delete(f"/api/medicines/{mid}/photo").status_code == 200
    assert dict(execute("SELECT photo_path FROM medicines WHERE id=?", (mid,), fetchone=True))["photo_path"] == ""
    assert c.get(f"/uploads/{fn}").status_code == 404   # no longer owned/served


def test_replacing_photo_updates_reference(app):
    c, uid = _client(app, "mphoto8@medeasy.test")
    mid = _new_med(app, uid)
    fn1 = c.post(f"/api/medicines/{mid}/photo", data=_img("a.png"),
                 content_type="multipart/form-data").get_json()["photo_path"]
    fn2 = c.post(f"/api/medicines/{mid}/photo", data=_img("b.png"),
                 content_type="multipart/form-data").get_json()["photo_path"]
    assert fn1 != fn2
    assert dict(execute("SELECT photo_path FROM medicines WHERE id=?", (mid,), fetchone=True))["photo_path"] == fn2
