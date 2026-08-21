"""routes/expenses.py — out-of-pocket health spending.

GET    /api/expenses?month=YYYY-MM  — a month's expenses + derived summary
POST   /api/expenses                — log {category, amount, date_key, description, covered, notes}
DELETE /api/expenses/<eid>          — remove one
GET    /api/expenses/trend          — net out-of-pocket, last few months
GET    /api/expenses/meta           — category list (for the picker)
"""
import csv, io
from flask import Blueprint, request, jsonify, make_response
from auth import require_auth
from db.expenses import log_expense, delete_expense, get_month, recent_months, CATEGORIES
from db.food import get_user_timezone
from db.core import today_iso

bp = Blueprint('expenses', __name__)


@bp.route('/api/tax-summary')
@require_auth
def api_tax_summary():
    """Organise a financial year's medical spend (Apr–Mar) for tax/reimbursement.
    An organiser of your own logged data — NOT tax advice (see disclaimer)."""
    from db.tax_summary import get_tax_summary, financial_years
    fy = request.args.get('fy')
    return jsonify({'summary': get_tax_summary(fy) if fy else get_tax_summary(None),
                    'years': financial_years()})


@bp.route('/api/tax-summary/csv')
@require_auth
def api_tax_summary_csv():
    """Itemised expense worksheet for the financial year, as a CSV download."""
    from db.tax_summary import tax_csv_rows
    rows, label = tax_csv_rows(request.args.get('fy'))
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    resp = make_response(buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="arogo-medical-spend-FY{label}.csv"'
    return resp


@bp.route('/api/expenses')
@require_auth
def api_expenses_month():
    month = request.args.get('month') or today_iso(get_user_timezone())[:7]
    try:
        return jsonify(get_month(month))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/expenses', methods=['POST'])
@require_auth
def api_expenses_add():
    d = request.json or {}
    try:
        e = log_expense(d.get('category', 'other'), d.get('amount'),
                        d.get('date_key', today_iso(get_user_timezone())),
                        d.get('description', ''), d.get('covered', 0), d.get('notes', ''))
        return jsonify({'success': True, 'expense': e})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/expenses/<eid>', methods=['DELETE'])
@require_auth
def api_expenses_delete(eid):
    delete_expense(eid)
    return jsonify({'success': True})


@bp.route('/api/expenses/trend')
@require_auth
def api_expenses_trend():
    return jsonify({'months': recent_months(6)})


@bp.route('/api/expenses/meta')
@require_auth
def api_expenses_meta():
    return jsonify({'categories': CATEGORIES})
