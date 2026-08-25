"""Deleting a health record has to be recoverable.

Every delete was a hard DELETE — eighty-two of them. Tapping the wrong row
removed a lab result or a scan of a discharge summary permanently, and some of
that cannot be recreated: a lab value from three years ago exists on a piece of
paper you no longer have.

The opposite promise matters just as much. A trash that never actually empties is
a second copy of everything the user asked you to destroy, so these tests pin the
purge and the emptying as firmly as the recovery.
"""
import datetime as dt
import json
import os

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db import trash as tr

PW = "trash-pw-12345"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    a = create_app()
    a.config["TESTING"] = True
    a.config["UPLOAD_FOLDER"] = str(tmp_path_factory.mktemp("uploads"))
    init_db()
    return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(autouse=True)
def _app_ctx(app):
    with app.app_context():
        yield


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


# ── The registry must not drift ─────────────────────────────────────────────

def test_every_table_has_a_delete_decision():
    """A new table must be recoverable, or explicitly not, with a reason. This is
    what stops a recycle bin quietly becoming half-working as features land."""
    from db.core import DATA_TABLES
    decided = {t.table for t in tr.TRASHABLE} | set(tr.NOT_TRASHABLE)
    missing = sorted(set(DATA_TABLES) - decided)
    assert not missing, (
        "these tables are neither recoverable nor explicitly excluded: "
        + ", ".join(missing))


def test_no_table_is_both_recoverable_and_excluded():
    both = sorted({t.table for t in tr.TRASHABLE} & set(tr.NOT_TRASHABLE))
    assert not both, f"contradictory decision for: {both}"


def test_every_exclusion_states_a_reason():
    vague = sorted(k for k, v in tr.NOT_TRASHABLE.items() if len(str(v).strip()) < 20)
    assert not vague, f"these need a real reason, not a shrug: {vague}"


def test_security_sensitive_deletes_stay_immediate():
    """Disconnecting an integration or revoking a share link must actually take
    effect. A recoverable revocation is a security problem, not a convenience."""
    for t in ("oauth_tokens", "push_subscriptions", "share_snapshots"):
        assert t in tr.NOT_TRASHABLE, f"{t} must not be recoverable"


def test_no_trashable_delete_path_still_hard_deletes():
    """The db layer must route these through soft_delete — a single missed
    function is an unrecoverable delete that looks recoverable everywhere else."""
    import glob
    import re
    tables = {t.table for t in tr.TRASHABLE}
    skip = {"trash.py", "account.py", "core.py"}
    offenders = []
    for path in glob.glob("db/*.py"):
        if os.path.basename(path) in skip:
            continue
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for t in sorted(tables):
            if re.search(r"DELETE FROM " + t + r"\b", src):
                offenders.append(f"{os.path.basename(path)} → {t}")
    assert not offenders, f"still hard-deleting: {offenders}"


# ── Recovery ────────────────────────────────────────────────────────────────

def test_a_deleted_lab_result_comes_back_intact(app):
    c, uid = _uid(app, "trash1@medeasy.test")
    with user_context(uid):
        from db.labs import log_lab_result, delete_lab_result
        row = log_lab_result("hba1c", 5.6, user_today(), notes="fasting")
        delete_lab_result(row["id"])
        assert execute("SELECT 1 FROM lab_results WHERE id=?", (row["id"],),
                       fetchone=True) is None

        items = tr.list_trash()
        assert len(items) == 1
        assert items[0]["kind"] == "Lab result"
        assert "HbA1c" in items[0]["label"] or "hba1c" in items[0]["label"].lower()

        assert tr.restore(items[0]["id"])["ok"] is True
        back = execute("SELECT * FROM lab_results WHERE id=?", (row["id"],), fetchone=True)
    assert back is not None, "the lab result did not come back"
    assert back["value"] == 5.6
    assert back["notes"] == "fasting", "the row must return whole, not as a stub"


def test_restoring_removes_it_from_the_trash(app):
    c, uid = _uid(app, "trash2@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Penicillin", "reaction": "Hives",
                            "severity": "severe", "date_noted": user_today()})
        delete_allergy(a["id"])
        item = tr.list_trash()[0]
        tr.restore(item["id"])
        assert tr.list_trash() == []


def test_a_second_restore_of_the_same_item_fails_cleanly(app):
    c, uid = _uid(app, "trash3@medeasy.test")
    with user_context(uid):
        from db.procedures import add_procedure, delete_procedure
        p = add_procedure({"name": "Appendectomy", "kind": "surgery",
                           "date_key": user_today()})
        delete_procedure(p["id"])
        item = tr.list_trash()[0]
        assert tr.restore(item["id"])["ok"] is True
        again = tr.restore(item["id"])
    assert again["ok"] is False and again["error"]


