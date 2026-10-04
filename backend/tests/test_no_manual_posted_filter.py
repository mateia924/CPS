"""Sprint 7.0.3 structural guard: no hand-written `status=POSTED` (or
the bare string 'posted') JournalEntry.objects.filter(...) call exists
outside apps/accounting/services.py's three named functions
(unreversed_posted_entries, debt_entries, gross_trial_balance).

Why this exists: three subtly different definitions of "which entries
count" were each written out by hand at least once during the 7.0.2
incident response, and two of those three hand-written versions were
wrong on the first try (one miscounted a tenant's own debt by
including its closing reversal entry, one miscounted a gross balance
by excluding an already-reversed original). The three named functions
now hold the one correct definition of each; this test is the fence
that keeps a future script or report from quietly re-deriving a fourth
variant instead of calling one of them.

This deliberately does NOT flag `status=JournalEntry.Status.POSTED`
used to CREATE an entry (every automated posting path does this, and
it is not a query), nor `status__in=[...]` (REPORTABLE_STATUSES-style
queries already have their own, different, correct convention), nor a
plain equality check like `if entry.status != POSTED`. It only flags
`<Model>.objects.filter(...)` calls whose argument list contains a
bare `status=` equal to POSTED/'posted' — the exact shape of the three
functions this guard exists to protect.
"""

import re
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

# Files allowed to contain the pattern: the three functions' own
# definitions, and this test file's own docstring/example text.
ALLOWED_FILES = {APPS_DIR / "accounting" / "services.py"}

FILTER_CALL_RE = re.compile(r"JournalEntry\.objects\.filter\(")
# `status\s*=\s*` (not `status__in=`, which has extra characters before
# the "=" and so never matches this) followed by POSTED/'posted'.
BAD_STATUS_RE = re.compile(r"\bstatus\s*=\s*(JournalEntry\.Status\.POSTED|['\"]posted['\"])")


def _filter_call_arglists(source):
    """Yield the (start_offset, text) of each JournalEntry.objects.filter(...)
    call's argument list, matching parens by depth so a call that spans
    multiple lines is captured whole."""
    for match in FILTER_CALL_RE.finditer(source):
        start = match.end()  # just after the opening "("
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
            i += 1
        yield start, source[start : i - 1]


def _violations_in_file(path):
    source = path.read_text(encoding="utf-8")
    violations = []
    for offset, arglist in _filter_call_arglists(source):
        if BAD_STATUS_RE.search(arglist):
            line_no = source.count("\n", 0, offset) + 1
            violations.append(f"{path}:{line_no}")
    return violations


def test_no_file_outside_the_named_functions_hand_writes_a_posted_filter():
    violations = []
    for path in APPS_DIR.rglob("*.py"):
        if path in ALLOWED_FILES:
            continue
        if "/migrations/" in str(path) or "/tests/" in str(path):
            continue
        violations.extend(_violations_in_file(path))

    assert not violations, (
        "Found a hand-written JournalEntry.objects.filter(status=POSTED/'posted') "
        "outside apps/accounting/services.py. Use one of the three named functions "
        "instead (unreversed_posted_entries / debt_entries / gross_trial_balance) — "
        "see their docstrings for which one matches your intent. Violations:\n"
        + "\n".join(violations)
    )
