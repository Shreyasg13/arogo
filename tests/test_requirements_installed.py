"""The test run must be the run CI does.

A QR-code bug shipped and stayed invisible for weeks because of a gap this file
closes. `segno` is an optional dependency: it wasn't installed on the dev
machine, so the only test covering the QR called importorskip and skipped, the
pre-commit hook went green, and CI — which installs everything in
requirements.txt — failed on every push. The code passed a StringIO to a library
that writes bytes, and nothing local could ever have noticed.

Optional at RUNTIME is not optional for TESTING. The app degrading gracefully
without segno is a deliberate feature; a developer's test run silently covering
less than CI's is not.

So: if requirements.txt declares it, it has to be installed here too. The failure
message names what is missing and the one command that fixes it.
"""
import re

import pytest

try:
    from importlib import metadata as _md
except ImportError:                                   # pragma: no cover
    import importlib_metadata as _md                  # type: ignore

REQUIREMENTS = "requirements.txt"

# Declared in requirements.txt but deliberately not required for a test run,
# each with the reason. Kept short: every entry here is a hole in the guarantee
# above, so "it was inconvenient" is not a reason.
NOT_NEEDED_FOR_TESTS = {
    # A Linux WSGI server that needs fcntl, so it cannot install on Windows at
    # all. It imports the app rather than the other way round — nothing in this
    # repo imports gunicorn — so its absence changes no code path under test.
    "gunicorn": "production WSGI server; never imported, and unavailable on Windows",
}


def _declared():
    """Distribution names from requirements.txt, ignoring comments, blank lines,
    version specifiers, and lines whose environment marker excludes this Python."""
    import os
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []
    with open(os.path.join(root, REQUIREMENTS), encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            # Environment markers, e.g. `; python_version >= "3.10"`. Evaluated
            # crudely on purpose — only python_version is used in this file, and
            # a real marker parser would be a dependency of its own.
            if ";" in line:
                spec, marker = line.split(";", 1)
                m = re.search(r'python_version\s*(>=|<=|<|>|==)\s*"([\d.]+)"', marker)
                if m:
                    op, want = m.group(1), tuple(int(x) for x in m.group(2).split("."))
                    cur = sys.version_info[:len(want)]
                    ok = {">=": cur >= want, "<=": cur <= want, "<": cur < want,
                          ">": cur > want, "==": cur == want}[op]
                    if not ok:
                        continue
                line = spec.strip()
            name = re.split(r"[<>=!~\[]", line, 1)[0].strip()
            if name:
                out.append(name)
    return sorted(set(out))


def test_every_declared_dependency_is_installed():
    """Missing packages mean this machine is testing less code than CI is.

    Checked by DISTRIBUTION name via importlib.metadata rather than by trying to
    import a guessed module name — `psycopg2-binary` imports as `psycopg2`,
    `Pillow` as `PIL`, and `tzdata` isn't importable at all.
    """
    missing = []
    for name in _declared():
        if name in NOT_NEEDED_FOR_TESTS:
            continue
        try:
            _md.distribution(name)
        except _md.PackageNotFoundError:
            missing.append(name)
    assert not missing, (
        "these are in requirements.txt but not installed here, so your test run "
        "covers less code than CI's and an optional-dependency bug can pass "
        "locally and fail on push:\n    "
        + " ".join(missing)
        + "\n  fix with:  python -m pip install -r requirements.txt"
    )


def test_every_exemption_states_a_reason():
    """Each entry is a hole in the guarantee above, so it has to be argued for."""
    vague = sorted(k for k, v in NOT_NEEDED_FOR_TESTS.items()
                   if len(str(v).strip()) < 25)
    assert not vague, f"these exemptions need a real reason: {vague}"


def test_the_qr_dependency_specifically_is_present():
    """Named on its own because this is the one that actually bit.

    With segno absent the QR test skips, which reads as a pass in the summary
    line and is the reason a broken QR survived several releases.
    """
    pytest.importorskip  # noqa: B018 - referenced to make the contrast explicit
    try:
        _md.distribution("segno")
    except _md.PackageNotFoundError:
        pytest.fail(
            "segno is not installed, so the emergency-QR test will skip and its "
            "coverage is imaginary. Install requirements.txt."
        )
