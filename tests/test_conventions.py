"""
tests/test_conventions.py — Security headers, PWA routes, and codebase
regression guards.

The guards encode decisions that are easy to accidentally undo months
later: the strict CSP (no inline handlers), undo-toasts-not-confirm(),
portable SQL, and the Arogo rename. A failure here means a convention
was broken, not that a feature is buggy.

Run:  pytest tests/test_conventions.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import re
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
from db.core import init_db
from app import create_app


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def _read(relpath):
    with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _code_lines(relpath):
    """Source lines with //-comments stripped (crude but effective)."""
    for i, line in enumerate(_read(relpath).splitlines(), 1):
        yield i, line.split("//")[0]


# ── Security headers ───────────────────────────────────────────────────────────

class TestSecurityHeaders:
    def test_csp_present_and_strict(self, client):
        csp = client.get("/").headers.get("Content-Security-Policy", "")
        assert csp, "CSP header missing"
        script_src = next((p for p in csp.split(";") if "script-src" in p), "")
        assert "'unsafe-inline'" not in script_src, \
            "script-src regained 'unsafe-inline' — the CSP refactor is being undone"
        assert "'self'" in script_src

    def test_basic_headers(self, client):
        h = client.get("/").headers
        assert h.get("X-Frame-Options") == "SAMEORIGIN"
        assert h.get("X-Content-Type-Options") == "nosniff"
        assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_no_hsts_in_dev(self, client):
        # HSTS must only appear together with COOKIE_SECURE=1 (HTTPS)
        assert "Strict-Transport-Security" not in client.get("/").headers


# ── PWA plumbing ───────────────────────────────────────────────────────────────

