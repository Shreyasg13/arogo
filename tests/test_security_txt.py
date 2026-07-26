"""security.txt (RFC 9116) is served with a contact and expiry."""
import pytest

from db.core import init_db
from app import create_app


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


def test_security_txt_served(app):
    r = app.test_client().get("/.well-known/security.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["Content-Type"]
    body = r.get_data(as_text=True)
    assert "Contact:" in body
    assert "Expires:" in body           # required by RFC 9116
