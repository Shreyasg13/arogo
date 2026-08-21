"""
db/tax_summary.py — a medical-spend organizer for tax & reimbursement.

Every year people scramble to total their medical receipts. This ORGANIZES the
expenses you already logged into your country's financial year, grouped by
category, with net out-of-pocket and reimbursement status, and an itemised CSV to
hand to an accountant. The financial-year boundary follows your chosen country
(e.g. Apr–Mar in India/UK, Jul–Jun in Australia, Jan–Dec elsewhere).

HONESTY — this is NOT tax advice and NOT a deduction calculation. It only sums
what you logged; whether any of it is deductible, and how much, depends on the
rules and your situation. We never assert an eligible amount, never tell you what
to claim, and always say to confirm with a professional. No financial advice.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, user_today
from .locale_config import country_of, country_info, currency_of

_CAT_LABEL = {
    'medicines': 'Medicines', 'consultation': 'Consultations', 'lab': 'Lab tests',
    'hospital': 'Hospital', 'insurance': 'Insurance premium', 'other': 'Other',
}


def _fy_start_month():
    return country_info(country_of())['fy_start_month']


def _disclaimer():
    note = country_info(country_of()).get('tax_note')
    ref = f" (in some places, {note})" if note else ""
    return ("This organises the medical spending you logged for the financial year. "
            "It is not tax advice and not a deduction calculation — whether any of it "
            f"is eligible{ref}, and how much, depends on the rules and your situation. "
            "Please confirm with a qualified professional before filing.")


# Kept as a module attribute for tests / callers that want the base text.
DISCLAIMER = ("This organises the medical spending you logged for the financial year. "
              "It is not tax advice and not a deduction calculation — whether any of it "
              "is eligible, and how much, depends on the rules and your situation. "
              "Please confirm with a qualified professional before filing.")


def fy_of(iso_date, start_month=None):
    """The financial-year START year for a date, given the FY start month
    (defaults to the user's country's)."""
    if start_month is None:
        start_month = _fy_start_month()
    d = dt.date.fromisoformat(str(iso_date)[:10])
    return d.year if d.month >= start_month else d.year - 1


def _fy_bounds(fy, start_month=None):
    if start_month is None:
        start_month = _fy_start_month()
    start = dt.date(fy, start_month, 1)
    end = dt.date(fy + 1, start_month, 1) - dt.timedelta(days=1) if start_month > 1 \
        else dt.date(fy, 12, 31)
    return start.isoformat(), end.isoformat()


def _fy_label(fy, start_month=None):
    if start_month is None:
        start_month = _fy_start_month()
    return str(fy) if start_month == 1 else f"{fy}–{str(fy + 1)[2:]}"   # 2025 vs 2025–26


def financial_years():
    """FYs the user has any expense in, newest first, always including the current FY."""
    uid = current_user_id()
    rows = execute("SELECT DISTINCT date_key FROM health_expenses WHERE user_id=?", (uid,), fetchall=True) or []
    years = {fy_of(r['date_key']) for r in rows if r['date_key']}
    years.add(fy_of(user_today()))
    out = sorted(years, reverse=True)
    return [{'fy': y, 'label': _fy_label(y)} for y in out]


def get_tax_summary(fy):
    """One financial year's medical spend, organised. Descriptive only."""
    uid = current_user_id()
    try:
        fy = int(fy)
    except (TypeError, ValueError):
        fy = fy_of(user_today())
    start, end = _fy_bounds(fy)

    rows = execute("""SELECT category, SUM(amount) amt, SUM(covered) cov, COUNT(*) n
                      FROM health_expenses WHERE user_id=? AND date_key BETWEEN ? AND ?
                      GROUP BY category""", (uid, start, end), fetchall=True) or []
    categories, total, covered = [], 0.0, 0.0
    insurance_premiums = 0.0
    for r in rows:
        amt = round(r['amt'] or 0, 2)
        cov = round(r['cov'] or 0, 2)
        total += amt
        covered += cov
        if r['category'] == 'insurance':
            insurance_premiums += amt
        categories.append({
            'key': r['category'], 'label': _CAT_LABEL.get(r['category'], 'Other'),
            'amount': amt, 'covered': cov, 'net': round(amt - cov, 2), 'n': int(r['n'] or 0),
        })
    categories.sort(key=lambda c: -c['amount'])

    # Claims submitted within the FY (by submission date).
    cl = execute("""SELECT SUM(amount) claimed, SUM(reimbursed) reimb, COUNT(*) n
                    FROM claims WHERE user_id=? AND date_submitted BETWEEN ? AND ?""",
                 (uid, start, end), fetchone=True) or {}
    claimed = round(cl['claimed'] or 0, 2) if cl else 0.0
    reimb = round(cl['reimb'] or 0, 2) if cl else 0.0

    return {
        'fy': fy, 'label': _fy_label(fy), 'start': start, 'end': end,
        'currency': currency_of(),
        'categories': categories,
        'total': round(total, 2),
        'covered': round(covered, 2),
        'out_of_pocket': round(total - covered, 2),
        'insurance_premiums': round(insurance_premiums, 2),
        'other_medical': round(total - insurance_premiums, 2),
        'claims': {'claimed': claimed, 'reimbursed': reimb,
                   'outstanding': round(claimed - reimb, 2), 'n': int(cl['n'] or 0) if cl else 0},
        'has_data': bool(categories),
        'disclaimer': _disclaimer(),
    }


def tax_csv_rows(fy):
    """Itemised expense rows for the FY, oldest first — the accountant's worksheet."""
    uid = current_user_id()
    try:
        fy = int(fy)
    except (TypeError, ValueError):
        fy = fy_of(user_today())
    start, end = _fy_bounds(fy)
    rows = execute("""SELECT date_key, category, description, amount, covered
                      FROM health_expenses WHERE user_id=? AND date_key BETWEEN ? AND ?
                      ORDER BY date_key""", (uid, start, end), fetchall=True) or []
    ccy = currency_of()['code']
    out = [['Date', 'Category', 'Description', f'Amount ({ccy})', f'Reimbursed ({ccy})', f'Net ({ccy})']]
    for r in rows:
        amt = round(r['amount'] or 0, 2)
        cov = round(r['covered'] or 0, 2)
        out.append([r['date_key'], _CAT_LABEL.get(r['category'], 'Other'),
                    r['description'] or '', f"{amt:.2f}", f"{cov:.2f}", f"{amt - cov:.2f}"])
    return out, _fy_label(fy)
