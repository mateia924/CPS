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

import shutil
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
    # 7.2.9-c: `git worktree add` checks out HEAD, so until now these
    # tests exercised the COMMITTED deploy.sh — they would stay green
    # while the WORKING COPY's guard was broken, the same "the test
    # takes a different path from the real thing" flaw 7.2.9-b was
    # about. Copy the working copy in and commit it INSIDE the
    # disposable detached worktree (removed on teardown; the real repo,
    # its index and its branches are never touched), so the tree starts
    # clean again and each test controls its own dirtiness. Explicit
    # -c user.* because CI installs a bare git with no identity.
    shutil.copy2(REPO_ROOT / "scripts" / "deploy.sh", worktree / "scripts" / "deploy.sh")
    subprocess.run(
        ["git", "-c", "user.email=tests@cps.local", "-c", "user.name=CPS tests",
         "commit", "--no-verify", "-qam", "test: working copy of scripts/deploy.sh"],
        cwd=worktree, check=False, capture_output=True, text=True,
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


_MINIMAL_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin"}


def test_deploy_sh_dirty_guard_ignores_an_ops_log_the_previous_run_appended(disposable_worktree):
    """7.2.9-c: scripts/backup.sh and deploy.sh each append one line to
    docs/ops/*.log on every run, so the PREVIOUS deploy's own log line
    left the tree dirty and refused the NEXT deploy — three deploys were
    blocked this way, and the cron backup makes it happen nightly. A
    modification to those append-only logs ALONE is not a code change
    and must not refuse. Reaching the .env load (deploy.sh line ~72) is
    the positive proof that execution got past the guard, not merely
    that the refusal string is absent."""
    log = disposable_worktree / "docs" / "ops" / "backups.log"
    log.write_text(log.read_text() + "2026-01-01T00:00:00+03:00\tdeadbee\ttest-line\n")

    result = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=disposable_worktree,
        capture_output=True, text=True, env=_MINIMAL_ENV,
    )
    out = result.stdout + result.stderr

    assert "refusing to deploy" not in out, out
    # Not an override either: the tree counts as CLEAN, so the guard's
    # own WARNING line must be absent too.
    assert "WARNING: deploying from a DIRTY working tree" not in out, out
    assert ".env" in out, out


def test_deploy_sh_dirty_guard_still_refuses_an_ops_log_plus_any_other_change(disposable_worktree):
    """7.2.9-c: the exemption is for the logs ALONE. A real change
    alongside one still refuses, and the refusal names that change."""
    log = disposable_worktree / "docs" / "ops" / "backups.log"
    log.write_text(log.read_text() + "2026-01-01T00:00:00+03:00\tdeadbee\ttest-line\n")
    marker = disposable_worktree / "dirty_marker_for_this_test.txt"
    marker.write_text("uncommitted change\n")

    result = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=disposable_worktree,
        capture_output=True, text=True, env=_MINIMAL_ENV,
    )
    out = result.stdout + result.stderr

    assert result.returncode != 0
    assert "refusing to deploy" in out, out
    assert "dirty_marker_for_this_test.txt" in out, out
