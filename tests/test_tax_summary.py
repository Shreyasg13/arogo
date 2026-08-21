"""Medical-spend organizer (India FY / 80D) — sums own data, never advises."""
import re
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.tax_summary import get_tax_summary, tax_csv_rows, financial_years, fy_of, DISCLAIMER

PW = "tax-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def _expense(uid, date_key, category, amount, covered=0):
    execute("""INSERT INTO health_expenses (id,date_key,category,description,amount,covered,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_id(), date_key, category, category + " item", amount, covered, now_iso(), uid), commit=True)


def test_fy_of_boundaries():
    assert fy_of("2025-04-01") == 2025      # first day of FY 2025-26
    assert fy_of("2026-03-31") == 2025      # last day of FY 2025-26
    assert fy_of("2026-04-01") == 2026      # rolls to next FY


def test_organises_by_category_and_fy(app):
    _, uid = _uid(app, "taxfy1@medeasy.test")
    with user_context(uid):
        # FY 2025-26 (Apr 2025 – Mar 2026)
        _expense(uid, "2025-06-10", "medicines", 1000, 0)
        _expense(uid, "2026-01-15", "insurance", 12000, 0)
        _expense(uid, "2025-09-01", "lab", 800, 300)      # 300 reimbursed
        # a different FY — must be excluded
        _expense(uid, "2024-05-01", "hospital", 50000, 0)
        s = get_tax_summary(2025)
    assert s["label"] == "2025–26"
    assert s["total"] == 13800.0                          # 1000+12000+800, NOT the 2024 one
    assert s["covered"] == 300.0
    assert s["out_of_pocket"] == 13500.0
    assert s["insurance_premiums"] == 12000.0
    assert s["other_medical"] == 1800.0
    cats = {c["key"]: c for c in s["categories"]}
    assert cats["lab"]["net"] == 500.0


def test_disclaimer_present_and_no_advice_language(app):
    _, uid = _uid(app, "taxfy2@medeasy.test")
    with user_context(uid):
        s = get_tax_summary(2025)
    # honesty: never asserts a deductible amount or tells the user what to claim
    txt = s["disclaimer"].lower()
    assert "not tax advice" in txt and "not a deduction calculation" in txt
    assert not re.search(r"you can claim|deductible amount|eligible amount|you will save", txt)
    # the payload must not carry a computed "deduction"/"savings" field
    assert "deduction" not in s and "savings" not in s and "tax_saved" not in s


def test_country_drives_fy_and_currency(app):
    from db.food import update_profile
    from db.locale_config import currency_of
    _, uid = _uid(app, "taxus@medeasy.test")
    with user_context(uid):
        # India default → Apr–Mar, ₹
        assert get_tax_summary(2025)["label"] == "2025–26"
        assert currency_of()["symbol"] == "₹"
        # switch to the US → calendar year Jan–Dec, $
        update_profile({"country": "US"})
        s = get_tax_summary(2025)
    assert s["label"] == "2025"                    # calendar year, not 2025–26
    assert s["start"] == "2025-01-01" and s["end"] == "2025-12-31"
    assert s["currency"]["code"] == "USD" and s["currency"]["symbol"] == "$"


def test_claims_within_fy(app):
    _, uid = _uid(app, "taxfy3@medeasy.test")
    with user_context(uid):
        execute("""INSERT INTO claims (id,insurer,amount,date_submitted,status,reimbursed,created_at,user_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id(), "Acme", 5000, "2025-08-01", "paid", 4000, now_iso(), uid), commit=True)
        s = get_tax_summary(2025)
    assert s["claims"]["claimed"] == 5000.0
    assert s["claims"]["reimbursed"] == 4000.0
    assert s["claims"]["outstanding"] == 1000.0


def test_csv_itemises_the_year(app):
    _, uid = _uid(app, "taxfy4@medeasy.test")
    with user_context(uid):
        _expense(uid, "2025-06-10", "medicines", 1000, 200)
        rows, label = tax_csv_rows(2025)
    assert label == "2025–26"
    assert rows[0] == ['Date', 'Category', 'Description', 'Amount (INR)', 'Reimbursed (INR)', 'Net (INR)']
    assert rows[1][0] == "2025-06-10" and rows[1][-1] == "800.00"


def test_empty_year_is_honest(app):
    _, uid = _uid(app, "taxfy5@medeasy.test")
    with user_context(uid):
        s = get_tax_summary(2025)
    assert s["has_data"] is False and s["total"] == 0.0 and s["categories"] == []


def test_routes(app):
    c, _ = _uid(app, "taxfy6@medeasy.test")
    assert c.get("/api/tax-summary").status_code == 200
    r = c.get("/api/tax-summary/csv?fy=2025")
    assert r.status_code == 200 and "text/csv" in r.headers["Content-Type"]


def test_route_requires_auth(app):
    assert app.test_client().get("/api/tax-summary").status_code in (401, 403)
