"""Category 2 — scoped export. Pick categories, export ONLY those health-data
tables; never account/secret meta, never everything on a stray key. User-scoped."""
import json
import pytest
import auth as auth_module
from app import create_app
from db.core import init_db

PW = "sx-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client(); c.post("/auth/register", json={"email": email, "password": PW}); return c


def _seed(c):
    c.post("/api/medicines", json={"name": "Metformin", "frequency": "once_daily", "times": ["08:00"]})
    c.post("/api/vitals", json={"type": "blood_pressure", "value1": 120, "value2": 80})


def test_categories_listed(app):
    c = _reg(app, "sx1@medeasy.test")
    keys = [x["key"] for x in c.get("/api/export/categories").get_json()["categories"]]
    assert "vitals" in keys and "private" in keys and "medicines" in keys


def test_scoped_export_includes_only_chosen(app):
    c = _reg(app, "sx2@medeasy.test")
    _seed(c)
    d = json.loads(c.post("/api/export/scoped", json={"categories": ["vitals"]}).get_data(as_text=True))
    assert "vitals" in d and d["vitals"]              # chosen, and has the reading
    assert "medicines" not in d                        # not chosen
    assert d["_categories"] == ["vitals"]


def test_empty_or_unknown_categories_export_nothing(app):
    c = _reg(app, "sx3@medeasy.test")
    _seed(c)
    d = json.loads(c.post("/api/export/scoped", json={"categories": ["not-a-cat"]}).get_data(as_text=True))
    # A stray key can never dump everything — only the meta marker is present.
    assert [k for k in d if not k.startswith("_")] == []
    d2 = json.loads(c.post("/api/export/scoped", json={"categories": []}).get_data(as_text=True))
    assert [k for k in d2 if not k.startswith("_")] == []


def test_every_health_table_belongs_to_a_category(app):
    """A scoped export must not silently omit a health table. Anything genuinely
    non-health (account/settings/secret meta) is listed here explicitly, so
    adding a new feature table forces a conscious choice rather than a gap."""
    from db.account import EXPORT_CATEGORIES
    from db.core import DATA_TABLES
    covered = set()
    for _key, _label, tables in EXPORT_CATEGORIES:
        covered.update(tables)
    # Deliberately NOT exportable by category: account/settings/secret meta.
    not_health = {
        'notification_log', 'reminder_settings', 'user_profile', 'oauth_tokens',
        'sync_log', 'measurement_reminders', 'share_snapshots',
    }
    missing = [t for t in DATA_TABLES if t not in covered and t not in not_health]
    assert not missing, (
        "these health tables are in no export category, so a scoped export "
        f"silently drops them: {missing}")


def test_never_exports_account_or_secret_tables(app):
    c = _reg(app, "sx4@medeasy.test")
    _seed(c)
    # Even choosing every category, meta/secret tables are never in a scoped export.
    all_cats = [x["key"] for x in c.get("/api/export/categories").get_json()["categories"]]
    d = json.loads(c.post("/api/export/scoped", json={"categories": all_cats}).get_data(as_text=True))
    for forbidden in ("oauth_tokens", "reminder_settings", "user_profile", "account", "sync_log"):
        assert forbidden not in d


def test_user_scoped(app):
    a = _reg(app, "sx5a@medeasy.test"); b = _reg(app, "sx5b@medeasy.test")
    a.post("/api/medicines", json={"name": "SecretDrugA", "frequency": "once_daily", "times": ["08:00"]})
    d = json.loads(b.post("/api/export/scoped", json={"categories": ["medicines"]}).get_data(as_text=True))
    assert d.get("medicines", []) == []                # B's export never has A's meds


def test_requires_auth(app):
    anon = app.test_client()
    assert anon.get("/api/export/categories").status_code in (401, 403)
    assert anon.post("/api/export/scoped", json={"categories": ["vitals"]}).status_code in (401, 403)