def test_restore_refuses_to_overwrite_a_row_that_now_exists(app):
    """Writing over whatever occupies that id would be a second silent deletion."""
    c, uid = _uid(app, "trash4@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Sulfa", "reaction": "Rash",
                            "severity": "mild", "date_noted": user_today()})
        delete_allergy(a["id"])
        # Something else takes that id in the meantime.
        execute("""INSERT INTO allergies (id, allergen, reaction, severity,
                     date_noted, created_at, user_id) VALUES (?,?,?,?,?,?,?)""",
                (a["id"], "Something else", "", "mild", user_today(), now_iso(), uid),
                commit=True)
        res = tr.restore(tr.list_trash()[0]["id"])
        current = execute("SELECT allergen FROM allergies WHERE id=?", (a["id"],),
                          fetchone=True)["allergen"]
    assert res["ok"] is False
    assert current == "Something else", "the restore overwrote a live record"


def test_a_column_the_schema_no_longer_has_is_dropped_not_fatal(app):
    """A record from before a migration should still come back, minus a field
    that no longer exists — rather than not at all."""
    c, uid = _uid(app, "trash5@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Latex", "reaction": "Rash",
                            "severity": "mild", "date_noted": user_today()})
        delete_allergy(a["id"])
        item = execute("SELECT * FROM deleted_items WHERE user_id=?", (uid,),
                       fetchone=True)
        payload = json.loads(item["payload"])
        payload["a_column_that_was_removed"] = "x"
        execute("UPDATE deleted_items SET payload=? WHERE id=?",
                (json.dumps(payload), item["id"]), commit=True)
        assert tr.restore(item["id"])["ok"] is True
        assert execute("SELECT allergen FROM allergies WHERE id=?", (a["id"],),
                       fetchone=True)["allergen"] == "Latex"


# ── Scope ───────────────────────────────────────────────────────────────────

def test_one_user_never_sees_or_restores_anothers_trash(app):
    ca, ua = _uid(app, "trash6a@medeasy.test")
    cb, ub = _uid(app, "trash6b@medeasy.test")
    with user_context(ua):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Peanut", "reaction": "Swelling",
                            "severity": "severe", "date_noted": user_today()})
        delete_allergy(a["id"])
        mine = tr.list_trash()[0]["id"]
    with user_context(ub):
        assert tr.list_trash() == []
        assert tr.restore(mine)["ok"] is False
        assert tr.purge(mine) is False
    with user_context(ua):
        assert len(tr.list_trash()) == 1, "another user's call removed my item"


def test_the_trash_is_walled_from_a_caregiver():
    """It holds whole deleted rows — journal entries and notes among them — so
    browsing it would walk straight around the private-category wall."""
    from auth import _is_private_while_acting
    assert _is_private_while_acting("/api/trash")
    assert _is_private_while_acting("/api/v1/trash")


def test_private_entries_are_dropped_when_asked(app):
    c, uid = _uid(app, "trash7@medeasy.test")
    with user_context(uid):
        from db.wellness import save_thought, delete_thought
        t = save_thought("Feeling anxious about the scan.", "sad", user_today())
        delete_thought(t["id"])
        assert len(tr.list_trash(include_private=True)) == 1
        assert tr.list_trash(include_private=False) == []


# ── Emptying really empties ─────────────────────────────────────────────────

def test_expired_items_are_purged(app):
    c, uid = _uid(app, "trash8@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Dust", "reaction": "Sneezing",
                            "severity": "mild", "date_noted": user_today()})
        delete_allergy(a["id"])
        execute("UPDATE deleted_items SET expires_at=? WHERE user_id=?",
                ((dt.datetime.now() - dt.timedelta(days=1)).isoformat(), uid),
                commit=True)
    assert tr.purge_expired() >= 1
    with user_context(uid):
        assert tr.list_trash() == []


def test_an_item_within_its_window_is_not_purged(app):
    c, uid = _uid(app, "trash9@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Pollen", "reaction": "Itchy eyes",
                            "severity": "mild", "date_noted": user_today()})
        delete_allergy(a["id"])
        tr.purge_expired()
        assert len(tr.list_trash()) == 1
        assert tr.list_trash()[0]["days_left"] >= tr.RETENTION_DAYS - 1


def test_emptying_the_trash_is_immediate_and_real(app):
    c, uid = _uid(app, "trash10@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        for name in ("A", "B", "C"):
            a = create_allergy({"allergen": name, "reaction": "x",
                                "severity": "mild", "date_noted": user_today()})
            delete_allergy(a["id"])
        assert tr.empty_trash() == 3
        assert tr.list_trash() == []


def test_deleting_an_account_takes_its_trash_with_it(app):
    from db.account import delete_account
    c, uid = _uid(app, "trash11@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Shellfish", "reaction": "Hives",
                            "severity": "severe", "date_noted": user_today()})
        delete_allergy(a["id"])
        assert len(tr.list_trash()) == 1
    delete_account(uid)
    left = execute("SELECT COUNT(*) AS n FROM deleted_items WHERE user_id=?",
                   (uid,), fetchone=True)["n"]
    assert left == 0, "erasing an account must erase its trash too"


# ── Files ───────────────────────────────────────────────────────────────────

def _write(app, name):
    path = os.path.join(app.config["UPLOAD_FOLDER"], name)
    with open(path, "wb") as fh:
        fh.write(b"x" * 64)
    # Backdate it past the orphan grace period so the sweep would consider it.
    old = dt.datetime.now().timestamp() - 7200
    os.utime(path, (old, old))
    return path


