"""The public transparency page: reachable without auth, and actually states
the promises it exists to make."""
from app import create_app
from db.core import init_db


def _client():
    app = create_app()
    app.config["TESTING"] = True
    init_db()
    return app.test_client()


def test_page_is_public():
    r = _client().get("/how-it-works")           # no session cookie
    assert r.status_code == 200
    assert "text/html" in r.content_type


def test_page_states_the_core_promises():
    body = _client().get("/how-it-works").get_data(as_text=True).lower()
    # The three things the page exists to say.
    assert "no ad" in body or "no advertising" in body
    assert "sell" in body                          # "we don't sell ... your data"
    assert "every number" in body                  # honest-numbers promise
    # And that it explains the metrics + points to data controls.
    assert "adherence" in body and "bmi" in body
    assert "security" in body
