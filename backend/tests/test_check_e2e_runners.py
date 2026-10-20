"""Block 8.2.1: scripts/check_e2e_runners.sh — every e2e spec file present
is run by exactly one runner (spec 10 sat unrun from 7.2.9 to 8.2.1).

Each test builds a small tree in tmp_path holding the guard, the runner,
the Makefile, ci.yml and the real spec files, then changes one thing.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "scripts" / "check_e2e_runners.sh"

pytestmark = pytest.mark.skipif(
    not GUARD.exists(),
    reason="needs the repo's scripts/ and frontend/e2e (CI and ci_local have them; the dev container mounts only backend/)",
)


def _tree(tmp_path):
    for rel in ("scripts/check_e2e_runners.sh", "scripts/e2e.sh", "Makefile", ".github/workflows/ci.yml"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    (tmp_path / "frontend/e2e").mkdir(parents=True)
    for spec in (REPO / "frontend/e2e").glob("*.spec.ts"):
        shutil.copy(spec, tmp_path / "frontend/e2e" / spec.name)
    return tmp_path


def _run(tree):
    return subprocess.run(["bash", str(tree / "scripts/check_e2e_runners.sh")], capture_output=True, text=True)


def test_every_spec_in_the_repo_is_run(tmp_path):
    result = _run(_tree(tmp_path))
    assert result.returncode == 0, result.stderr


def test_a_spec_no_runner_names_fails_and_is_named(tmp_path):
    tree = _tree(tmp_path)
    (tree / "frontend/e2e/99-throwaway-not-run.spec.ts").write_text('import { test } from "@playwright/test";\n')
    result = _run(tree)
    assert result.returncode == 1
    assert "NOT RUN by any runner: frontend/e2e/99-throwaway-not-run.spec.ts" in result.stderr


def test_a_spec_named_only_in_a_comment_is_not_run(tmp_path):
    tree = _tree(tmp_path)
    runner = tree / "scripts/e2e.sh"
    lines = runner.read_text().splitlines()
    runner.write_text(
        "\n".join(
            "# " + line if "10-reset-password-subdomain-from-host.spec.ts --reporter" in line else line
            for line in lines
        )
        + "\n"
    )
    result = _run(tree)
    assert result.returncode == 1
    assert "frontend/e2e/10-reset-password-subdomain-from-host.spec.ts" in result.stderr


def test_the_runner_must_still_be_reached_from_ci(tmp_path):
    tree = _tree(tmp_path)
    ci = tree / ".github/workflows/ci.yml"
    ci.write_text(ci.read_text().replace("make e2e", "echo e2e"))
    result = _run(tree)
    assert result.returncode == 1
    assert "ci.yml no longer runs 'make e2e'" in result.stderr
