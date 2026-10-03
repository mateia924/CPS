"""Sprint 7.0 (6.6.10, item 0-bis): `assert_open_period`'s protection
is only real if every code path that creates a POSTED JournalEntry
directly (invoice issuance, voucher posting, asset disposal, opening-
balance approval, recurring-installment generation, manual posting,
and whatever sprint 7 adds — COGS at issuance, inventory adjustments,
cost variances) actually calls it in the same function. This is a
source-level scan (not a runtime registry walk), same shape as
test_platform_db_structural.py's own "platform" DB-alias scan, since
the whole point is catching a forgetful new caller before it's ever
exercised by a request at all.

No per-function exemptions dict, and no folder-based exemption either
(an earlier version of this check excluded `management/commands/*.py`
by location — wrong boundary, caught live: it also silently excluded
`fix_disposal_correction.py`, which exists specifically to touch real
tenant data, from ever being checked again). The real boundary is
whether the code can reach real tenant data at all, not what directory
it lives in — a site is accepted if EITHER:

(a) it calls `assert_open_period` in the same function, or
(b) its own MODULE carries an enforced environment guard that refuses
    to run outside dev (CPS_ENVIRONMENT in {staging, production} ->
    raises and exits non-zero) — verified as real code here, not
    assumed from a docstring; `seed_perf.py`'s own guard has its own
    negative test in test_guards.py, so this exemption is self-
    justifying rather than resting on undocumented trust.

Any site that satisfies neither is a design discussion, not a line
added anywhere in this file.
"""

import ast
import re
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

# Sprint 7.0 (6.6.10): matches the real, enforced shape of seed_perf.py's
# own guard — `CPS_ENVIRONMENT` checked against both "staging" and
# "production" literals, with a `raise` in the same file (not just a
# docstring claim). Deliberately file-wide, not function-scoped: the
# owner's own framing is "the MODULE carries the guard," since the
# check and the posting code are often in the same function anyway but
# don't have to be.
_ENV_GUARD_PATTERN = re.compile(
    r"CPS_ENVIRONMENT.*staging.*production|CPS_ENVIRONMENT.*production.*staging", re.DOTALL
)


def _module_has_enforced_env_guard(file_text: str) -> bool:
    return bool(_ENV_GUARD_PATTERN.search(file_text)) and "raise" in file_text


def _is_posted_journal_entry_create(node):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    is_create_call = (
        isinstance(func, ast.Attribute) and func.attr == "create"
        and isinstance(func.value, ast.Attribute) and func.value.attr == "objects"
        and isinstance(func.value.value, ast.Name) and func.value.value.id == "JournalEntry"
    )
    is_bare_constructor = isinstance(func, ast.Name) and func.id == "JournalEntry"
    if not (is_create_call or is_bare_constructor):
        return False
    for kw in node.keywords:
        if kw.arg == "status" and "POSTED" in ast.unparse(kw.value):
            return True
    return False


def _posted_create_sites():
    for path in sorted(APPS_DIR.rglob("*.py")):
        relative_path = str(path.relative_to(APPS_DIR))
        if "migrations/" in relative_path:
            continue
        file_text = path.read_text()
        try:
            tree = ast.parse(file_text, filename=str(path))
        except SyntaxError:
            continue
        module_has_env_guard = _module_has_enforced_env_guard(file_text)
        func_stack = []
        sites = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                func_stack.append(node)
                self.generic_visit(node)
                func_stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                if _is_posted_journal_entry_create(node):
                    enclosing = func_stack[-1] if func_stack else None
                    fn_name = enclosing.name if enclosing else "<module>"
                    fn_src = ast.unparse(enclosing) if enclosing else file_text
                    has_guard = "assert_open_period" in fn_src or module_has_env_guard
                    sites.append((relative_path, fn_name, has_guard))
                self.generic_visit(node)

        Visitor().visit(tree)
        yield from sites


def test_every_posted_journal_entry_create_calls_assert_open_period():
    violations = [f"{path}::{fn}" for path, fn, has_guard in _posted_create_sites() if not has_guard]
    assert not violations, (
        "Function(s) create a JournalEntry with status=POSTED directly "
        "without calling assert_open_period in the same function, and "
        "without their module carrying an enforced dev-only environment "
        f"guard: {violations}. Either call apps.accounting.periods."
        "assert_open_period there, add a real (not just documented) "
        "CPS_ENVIRONMENT guard, or raise this as a design discussion — "
        "this check has no exemptions list by design."
    )
