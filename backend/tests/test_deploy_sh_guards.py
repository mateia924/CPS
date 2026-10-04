"""Sprint 7.0.2 (incident, docs/SYSTEM_ANALYSIS.md §11): scripts/
deploy.sh now refuses to run from a dirty working tree by default —
the night this guard didn't exist, a deploy shipped uncommitted 7.0.1
fixes on top of the committed 7.0.1 commit, and deploys.log's own
one-line record (just a git hash) could not reconstruct what was
actually live.

Runs the real script against a disposable `git worktree` (never the
real repo, no backup/build/migrate/restart/smoke ever runs — the
guard is the very first thing the script does, before even sourcing
.env) — safe to run in CI forever.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def disposable_worktree(tmp_path):
    worktree = tmp_path / "deploy-sh-guard-worktree"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree)],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    try:
        yield worktree
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )


def test_deploy_sh_refuses_a_dirty_working_tree(disposable_worktree):
    marker = disposable_worktree / "dirty_marker_for_this_test.txt"
    marker.write_text("uncommitted change\n")

    result = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=disposable_worktree, capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "dirty_marker_for_this_test.txt" in result.stdout + result.stderr
    assert "refusing to deploy" in (result.stdout + result.stderr)


def test_deploy_sh_dirty_guard_allows_the_documented_override(disposable_worktree):
    marker = disposable_worktree / "dirty_marker_for_this_test.txt"
    marker.write_text("uncommitted change\n")

    # Still fails past this point (no real .env / docker stack in the
    # disposable worktree) — the only thing under test is that the
    # override lets execution reach PAST the dirty-tree guard itself,
    # proven by the WARNING line (the guard's own output) appearing
    # instead of the refusal message.
    result = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=disposable_worktree, capture_output=True, text=True,
        env={
            "ALLOW_DIRTY_DEPLOY": "1",
            "DIRTY_DEPLOY_REASON": "test: proving the documented override is reachable",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )

    assert "refusing to deploy" not in (result.stdout + result.stderr)
    assert "WARNING: deploying from a DIRTY working tree" in (result.stdout + result.stderr)
    assert "dirty_marker_for_this_test.txt" in (result.stdout + result.stderr)
