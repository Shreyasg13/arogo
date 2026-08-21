"""
db/tax_summary.py — a medical-spend organizer for tax & reimbursement.

India-first: Section 80D lets people claim health-insurance premiums and some
medical spend, and every March people scramble to total their year's receipts.
This ORGANIZES the expenses you already logged into an Indian financial year
(Apr–Mar), grouped by category, with net out-of-pocket and reimbursement status,
and an itemised CSV to hand to an accountant.

HONESTY — this is NOT tax advice and NOT a deduction calculation. It only sums
what you logged; whether any of it is deductible, and how much, depends on the
rules and your situation. We never assert an eligible amount, never tell you what
to claim, and always say to confirm with a professional. No financial advice.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, user_today

_CAT_LABEL = {
    'medicines': 'Medicines', 'consultation': 'Consultations', 'lab': 'Lab tests',
    'hospital': 'Hospital', 'insurance': 'Insurance premium', 'other': 'Other',
}

DISCLAIMER = ("This organises the medical spending you logged for the financial year. "
              "It is not tax advice and not a deduction calculation — whether any of it "
              "is eligible under Section 80D, and how much, depends on the rules and your "
              "situation. Please confirm with a qualified professional before filing.")


def fy_of(iso_date):
    """The Indian financial-year START year for a date (FY runs Apr 1 – Mar 31)."""
    d = dt.date.fromisoformat(str(iso_date)[:10])
    return d.year if d.month >= 4 else d.year - 1


def _fy_bounds(fy):
    return f"{fy}-04-01", f"{fy + 1}-03-31"


def _fy_label(fy):
    return f"{fy}–{str(fy + 1)[2:]}"       # e.g. 2025–26


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
        'categories': categories,
        'total': round(total, 2),
        'covered': round(covered, 2),
        'out_of_pocket': round(total - covered, 2),
        'insurance_premiums': round(insurance_premiums, 2),
        'other_medical': round(total - insurance_premiums, 2),
        'claims': {'claimed': claimed, 'reimbursed': reimb,
                   'outstanding': round(claimed - reimb, 2), 'n': int(cl['n'] or 0) if cl else 0},
        'has_data': bool(categories),
        'disclaimer': DISCLAIMER,
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
    out = [['Date', 'Category', 'Description', 'Amount (INR)', 'Reimbursed (INR)', 'Net (INR)']]
    for r in rows:
        amt = round(r['amount'] or 0, 2)
        cov = round(r['covered'] or 0, 2)
        out.append([r['date_key'], _CAT_LABEL.get(r['category'], 'Other'),
                    r['description'] or '', f"{amt:.2f}", f"{cov:.2f}", f"{amt - cov:.2f}"])
    return out, _fy_label(fy)
