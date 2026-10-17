"""Pre-deploy 1, rule 32 (docs/SYSTEM_ANALYSIS.md §4): the staging
rehearsal runs production's own gates. Not "the same list kept in two
places" — one definition, scripts/production_gates.sh, that
scripts/deploy.sh and scripts/staging_refresh.sh both source and run
through cps_run_gates. Before it, the two scripts carried their own
copies and drifted: the rehearsal skipped add_missing_system_accounts and
check_chart_health entirely, and its full mode (the most destructive)
had neither smoke nor the readiness poll.

These read the scripts as text, so they need the repo's scripts/ — the
dev container mounts only backend/ at /app. Same declared skip as
tests/test_deploy_sh_guards.py; scripts/ci_local.sh asserts they PASS
there, so the skip can never quietly become "never runs anywhere".
"""

import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
GATES_FILE = SCRIPTS / "production_gates.sh"
CALLERS = ("deploy.sh", "staging_refresh.sh")

# What a gate looks like when someone runs it directly instead of through
# the shared definition — a private copy, i.e. the start of a drift.
GATE_COMMANDS = {
    "backup": r"scripts/backup\.sh",
    "migrate": r"manage\.py\s+migrate\b",
    "setup_rls": r"manage\.py\s+setup_rls\b",
    "verify_rls": r"pg_policies",
    "add_missing_system_accounts": r"add_missing_system_accounts",
    "check_chart_health": r"check_chart_health",
    "ready": r"/admin/login/",
    "smoke": r"smoke\.sh",
}

pytestmark = pytest.mark.skipif(
    not GATES_FILE.exists(),
    reason="needs the repo's scripts/ (CI and ci_local have it; the dev container mounts only backend/)",
)


def _code(path):
    """The script without comment lines and without the messages it
    prints — either may name a gate without running it."""
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith(("#", "echo ", "log "))
    )


def _gate_list():
    match = re.search(r"^CPS_PRODUCTION_GATES=\(\n(.*?)\n\)", _code(GATES_FILE), re.S | re.M)
    assert match, "production_gates.sh must define CPS_PRODUCTION_GATES=( ... )"
    return match.group(1).split()


def test_the_shared_definition_holds_every_production_gate_in_order():
    assert _gate_list() == [
        "backup",
        "migrate",
        "setup_rls",
        "verify_rls",
        "add_missing_system_accounts",
        "check_chart_health",
        "start",
        "ready",
        "smoke",
    ]
    code = _code(GATES_FILE)
    for gate in _gate_list():
        assert re.search(rf"^cps_gate_{gate}\(\) {{", code, re.M), f"no cps_gate_{gate} function"
    assert re.search(r"check_chart_health --fail-on-findings", code)
    assert re.search(r'backup\.sh" --target "\$GATE_BACKUP_TARGET"', code)


@pytest.mark.parametrize("caller", CALLERS)
def test_caller_runs_the_shared_gates_and_holds_none_of_its_own(caller):
    code = _code(SCRIPTS / caller)

    assert re.search(r'^\s*source "\$REPO_DIR/scripts/production_gates\.sh"$', code, re.M), (
        f"{caller} does not source scripts/production_gates.sh"
    )
    runs = re.findall(r"^.*\bcps_run_gates\b.*$", code, re.M)
    assert len(runs) == 1, f"{caller} must call cps_run_gates exactly once, found {runs}"
    # At the top level, not inside one mode's branch: every mode passes it.
    assert not runs[0].startswith((" ", "\t")), f"{caller} calls cps_run_gates inside a branch: {runs[0]!r}"

    assert "CPS_PRODUCTION_GATES" not in code, f"{caller} defines or edits a gate list of its own"
    assert not re.search(r"^\s*cps_gate_\w+\(\)", code, re.M), f"{caller} defines a gate function of its own"

    private = {gate: re.findall(rf"^.*{pattern}.*$", code, re.M) for gate, pattern in GATE_COMMANDS.items()}
    private = {gate: lines for gate, lines in private.items() if lines}
    assert not private, f"{caller} runs production gates of its own instead of the shared definition: {private}"
