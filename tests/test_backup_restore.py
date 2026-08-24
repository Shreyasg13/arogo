"""Local backup & restore: full snapshot download + guarded import."""
import json

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "bkp-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def test_backup_downloads_a_named_json_snapshot(app):
    c = _register(app, "bkp1@medeasy.test")
    c.post("/api/medicines", json={"name": "Metformin", "frequency": "once_daily", "times": ["09:00"]})
    r = c.get("/api/backup")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = json.loads(r.data)
    assert data["_backup"]["app"] == "arogo"
    assert any(m["name"] == "Metformin" for m in data["medicines"])


def test_restore_replaces_current_data_with_the_backup(app):
    c = _register(app, "bkp2@medeasy.test")
    c.post("/api/medicines", json={"name": "Original", "frequency": "once_daily", "times": ["09:00"]})
    backup = json.loads(c.get("/api/backup").data)

    # Change the world after taking the backup…
    c.post("/api/medicines", json={"name": "AddedLater", "frequency": "once_daily", "times": ["10:00"]})
    assert {m["name"] for m in c.get("/api/medicines").get_json()} == {"Original", "AddedLater"}

    # …then restore the backup: only what it held should remain.
    res = c.post("/api/import", json=backup).get_json()
    assert res["success"] is True and res["total"] >= 1
    names = {m["name"] for m in c.get("/api/medicines").get_json()}
    assert names == {"Original"}


def test_restore_rejects_a_file_that_isnt_a_backup(app):
    c = _register(app, "bkp3@medeasy.test")
    r = c.post("/api/import", json={"hello": "world"})
    assert r.status_code == 400 and r.get_json()["success"] is False


def test_restore_forces_ownership_to_the_current_user(app):
    c = _register(app, "bkp4@medeasy.test")
    # A crafted backup claiming rows belong to someone else must still land on me.
    payload = {"medicines": [{
        "id": "x1", "name": "Injected", "frequency": "once_daily",
        "times": '["09:00"]', "active": 1, "created_at": "2026-01-01T00:00:00",
        "user_id": "SOMEONE-ELSE"}]}
    c.post("/api/import", json=payload)
    got = c.get("/api/medicines").get_json()
    assert [m["name"] for m in got] == ["Injected"]     # visible to me = owned by me


def test_backup_and_import_require_auth(app):
    anon = app.test_client()
    assert anon.get("/api/backup").status_code == 401
    assert anon.post("/api/import", json={"medicines": []}).status_code == 401
    assert anon.post("/api/import/preview", json={"medicines": []}).status_code == 401


# ── The preview must name everything the restore touches ────────────────────

def test_every_restorable_table_has_a_human_label():
    """A table with no label would be replaced without ever appearing on the
    confirmation screen — which is what happened to 44 of them when the list
    lived in the browser."""
    from db.account import TABLE_LABELS, NOT_RESTORED
    from db.core import DATA_TABLES
    missing = sorted(set(DATA_TABLES) - set(TABLE_LABELS) - set(NOT_RESTORED))
    assert not missing, (
        "these tables would be restored without being named in the confirmation: "
        + ", ".join(missing))


def test_preview_names_a_table_the_old_client_list_hid(app):
    c = _register(app, "bkp5@medeasy.test")
    today = "2026-08-01"
    c.post("/api/allergies", json={"allergen": "Penicillin", "reaction": "Hives",
                                   "severity": "severe", "date_noted": today})
    backup = json.loads(c.get("/api/backup").data)
    p = c.post("/api/import/preview", json=backup).get_json()
    assert p["ok"] is True
    named = {e["table"]: e for e in p["tables"]}
    assert "allergies" in named, "allergies were restored but never shown"
    assert named["allergies"]["label"] == "Allergies"
    assert named["allergies"]["incoming"] == 1


def test_preview_reports_what_will_be_deleted(app):
    c = _register(app, "bkp6@medeasy.test")
    backup = json.loads(c.get("/api/backup").data)          # empty history
    c.post("/api/medicines", json={"name": "AddedAfter", "frequency": "once_daily",
                                   "times": ["09:00"]})
    p = c.post("/api/import/preview", json=backup).get_json()
    meds = next(e for e in p["tables"] if e["table"] == "medicines")
    assert meds["current"] == 1, "the preview must say how many of my rows go"
    assert meds["incoming"] == 0


def test_preview_flags_the_areas_a_backup_would_empty(app):
    """The quiet data-loss case: a backup taken before you tracked something
    lists that table with no rows, so the restore deletes what you have and puts
    nothing back. The old preview filtered empty tables out entirely."""
    c = _register(app, "bkp7@medeasy.test")
    backup = json.loads(c.get("/api/backup").data)
    c.post("/api/medicines", json={"name": "WouldVanish", "frequency": "once_daily",
                                   "times": ["09:00"]})
    p = c.post("/api/import/preview", json=backup).get_json()
    emptied = {e["table"] for e in p["emptying"]}
    assert "medicines" in emptied
    assert any(e["current"] == 1 for e in p["emptying"] if e["table"] == "medicines")


def test_preview_lists_areas_the_file_does_not_mention(app):
    """A partial file leaves other areas alone — say so, so "restore" isn't read
    as "everything is back exactly as it was"."""
    c = _register(app, "bkp8@medeasy.test")
    c.post("/api/medicines", json={"name": "Kept", "frequency": "once_daily",
                                   "times": ["09:00"]})
    p = c.post("/api/import/preview", json={"allergies": []}).get_json()
    untouched = {e["table"] for e in p["untouched"]}
    assert "medicines" in untouched


