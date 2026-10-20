"""Block 8.2.1: the CI Gate caps tests that did not run.

Uncollected files are caught by scripts/check_ci_collection.sh and skips
by their per-step ceilings. Deselection is the third way a test does not
run: scripts/ci_gate_counts.sh now caps it per step too (CI_MAX_DESELECTED_*
in scripts/ci_test_groups.sh). These tests feed that script pytest's final
summary lines and check its verdict.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
GATE = SCRIPTS / "ci_gate_counts.sh"
GROUPS = ("accounting", "assets-treasury", "attachments-permissions", "rest")

pytestmark = pytest.mark.skipif(
    not GATE.exists(),
    reason="needs the repo's scripts/ (CI and ci_local have it; the dev container mounts only backend/)",
)


def _logs(tmp_path, **summaries):
    for group in GROUPS:
        summary = summaries.get(group.replace("-", "_"), "10 passed")
        (tmp_path / f"test-{group}.log").write_text(
            f"tests/test_x.py::test_a PASSED\n===== {summary}, 2 warnings in 12.34s =====\n"
        )
    return subprocess.run(["bash", str(GATE), str(tmp_path)], capture_output=True, text=True)


def test_todays_counts_pass(tmp_path):
    result = _logs(tmp_path, attachments_permissions="200 passed, 2 deselected")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "attachments-permissions: 200 passed, 0 skipped (ceiling 0), 2 deselected (ceiling 2)" in result.stdout


def test_one_more_deselected_test_fails_the_gate_and_names_the_step(tmp_path):
    result = _logs(tmp_path, attachments_permissions="199 passed, 3 deselected")
    assert result.returncode == 1, result.stdout
    assert "attachments-permissions(deselected 3>2)" in result.stdout


def test_a_deselected_test_in_a_step_with_none_recorded_fails(tmp_path):
    result = _logs(tmp_path, rest="500 passed, 1 deselected")
    assert result.returncode == 1, result.stdout
    assert "rest(deselected 1>0)" in result.stdout


def test_skips_are_still_capped(tmp_path):
    result = _logs(tmp_path, accounting="99 passed, 1 skipped")
    assert result.returncode == 1, result.stdout
    assert "accounting(skipped 1>0)" in result.stdout


def test_a_missing_step_log_fails_rather_than_counting_zero(tmp_path):
    _logs(tmp_path)
    (tmp_path / "test-rest.log").unlink()
    result = subprocess.run(["bash", str(GATE), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
    assert "rest(no log)" in result.stdout
