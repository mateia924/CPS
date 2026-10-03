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

No per-function exemptions dict. `management/commands/*.py` is
excluded by LOCATION, the same boundary test_platform_db_structural.py
already draws (operator-run, never reachable from an HTTP/business
path, reviewed by a human each time it's invoked) — not a name-based
allowlist that can quietly decay. Any other site that genuinely cannot
call `assert_open_period` is a design discussion, not a line added
here.
"""

import ast
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"


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


def _is_exempt_by_location(relative_path: str) -> bool:
    return "management/commands/" in relative_path


def _posted_create_sites():
    for path in sorted(APPS_DIR.rglob("*.py")):
        relative_path = str(path.relative_to(APPS_DIR))
        if "migrations/" in relative_path or _is_exempt_by_location(relative_path):
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
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
                    fn_src = ast.unparse(enclosing) if enclosing else path.read_text()
                    sites.append((relative_path, fn_name, "assert_open_period" in fn_src))
                self.generic_visit(node)

        Visitor().visit(tree)
        yield from sites


def test_every_posted_journal_entry_create_calls_assert_open_period():
    violations = [f"{path}::{fn}" for path, fn, has_guard in _posted_create_sites() if not has_guard]
    assert not violations, (
        "Function(s) create a JournalEntry with status=POSTED directly "
        "without calling assert_open_period in the same function: "
        f"{violations}. Either call apps.accounting.periods."
        "assert_open_period there, or raise this as a design discussion "
        "— this check has no per-function exemptions list by design."
    )
