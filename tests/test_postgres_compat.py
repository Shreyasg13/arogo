"""Static guards for the SQLite/PostgreSQL differences that pass silently.

PostgreSQL is the documented production backend, but almost every test runs on
SQLite. The dangerous incompatibilities are the ones where SQLite is *more*
forgiving: the code works, the tests are green, and it fails only on the machine
that holds the real data.

These checks run on both engines and need no server, so they catch the mistake
at the point it is written rather than in production. They complement the
PostgreSQL CI job — they are not a substitute for it.
"""
import ast
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {'__pycache__', '.git', 'node_modules', '.github', 'venv', '.venv'}


def _py_files(include_tests=False):
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if not include_tests and os.path.basename(root) == 'tests':
            continue
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(root, f)


def _tree(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        return ast.parse(fh.read(), filename=path)


def _rel(path):
    return os.path.relpath(path, ROOT).replace('\\', '/')


SQL_KEYWORD = re.compile(r'\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b', re.I)


def _literal_parts(node):
    """Every string literal reachable inside an expression — the constant parts
    of an f-string and of a concatenation included."""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append((n.lineno, n.value))
    return out


def _sql_literals(path):
    """(lineno, text) for strings that actually reach the database.

    Deliberately narrow: matching any string that merely contains the word
    SELECT sweeps up every module docstring that documents its routes, and a
    guard that cries wolf gets deleted. So this looks only at arguments to
    execute()/executemany() plus the module-level SCHEMA/SQL constants that are
    split and executed at init.
    """
    tree = _tree(path)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if name in ('execute', 'executemany') and node.args:
                out.extend(_literal_parts(node.args[0]))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                nm = getattr(tgt, 'id', '') or ''
                if nm.isupper() and ('SCHEMA' in nm or 'SQL' in nm):
                    # What reaches the database is the comment-stripped text —
                    # db.core._schema_statements drops `--` lines before
                    # splitting, so a ? or % inside prose never becomes SQL.
                    for lineno, text in _literal_parts(node.value):
                        stripped = '\n'.join(
                            ln for ln in text.splitlines()
                            if not ln.lstrip().startswith('--'))
                        out.append((lineno, stripped))
    return [(ln, s) for ln, s in out if SQL_KEYWORD.search(s)]


# ── A failed statement inside a transaction poisons the whole transaction ───

def _calls_execute(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            name = getattr(fn, 'id', None) or getattr(fn, 'attr', None)
            if name in ('execute', 'executemany'):
                return True
    return False


def _uses_savepoint(node):
    for n in ast.walk(node):
        if isinstance(n, ast.With):
            for item in n.items:
                fn = item.context_expr
                if isinstance(fn, ast.Call):
                    name = getattr(fn.func, 'id', None) or getattr(fn.func, 'attr', None)
                    if name == 'savepoint':
                        return True
    return False


def test_no_bare_try_execute_inside_a_transaction():
    """try: execute(...) / except: continue works on SQLite and destroys the rest
    of the batch on PostgreSQL, which aborts the entire transaction on any
    statement error. Inside a transaction() the recoverable form is savepoint().

    This is not hypothetical: the restore path shipped with exactly this shape,
    so one malformed row in a backup would have skipped every row after it —
    while the SQLite tests stayed green.
    """
    offenders = []
    for path in _py_files():
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.With):
                continue
            opens_tx = any(
                isinstance(i.context_expr, ast.Call)
                and (getattr(i.context_expr.func, 'id', None)
                     or getattr(i.context_expr.func, 'attr', None)) == 'transaction'
                for i in node.items)
            if not opens_tx:
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Try) and _calls_execute(inner) \
                        and not _uses_savepoint(inner):
                    offenders.append(f"{_rel(path)}:{inner.lineno}")
    assert not offenders, (
        "a try/except around execute() inside transaction() silently loses every "
        "later statement on PostgreSQL — wrap the statement in savepoint() "
        "instead: " + ", ".join(offenders))


# ── The ?→%s rewrite ────────────────────────────────────────────────────────

