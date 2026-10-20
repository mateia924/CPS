"""Block A (2026-10-20): a backup never leaves a plaintext dump behind.

Until today backup.sh wrote cps-db-<ts>.sql.gz and encrypted it afterwards;
a gpg failure or a kill in between left a full plaintext dump of every
tenant, prune_backups.sh (matching only .gpg) never removed it, and the
file was 0644. Now: pg_dump | gzip | gpg streams (plaintext never on disk),
an EXIT trap removes the encrypted partial, the pruner removes post-
encryption plaintext and stale partials, and umask 077 makes every file
root-only. Runs the real scripts against a scratch directory with a fake
docker (see test_backup_attachments.py) and real gpg.
"""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from .test_backup_attachments import SCRIPTS, sandbox  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(
    not (SCRIPTS / "prune_backups.sh").exists(),
    reason="needs the repo's scripts/ (CI and ci_local have them)",
)


def _plaintext_files(root):
    """A plaintext dump by name (cps-db-*.sql.gz, even before gzip has
    flushed a byte into it) or by content (gzip magic, SQL text)."""
    found = []
    for path in root.rglob("*"):
        if path.is_file():
            head = path.read_bytes()[:4096]
            if path.name.endswith((".sql.gz", ".sql")) or head.startswith(b"\x1f\x8b") or b"fake dump" in head:
                found.append(f"{path.relative_to(root)} ({path.stat().st_size} bytes)")
    return found


@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGTERM], ids=["SIGKILL", "SIGTERM"])
def test_a_run_killed_mid_dump_leaves_no_plaintext(sandbox, sig):  # noqa: F811
    proc, started = sandbox.start(slow_dump=True)
    for _ in range(200):
        if started.exists():
            break
        time.sleep(0.05)
    assert started.exists(), "the fake pg_dump never started"
    time.sleep(1.0)  # let the first 256 KB flow through gzip
    os.killpg(proc.pid, sig)
    proc.wait(timeout=30)
    time.sleep(0.5)
    survivors = _plaintext_files(sandbox.root)
    assert survivors == [], f"a plaintext dump survived the kill: {survivors}"
    if sig == signal.SIGTERM:
        leftovers = [str(p.relative_to(sandbox.root)) for p in sandbox.root.rglob("*") if p.is_file()]
        assert leftovers == [], f"the trap left files behind: {leftovers}"


def test_the_pruner_removes_post_encryption_plaintext_and_stale_partials(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    names = {
        "stray": "cps-db-20261020-120000.sql.gz",            # after encryption existed: a failed run's leftover
        "historic": "cps-db-20260930-220943.sql.gz",         # before encryption: the owner's decision
        "dump": "cps-db-20261020-030001.sql.gz.gpg",
        "stale_part": "cps-db-20261020-020000.sql.gz.gpg.part",
        "fresh_part": "cps-db-20261020-230000.sql.gz.gpg.part",
    }
    for name in names.values():
        (d / name).write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(d / names["stale_part"], (two_hours_ago, two_hours_ago))
    result = subprocess.run(["bash", str(SCRIPTS / "prune_backups.sh"), str(d)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    left = sorted(p.name for p in d.iterdir())
    assert names["stray"] not in left, result.stdout
    assert names["stale_part"] not in left, result.stdout
    assert {names["historic"], names["dump"], names["fresh_part"]} <= set(left), left
    assert f"NOTICE: pre-encryption plaintext dump kept for the owner's decision: {names['historic']}" in result.stdout


def test_every_file_and_directory_a_backup_creates_is_root_only(sandbox):  # noqa: F811
    sandbox.put("t1/bank/2026/a.png", b"bytes")
    assert sandbox.run().returncode == 0
    loose = [p for p in [sandbox.root, *sandbox.root.rglob("*")] if p.stat().st_mode & 0o077]
    assert loose == [], [f"{Path(p).relative_to(sandbox.root)} {oct(p.stat().st_mode)}" for p in loose]