def _add_report(uid, filename):
    rid = new_id()
    execute("""INSERT INTO reports (id, filename, original_name, patient_name,
                 report_type, report_date, upload_date, user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, filename, filename, "", "lab", "2026-08-01", now_iso(), uid),
            commit=True)
    return rid


def test_a_trashed_records_file_is_not_treated_as_an_orphan(app):
    """The scan behind a deleted record has to survive as long as the record can
    be restored — otherwise a restore hands back an entry pointing at nothing."""
    from db import storage as st
    c, uid = _uid(app, "trash12@medeasy.test")
    _write(app, "trashed-scan.pdf")
    with user_context(uid):
        rid = _add_report(uid, "trashed-scan.pdf")
        from db.reports import delete_report
        delete_report(rid)
        assert "trashed-scan.pdf" not in {o["name"] for o in st.find_orphans()}
        assert "trashed-scan.pdf" in st.files_owned_by(uid)


def test_a_restored_record_still_has_its_file(app):
    from db import storage as st
    c, uid = _uid(app, "trash13@medeasy.test")
    _write(app, "restored-scan.pdf")
    with user_context(uid):
        rid = _add_report(uid, "restored-scan.pdf")
        from db.reports import delete_report
        delete_report(rid)
        st.delete_files(o["name"] for o in st.find_orphans())    # a sweep runs
        tr.restore(tr.list_trash()[0]["id"])
    assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "restored-scan.pdf"))


def test_purging_an_item_removes_its_file(app):
    c, uid = _uid(app, "trash14@medeasy.test")
    _write(app, "purged-scan.pdf")
    with user_context(uid):
        rid = _add_report(uid, "purged-scan.pdf")
        from db.reports import delete_report
        delete_report(rid)
        tr.purge(tr.list_trash()[0]["id"])
    assert not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "purged-scan.pdf"))


def test_purging_leaves_a_file_another_live_record_uses(app):
    c, uid = _uid(app, "trash15@medeasy.test")
    _write(app, "shared-scan.pdf")
    with user_context(uid):
        rid1 = _add_report(uid, "shared-scan.pdf")
        _add_report(uid, "shared-scan.pdf")                 # a second row, same file
        from db.reports import delete_report
        delete_report(rid1)
        tr.purge(tr.list_trash()[0]["id"])
    assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "shared-scan.pdf")), \
        "purging one record erased a file another record still points at"


# ── Search must not claim it never existed ──────────────────────────────────

def test_search_says_when_a_match_is_sitting_in_the_trash(app):
    """"No results" reads as "you never recorded that". If it's recoverable,
    say so."""
    from db.search import global_search
    c, uid = _uid(app, "trash16@medeasy.test")
    with user_context(uid):
        from db.allergies import create_allergy, delete_allergy
        a = create_allergy({"allergen": "Ibuprofenxyz", "reaction": "Rash",
                            "severity": "mild", "date_noted": user_today()})
        assert global_search("Ibuprofenxyz")["total"] == 1
        delete_allergy(a["id"])
        after = global_search("Ibuprofenxyz")
    assert after["total"] == 0
    assert after.get("in_trash") == 1


# ── Routes ──────────────────────────────────────────────────────────────────

def test_routes_require_auth(app):
    anon = app.test_client()
    assert anon.get("/api/trash").status_code == 401
    assert anon.post("/api/trash/x/restore").status_code == 401
    assert anon.delete("/api/trash/x").status_code == 401
    assert anon.delete("/api/trash").status_code == 401


def test_the_round_trip_through_the_api(app):
    c, uid = _uid(app, "trash17@medeasy.test")
    c.post("/api/allergies", json={"allergen": "Codeine", "reaction": "Nausea",
                                   "severity": "moderate", "date_noted": user_today()})
    aid = c.get("/api/allergies").get_json()["allergies"][0]["id"]
    assert c.delete(f"/api/allergies/{aid}").status_code == 200
    assert c.get("/api/allergies").get_json()["allergies"] == []

    listed = c.get("/api/trash").get_json()
    assert listed["retention_days"] == tr.RETENTION_DAYS
    assert len(listed["items"]) == 1
    item = listed["items"][0]
    assert item["kind"] == "Allergy" and item["label"] == "Codeine"

    assert c.post(f"/api/trash/{item['id']}/restore").get_json()["ok"] is True
    assert [a["allergen"] for a in c.get("/api/allergies").get_json()["allergies"]] == ["Codeine"]


def test_the_trash_can_be_searched(app):
    c, uid = _uid(app, "trash18@medeasy.test")
    for name in ("Aspirinzz", "Morphinezz"):
        c.post("/api/allergies", json={"allergen": name, "reaction": "x",
                                       "severity": "mild", "date_noted": user_today()})
    for a in c.get("/api/allergies").get_json()["allergies"]:
        c.delete(f"/api/allergies/{a['id']}")
    found = c.get("/api/trash?q=aspirin").get_json()["items"]
    assert [i["label"] for i in found] == ["Aspirinzz"]
