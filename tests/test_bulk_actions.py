"""Bulk selection on the lists that have it, and the rules that keep it safe.

Bulk delete is the most destructive control in the app: one click can remove
twenty health records. Two properties make that acceptable, and both are
asserted here rather than assumed.

  Everything a bulk action can delete goes to the trash first. A list that
  offers "delete selected" against a table with no undo would be a trap.

  The result is counted from the responses, not from how many rows were ticked.
  Reporting "20 deleted" when three requests failed is the specific lie this
  app spends most of its effort not telling.

These are static checks against app.js. They cannot prove the browser wires it
up — that was verified by driving the real page — but they do prove the shape
is right, and they fail if someone adds bulk delete to a list whose rows cannot
be recovered.
"""
import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, 'static', 'js', 'app.js')
INDEX = os.path.join(ROOT, 'templates', 'index.html')


def js():
    return io.open(APP_JS, encoding='utf-8').read()


# scope → (the table its ids belong to, the function that renders the list)
BULK_LISTS = {
    'trash': ('deleted_items', 'loadTrash'),
    'reports': ('reports', 'loadReports'),
    'symptoms': ('symptoms', 'loadSymptoms'),
    'vitals': ('vitals', 'loadVitals'),
}

TOP_LEVEL = re.compile(r'^(async function |function |const |let )')


def _function_body(name):
    lines = js().split('\n')
    pat = re.compile(r'^(?:async )?function ' + re.escape(name) + r'\s*\(')
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    assert start is not None, f'{name} does not exist'
    end = next((j for j in range(start + 1, len(lines))
                if TOP_LEVEL.match(lines[j])), len(lines))
    return '\n'.join(lines[start:end])


# ── Each list is wired up completely ────────────────────────────────────────

@pytest.mark.parametrize('scope', sorted(BULK_LISTS))
def test_the_list_renders_a_checkbox_per_row(scope):
    body = _function_body(BULK_LISTS[scope][1])
    assert f"bulkCheckbox('{scope}'" in body, (
        f'{scope} has no per-row checkbox, so nothing can be selected')


@pytest.mark.parametrize('scope', sorted(BULK_LISTS))
def test_the_list_renders_an_action_bar_and_select_all(scope):
    body = _function_body(BULK_LISTS[scope][1])
    # reports renders its bar into a sibling container, because reports-grid is
    # a CSS grid and a bar inside it would be laid out as another card.
    assert f"bulkBar('{scope}'" in body, f'{scope} has no action bar'
    assert f"bulkToggleAll('{scope}'" in body, f'{scope} has no select-all'


@pytest.mark.parametrize('scope', sorted(BULK_LISTS))
def test_the_bar_state_is_restored_after_a_re_render(scope):
    """Without this the bar vanishes the moment the list reloads, while the
    selection is still live — the user sees nothing selected and a stale set
    underneath."""
    body = _function_body(BULK_LISTS[scope][1])
    assert f"_bulkRefresh('{scope}')" in body, (
        f'{scope} never re-syncs its bar after rendering')


# ── Nothing bulk-deletable is unrecoverable ─────────────────────────────────

def _trashable_tables():
    import db.trash as trash
    return {t.table for t in trash.TRASHABLE}


@pytest.mark.parametrize('scope', sorted(BULK_LISTS))
def test_everything_a_bulk_action_deletes_can_be_recovered(scope):
    """The property that makes a one-click multi-delete acceptable at all."""
    table = BULK_LISTS[scope][0]
    if scope == 'trash':
        pytest.skip('the trash IS the recovery step; purging from it is final '
                    'by definition and says so')
    assert table in _trashable_tables(), (
        f'{scope} offers bulk delete but {table} rows do not go to the trash — '
        f'that makes it a one-click unrecoverable delete')


# ── Honest reporting ────────────────────────────────────────────────────────

def test_bulk_run_counts_responses_not_ticks():
    body = _function_body('bulkRun')
    assert 'failed++' in body, 'bulkRun does not track failures'
    # The success count must come from the per-item result, never from ids.length
    assert 'ids.length' not in body.split('bulkClear')[-1], (
        'the reported count is taken from how many rows were ticked')
    assert 'could not be' in body, 'a partial failure is not reported'


@pytest.mark.parametrize('fn', ['bulkDeleteReports', 'bulkDeleteSymptoms',
                                'bulkDeleteVitals'])
def test_each_bulk_delete_reports_per_item_success(fn):
    """`.then(r => r.ok)` is what makes the count real — without it every
    request "succeeds", including the ones that 404."""
    body = _function_body(fn)
    assert 'r.ok' in body, f'{fn} treats any response as a success'
    assert 'bulkRun(' in body


@pytest.mark.parametrize('fn', ['bulkDeleteReports', 'bulkDeleteSymptoms',
                                'bulkDeleteVitals'])
def test_each_bulk_delete_refreshes_what_it_changed(fn):
    """A list that still shows deleted rows invites a second delete."""
    body = _function_body(fn)
    assert re.search(r'load\w+\(\)', body), f'{fn} refreshes nothing'


@pytest.mark.parametrize('fn', ['bulkDeleteReports', 'bulkDeleteSymptoms',
                                'bulkDeleteVitals'])
def test_ids_are_encoded_into_the_url(fn):
    body = _function_body(fn)
    assert 'encodeURIComponent' in body, f'{fn} puts a raw id in a URL'


# ── The record cards ────────────────────────────────────────────────────────

def test_the_record_checkbox_does_not_open_the_record():
    """A report card is itself a click surface that opens the detail view, so a
    checkbox inside it has to stop the click before it gets there."""
    body = _function_body('loadReports')
    m = re.search(r'report-card-pick[^>]*>', body)
    assert m, 'the record checkbox wrapper is gone'
    assert 'event.stopPropagation()' in m.group(0)


def test_the_checkbox_wrapper_stays_out_of_the_accessibility_tree():
    """_a11yEnhance turns anything with data-ev-click into a role="button"
    unless it already has a role. The wrapper is not a control; the checkbox
    inside it is."""
    body = _function_body('loadReports')
    m = re.search(r'report-card-pick[^>]*>', body)
    assert 'role="presentation"' in m.group(0)


def test_the_record_bar_is_rendered_outside_the_grid():
    """reports-grid is a CSS grid — a bar rendered inside it becomes a cell."""
    raw = io.open(INDEX, encoding='utf-8').read()
    assert 'id="reports-bulk"' in raw
    bulk_at = raw.index('id="reports-bulk"')
    grid_at = raw.index('id="reports-grid"')
    assert bulk_at < grid_at, 'the bulk bar should sit above the grid'


def test_an_empty_record_list_clears_its_bar():
    """Otherwise a filter that matches nothing leaves "3 selected" hanging over
    an empty grid, acting on rows that are no longer shown."""
    body = _function_body('loadReports')
    empty_branch = body[body.index('reports.length === 0'):]
    assert "bulkBox.innerHTML = ''" in empty_branch[:600]
