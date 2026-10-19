"""Sprint 7.0.2 (incident, docs/SYSTEM_ANALYSIS.md §11): scripts/
deploy.sh now refuses to run from a dirty working tree by default —
the night this guard didn't exist, a deploy shipped uncommitted 7.0.1
fixes on top of the committed 7.0.1 commit, and deploys.log's own
one-line record (just a git hash) could not reconstruct what was
actually live.

Runs the real script against a disposable clone (never the
real repo, no backup/build/migrate/restart/smoke ever runs — the
guard is the very first thing the script does, before even sourcing
.env) — safe to run in CI forever.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 7.2.9-c: these drive the real scripts/deploy.sh through a git worktree,
# so they need BOTH a git binary and the repo root. The dev container has
# neither — it mounts only backend/ at /app and ships no git — so they
# errored there on every run and proved nothing. A declared skip is honest
# where a false ERROR was not. scripts/ci_local.sh mounts the whole repo at
# /workspace, installs git, and has its own step asserting these PASS (not
# skip), so the skip can never quietly become "never runs anywhere".
_GUARDS_RUNNABLE = (REPO_ROOT / ".git").exists() and shutil.which("git") is not None

pytestmark = pytest.mark.skipif(
    not _GUARDS_RUNNABLE,
    reason="needs the repo root and a git binary (CI does; the dev container does not)",
)


@pytest.fixture
def disposable_worktree(tmp_path):
    # 2026-10-19: a shallow clone, not `git worktree add` — a worktree
    # writes into the real repo's .git, so these could not run with the
    # repo mounted read-only (scripts/prove_guard.sh --repo). The clone
    # holds HEAD's tree, exactly what the worktree held.
    worktree = tmp_path / "deploy-sh-guard-worktree"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{REPO_ROOT}", str(worktree)],
        check=True, capture_output=True, text=True,
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
    for name in ("deploy.sh", "standing_exclusions.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, worktree / "scripts" / name)
    subprocess.run(["git", "add", "scripts/standing_exclusions.sh"], cwd=worktree, check=False, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=tests@cps.local", "-c", "user.name=CPS tests",
         "commit", "--no-verify", "-qam", "test: working copy of scripts/deploy.sh"],
        cwd=worktree, check=False, capture_output=True, text=True,
    )

    try:
        yield worktree
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


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


# --- 2026-10-19: the standing exclusion list, one definition, two readers. ---


def _dirty_the_standing_exclusions(worktree):
    """Every kind of standing exclusion at once: an untracked directory,
    a new file in a tracked screenshot directory, a regenerated tracked
    screenshot, and an append to a listed log."""
    (worktree / "infra" / "fail2ban").mkdir(parents=True, exist_ok=True)
    (worktree / "infra" / "fail2ban" / "jail.local").write_text("[sshd]\nenabled = true\n")
    screens = worktree / "docs" / "uat" / "screens" / "6.5.8"
    (screens / "new-shot-for-this-test.png").write_bytes(b"\x89PNG new")
    tracked = sorted(screens.glob("*.png"))[0]
    tracked.write_bytes(tracked.read_bytes() + b"regenerated")
    log = worktree / "docs" / "ops" / "ci-local.log"
    log.write_text(log.read_text() + "2026-01-01 test line\n")
    return tracked.name


def test_deploy_sh_does_not_count_the_standing_exclusions_and_names_each_one(disposable_worktree):
    tracked_png = _dirty_the_standing_exclusions(disposable_worktree)

    result = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=disposable_worktree,
        capture_output=True, text=True, env=_MINIMAL_ENV,
    )
    out = result.stdout + result.stderr

    assert "refusing to deploy" not in out, out
    assert "WARNING: deploying from a DIRTY working tree" not in out, out
    assert ".env" in out, out
    assert "not counted as dirty (standing exclusion infra/fail2ban/): ?? infra/fail2ban/" in out, out
    assert f"(standing exclusion docs/uat/screens/6.5.8/):  M docs/uat/screens/6.5.8/{tracked_png}" in out, out
    assert "?? docs/uat/screens/6.5.8/new-shot-for-this-test.png" in out, out


def test_deploy_sh_still_refuses_a_modified_py_file_by_name_beside_the_exclusions(disposable_worktree):
    _dirty_the_standing_exclusions(disposable_worktree)
    settings_py = disposable_worktree / "backend" / "config" / "settings.py"
    settings_py.write_text(settings_py.read_text() + "\n# uncommitted change\n")

    result = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=disposable_worktree,
        capture_output=True, text=True, env=_MINIMAL_ENV,
    )

    assert result.returncode != 0
    assert "refusing to deploy" in result.stderr, result.stderr
    refused = result.stderr.split("Changed file(s):", 1)[1]
    assert " M backend/config/settings.py" in refused
    assert "fail2ban" not in refused and "6.5.8" not in refused


@pytest.mark.parametrize(
    "path",
    [
        "infra/fail2ban.py",
        "infra/fail2ban-extra/jail.local",
        "docs/uat/screens/6.5.8-other/x.png",
        "docs/uat/screens/elsewhere.png",
        "docs/ops/backups.log.py",
        "frontend/next-env.d.ts.orig-copy",
    ],
)
def test_a_path_that_only_resembles_an_exclusion_still_refuses(disposable_worktree, path):
    target = disposable_worktree / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not on the list\n")

    result = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=disposable_worktree,
        capture_output=True, text=True, env=_MINIMAL_ENV,
    )

    assert result.returncode != 0
    assert "refusing to deploy" in result.stderr
    assert path.split("/")[0] in result.stderr.split("Changed file(s):", 1)[1]


def test_the_exclusion_list_has_one_definition_read_by_both_guards():
    scripts = REPO_ROOT / "scripts"
    shared = (scripts / "standing_exclusions.sh").read_text(encoding="utf-8")
    entries = [line.strip().strip('"') for line in shared.split("CPS_STANDING_EXCLUSIONS=(", 1)[1].split(")", 1)[0].splitlines() if line.strip()]
    assert entries == [
        "infra/fail2ban/",
        "docs/ops/backups.log",
        "docs/ops/ci-local.log",
        "frontend/next-env.d.ts",
        "docs/uat/screens/6.5.8/",
    ]
    assert not any(ch in entry for entry in entries for ch in "*?[")
    for reader in ("deploy.sh", "precommit_guard.sh"):
        code = "\n".join(
            line for line in (scripts / reader).read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "standing_exclusions.sh" in code and "cps_standing_exclusion " in code, reader
        for entry in entries:
            assert entry not in code, f"{reader} holds its own copy of {entry}"