def test_no_sql_literal_contains_a_percent_sign():
    """db.core._adapt rewrites ? to %s for psycopg2, which then %-formats the
    string. A literal % in the SQL — most naturally a LIKE pattern written
    inline — becomes a format spec and the query raises. Pass the pattern as a
    bound parameter instead."""
    offenders = []
    for path in _py_files():
        for lineno, sql in _sql_literals(path):
            if '%' in sql:
                offenders.append(f"{_rel(path)}:{lineno}")
    assert not offenders, (
        "a literal % in SQL breaks under psycopg2's formatting — bind it as a "
        "parameter (LIKE ?) instead: " + ", ".join(offenders))


def test_no_sql_literal_contains_a_bare_question_mark_outside_a_placeholder():
    """_adapt does a blind ? → %s replace, so a question mark that is NOT a
    placeholder (in a LIKE pattern or a default string) would be corrupted."""
    offenders = []
    for path in _py_files():
        for lineno, sql in _sql_literals(path):
            # A placeholder ? is always adjacent to SQL punctuation or whitespace.
            for m in re.finditer(r'\?', sql):
                before = sql[m.start() - 1] if m.start() else ' '
                after = sql[m.end()] if m.end() < len(sql) else ' '
                if before.isalnum() or after.isalnum():
                    offenders.append(f"{_rel(path)}:{lineno}")
                    break
    assert not offenders, (
        "a ? that isn't a placeholder gets rewritten to %s on PostgreSQL: "
        + ", ".join(offenders))


# ── SQL that only SQLite understands ────────────────────────────────────────

SQLITE_ONLY = {
    'INSERT OR REPLACE': 'use an explicit UPDATE/INSERT or ON CONFLICT',
    'INSERT OR IGNORE': 'use ON CONFLICT DO NOTHING',
    'AUTOINCREMENT': 'PostgreSQL has no AUTOINCREMENT',
    'IFNULL(': 'use COALESCE()',
    'GROUP_CONCAT(': 'PostgreSQL spells this string_agg()',
    'julianday(': 'no PostgreSQL equivalent',
    "datetime('now'": 'compute the timestamp in Python instead',
    "date('now'": 'compute the date in Python instead',
}


def test_no_sqlite_only_sql():
    offenders = []
    for path in _py_files():
        for node in ast.walk(_tree(path)):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            upper = node.value.upper()
            for frag, why in SQLITE_ONLY.items():
                if frag.upper() in upper:
                    offenders.append(f"{_rel(path)}:{node.lineno} — {frag} ({why})")
    assert not offenders, "SQLite-only SQL: " + "; ".join(offenders)


def test_pragma_is_confined_to_db_core():
    """PRAGMA is meaningless on PostgreSQL, and a failed statement there aborts
    the surrounding transaction. db/core.py owns the one guarded fallback to
    information_schema; nothing else should reach for it."""
    offenders = []
    for path in _py_files():
        rel = _rel(path)
        if rel == 'db/core.py':
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and 'PRAGMA ' in node.value.upper():
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "call db.core.table_columns() rather than PRAGMA directly: "
        + ", ".join(offenders))


# ── The backend switch itself ───────────────────────────────────────────────

def test_adapt_rewrites_placeholders_only_for_postgres():
    import db.core as core
    sql = "SELECT * FROM t WHERE a=? AND b=?"
    was = core.IS_POSTGRES
    try:
        core.IS_POSTGRES = False
        assert core._adapt(sql) == sql
        core.IS_POSTGRES = True
        assert core._adapt(sql) == "SELECT * FROM t WHERE a=%s AND b=%s"
    finally:
        core.IS_POSTGRES = was


def test_table_columns_answers_for_a_real_table():
    """Whichever backend is running, this must return real column names — it
    gates which fields a restore will write."""
    from db.core import init_db, table_columns
    init_db()
    cols = table_columns('medicines')
    assert {'id', 'name', 'user_id'} <= cols, cols
    assert table_columns('definitely_not_a_table_xyz') == set()