def test_preview_writes_nothing(app):
    c = _register(app, "bkp9@medeasy.test")
    c.post("/api/medicines", json={"name": "StillHere", "frequency": "once_daily",
                                   "times": ["09:00"]})
    c.post("/api/import/preview", json={"medicines": []})
    assert [m["name"] for m in c.get("/api/medicines").get_json()] == ["StillHere"]


def test_preview_rejects_a_file_that_isnt_a_backup(app):
    c = _register(app, "bkp10@medeasy.test")
    r = c.post("/api/import/preview", json={"hello": "world"})
    assert r.status_code == 400 and r.get_json()["ok"] is False


# ── Atomicity: a failed restore must leave the old data alone ───────────────

def test_a_failed_restore_leaves_existing_data_untouched(app, monkeypatch):
    """The old code deleted a table's rows and then inserted the backup's one
    autocommitted statement at a time, so a crash partway through left the user
    with neither their old data nor all of the new. That is the worst outcome a
    restore can have, so it is now one transaction."""
    c = _register(app, "bkp11@medeasy.test")
    c.post("/api/medicines", json={"name": "MustSurvive", "frequency": "once_daily",
                                   "times": ["09:00"]})
    c.post("/api/allergies", json={"allergen": "MustAlsoSurvive", "reaction": "Rash",
                                   "severity": "mild", "date_noted": "2026-08-01"})

    import db.account as account
    real = account._row_columns
    calls = {"n": 0}

    def explode(row, cols):
        calls["n"] += 1
        if calls["n"] > 1:                     # let one row through, then fail
            raise RuntimeError("disk went away mid-restore")
        return real(row, cols)

    monkeypatch.setattr(account, "_row_columns", explode)
    r = c.post("/api/import", json={
        "medicines": [{"id": "n1", "name": "New1", "frequency": "once_daily",
                       "times": '["08:00"]', "active": 1,
                       "created_at": "2026-01-01T00:00:00"},
                      {"id": "n2", "name": "New2", "frequency": "once_daily",
                       "times": '["09:00"]', "active": 1,
                       "created_at": "2026-01-01T00:00:00"}],
        "allergies": [],
    })
    assert r.status_code == 500
    body = r.get_json()
    assert body["success"] is False
    assert "unchanged" in body["error"].lower(), "tell them nothing was lost"

    monkeypatch.undo()
    names = {m["name"] for m in c.get("/api/medicines").get_json()}
    assert names == {"MustSurvive"}, f"a rolled-back restore lost data: {names}"
    allergens = {a["allergen"] for a in c.get("/api/allergies").get_json()["allergies"]}
    assert allergens == {"MustAlsoSurvive"}


# ── Honest reporting ────────────────────────────────────────────────────────

def test_skipped_rows_are_reported_not_swallowed(app):
    """"✓ Restored 3,100 records" while 900 silently failed tells someone their
    history is back when it isn't, and gives them no reason to check."""
    c = _register(app, "bkp12@medeasy.test")
    res = c.post("/api/import", json={"medicines": [
        {"id": "ok1", "name": "Good", "frequency": "once_daily",
         "times": '["08:00"]', "active": 1, "created_at": "2026-01-01T00:00:00"},
        "not-even-an-object",
        {"nothing_this_schema_knows": 1},
    ]}).get_json()
    assert res["success"] is True
    assert res["total"] == 1
    assert res["skipped_total"] == 2, "unreadable rows must be counted out loud"
    assert res["skipped"]["medicines"] == 2


def test_restore_reports_what_it_deleted(app):
    c = _register(app, "bkp13@medeasy.test")
    c.post("/api/medicines", json={"name": "Replaced", "frequency": "once_daily",
                                   "times": ["09:00"]})
    res = c.post("/api/import", json={"medicines": [
        {"id": "r1", "name": "Fresh", "frequency": "once_daily",
         "times": '["08:00"]', "active": 1, "created_at": "2026-01-01T00:00:00"}]}).get_json()
    assert res["deleted"]["medicines"] == 1


# ── Credential-bearing tables stay out of a restore ─────────────────────────

def test_redacted_credential_tables_are_not_restored(app):
    """A backup redacts OAuth tokens, so writing the row back would show a
    connected service that cannot sync. Not restoring it, and saying why, beats
    a dead integration that looks alive."""
    from db.account import NOT_RESTORED
    c = _register(app, "bkp14@medeasy.test")
    res = c.post("/api/import", json={
        "medicines": [],
        "oauth_tokens": [{"id": "t1", "service": "strava",
                          "access_token": "[redacted]", "athlete_name": "Someone"}],
    }).get_json()
    assert "oauth_tokens" not in res["restored"]
    assert "oauth_tokens" in NOT_RESTORED
    assert len(NOT_RESTORED["oauth_tokens"]) > 20, "the reason is shown to the user"


def test_preview_explains_what_it_will_not_restore(app):
    c = _register(app, "bkp15@medeasy.test")
    p = c.post("/api/import/preview", json={
        "medicines": [], "oauth_tokens": [{"id": "t1", "service": "strava"}],
    }).get_json()
    skipped = {e["table"]: e for e in p["not_restored"]}
    assert "oauth_tokens" in skipped
    assert skipped["oauth_tokens"]["reason"]


def test_restore_still_forces_ownership_under_a_transaction(app):
    c = _register(app, "bkp16@medeasy.test")
    c.post("/api/import", json={"medicines": [{
        "id": "own1", "name": "Mine", "frequency": "once_daily",
        "times": '["09:00"]', "active": 1, "created_at": "2026-01-01T00:00:00",
        "user_id": "SOMEONE-ELSE"}]})
    assert [m["name"] for m in c.get("/api/medicines").get_json()] == ["Mine"]