class TestPwaRoutes:
    def test_service_worker_served_from_root(self, client):
        r = client.get("/sw.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("Content-Type", "")
        assert b"addEventListener" in r.data

    def test_manifest(self, client):
        r = client.get("/static/manifest.json")
        assert r.status_code == 200
        assert r.get_json()["short_name"] == "Arogo"

    def test_icons_exist(self, client):
        for icon in ["icon-192.png", "icon-512.png", "icon-512-maskable.png"]:
            assert client.get(f"/static/icons/{icon}").status_code == 200, icon


# ── Test-isolation hygiene ──────────────────────────────────────────────────────

class TestNoSharedTestEmails:
    def test_no_email_reused_across_test_files(self):
        """Every test file shares one in-memory DB per xdist worker, so a fixture
        email used in two files means the second registration hits a duplicate,
        leaves that client unauthenticated, and the test flakes with a 401 only
        under parallel load (passing serially). This bit the suite repeatedly
        (cal*/meas*/tl*/exp1@). Keep every @medeasy.{test,local} address to a
        single file so the flake class can't return."""
        import glob
        pat = re.compile(r'[A-Za-z0-9_.+-]+@medeasy\.(?:test|local)')
        owners = {}
        clashes = []
        for path in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
            fname = os.path.basename(path)
            for email in set(pat.findall(_read("tests/" + fname))):
                if email in owners and owners[email] != fname:
                    clashes.append(f"{email}: {owners[email]} + {fname}")
                owners.setdefault(email, fname)
        assert not clashes, ("test-fixture emails reused across files (parallel-run "
                             "flake risk — give each file a unique prefix):\n" + "\n".join(sorted(clashes)))


# ── Route-map hygiene ───────────────────────────────────────────────────────────

class TestNoDuplicateRoutes:
    def test_no_duplicate_path_method(self, app):
        """No two blueprints may register the same (path, method): the loser is
        dead code and the two handlers can silently diverge (the bug that left a
        fabricated height_cm=170 fallback shadowing the honest body-metrics
        handler). Regression guard for the 2026-08 route-dedup cleanup."""
        seen = {}
        dupes = []
        for rule in app.url_map.iter_rules():
            for method in (rule.methods or set()) - {"HEAD", "OPTIONS"}:
                key = (rule.rule, method)
                if key in seen and seen[key] != rule.endpoint:
                    dupes.append(f"{method} {rule.rule}: {seen[key]} vs {rule.endpoint}")
                seen[key] = rule.endpoint
        assert not dupes, "Duplicate route registrations (one is dead code):\n" + "\n".join(dupes)


# ── Codebase regression guards ─────────────────────────────────────────────────

FRONTEND_FILES = ["templates/index.html", "templates/oauth_result.html",
                  "static/js/app.js"]
PY_SQL_DIRS = ["db", "routes"]


def _py_files(*dirs):
    for d in dirs:
        for name in os.listdir(os.path.join(ROOT, d)):
            if name.endswith(".py"):
                yield f"{d}/{name}"


class TestConventions:
    def test_no_inline_event_handlers(self):
        """Strict CSP: on*= attributes are dead on arrival — use data-ev-*.
        Covers error/load/focus/blur/mouse* too: an inline onerror fallback
        silently never fires under CSP (was the case on the Garmin logo)."""
        pat = re.compile(
            r'\bon(?:click|change|input|keydown|keyup|submit|load|dblclick|'
            r'error|focus|blur|mouseover|mouseout|mouseenter|mouseleave)\s*=\s*["\']')
        offenders = []
        for f in FRONTEND_FILES:
            for i, line in enumerate(_read(f).splitlines(), 1):
                if pat.search(line):
                    offenders.append(f"{f}:{i}")
        assert not offenders, f"inline handlers found (CSP blocks them): {offenders}"

    def test_no_inline_script_blocks(self):
        """<script> without src is blocked by script-src 'self'."""
        for f in ["templates/index.html", "templates/oauth_result.html"]:
            for m in re.finditer(r"<script\b([^>]*)>", _read(f)):
                assert "src=" in m.group(1), f"inline <script> block in {f}"

    def test_no_confirm_dialogs(self):
        """Destructive actions use undoable(), not browser confirm()."""
        offenders = [f"static/js/app.js:{i}"
                     for i, code in _code_lines("static/js/app.js")
                     if re.search(r"[^.\w]confirm\(", code)]
        assert not offenders, f"confirm() found — use undoable(): {offenders}"

    def test_portable_sql_only(self):
        """SQLite-isms break the PostgreSQL backend."""
        bad = re.compile(r"INSERT\s+OR\s+(REPLACE|IGNORE)", re.I)
        offenders = []
        for f in _py_files(*PY_SQL_DIRS):
            src = _read(f)
            if bad.search(src):
                offenders.append(f + " (INSERT OR ...)")
            if "PRAGMA" in src and f != "db/core.py":
                offenders.append(f + " (PRAGMA outside db/core)")
        assert not offenders, f"non-portable SQL: {offenders}"

    def test_no_linux_only_strftime(self):
        """strftime('%-d') raises on Windows — build day numbers manually."""
        pat = re.compile(r"strftime\([^)]*%-")
        offenders = [f for f in list(_py_files("db", "routes")) + ["app.py", "scheduler.py"]
                     if pat.search(_read(f))]
        assert not offenders, f"Linux-only strftime format: {offenders}"

    def test_no_mediscan_references(self):
        """The rename is done — don't let the old name creep back."""
        pat = re.compile(r"medi?scan", re.I)
        skip_dirs = {".git", "__pycache__", "uploads", "docs", ".claude",
                     "node_modules", ".pytest_cache", "static"}
        offenders = []
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                if not name.endswith((".py", ".html", ".js", ".md", ".yml", ".json", ".css")):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, ROOT)
                if rel.endswith(".local.md") or rel.endswith("test_conventions.py"):
                    continue
                with open(path, encoding="utf-8", errors="ignore") as f:
                    if pat.search(f.read()):
                        offenders.append(rel)
        assert not offenders, f"MediScan reference resurfaced: {offenders}"

    def test_db_functions_scope_by_user(self):
        """Spot-check: SELECTs on per-user tables must filter by user_id."""
        # Regression guard for Phase 2 — checks the highest-risk tables.
        # Source is normalized (quotes/newlines stripped) so multi-line
        # f-string SQL is seen as one statement.
        for table in ["food_logs", "sleep_logs", "medicines", "thoughts", "vitals",
                      "sync_log", "notification_log", "hydration_logs"]:
            for f in _py_files("db"):
                norm = re.sub(r"['\"\n]", " ", _read(f))
                for m in re.finditer(r"FROM\s+%s\b" % table, norm):
                    window = norm[m.start():m.start() + 300]
                    assert "user_id" in window or "WHERE id=" in window, \
                        f"{f}: unscoped query on {table}: …{window[:90]}"


class TestAccessibility:
    """Guards for the accessibility baseline so a later edit can't silently
    strip the skip link, landmarks, reduced-motion handling, or the CSS hooks
    the a11y layer depends on."""

    def test_skip_link_targets_main(self):
        html = _read("templates/index.html")
        assert 'class="skip-link"' in html, "skip link removed"
        assert 'href="#app-main"' in html, "skip link must target #app-main"
        assert 'id="app-main"' in html, "main landmark #app-main missing"

    def test_sr_only_utility_defined(self):
        css = _read("static/css/style.css")
        assert re.search(r"\.sr-only\s*\{", css), ".sr-only utility missing"
        assert re.search(r"\.skip-link\s*\{", css), ".skip-link styles missing"

    def test_landmarks_are_labelled(self):
        html = _read("templates/index.html")
        # The primary nav must carry an accessible name (two navs otherwise clash).
        assert re.search(r'<nav class="sidebar-nav"[^>]*aria-label=', html), \
            "primary nav needs aria-label"
        assert re.search(r'<nav class="mobile-tabbar"[^>]*aria-label=', html), \
            "mobile tabbar needs aria-label"

    def test_active_nav_marks_aria_current(self):
        """switchView must set aria-current on the active nav item (and the
        default dashboard item ships marked)."""
        html = _read("templates/index.html")
        assert 'aria-current="page"' in html, "no default aria-current on dashboard nav"
        js = _read("static/js/app.js")
        assert "setAttribute('aria-current'" in js, "switchView doesn't set aria-current"

    def test_global_reduced_motion(self):
        css = _read("static/css/style.css")
        assert "prefers-reduced-motion" in css, "no reduced-motion handling"
        # Must be the app-wide guard, not only the two scoped Q1 blocks.
        assert re.search(r"prefers-reduced-motion:\s*reduce\s*\)\s*\{\s*\*", css), \
            "reduced-motion must apply app-wide (*, *::before, *::after)"

    def test_keyboard_bridge_present(self):
        """Non-native click surfaces get button semantics + an Enter/Space
        activation bridge — the a11y layer's core keyboard fix."""
        js = _read("static/js/app.js")
        assert "_a11yEnhance" in js, "a11y enhancer removed"
        assert "role" in js and "'button'" in js, "no role=button assignment"
        assert "_evRun(el.getAttribute('data-ev-click')" in js, \
            "Enter/Space → click bridge missing"


class TestPrint:
    """Guards the shared print baseline so a later edit can't send the app's
    printables (binder, visit summary, doctor letters) back to messy pages."""

    def test_shared_print_baseline(self):
        css = _read("static/css/style.css")
        assert "@page" in css, "no @page margin — printables lose page setup"
        assert ".no-print" in css, "no .no-print utility"
        # Chrome must be dropped on paper.
        assert re.search(r"@media print\b", css)
        assert ".quick-fab" in css and ".sidebar" in css, "print CSS must hide app chrome"

    def test_visit_print_isolate(self):
        css = _read("static/css/style.css")
        assert "printing-visit" in css, "per-visit print isolate rule missing"
        assert ".print-doc" in css, "printable doc shell styles missing"
        js = _read("static/js/app.js")
        assert "printVisitSummary" in js, "visit print function removed"
