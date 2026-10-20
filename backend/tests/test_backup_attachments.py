"""Block A (2026-10-20): attachments in the nightly backup.

backup.sh runs from root cron on live. The attachment step must never be
able to fail the database dump: MinIO unreachable, hanging or misconfigured,
the database backup still completes, still writes its backups.log line, and
backup.sh still exits 0. These tests run the real scripts/backup.sh and
scripts/backup_attachments.sh against a scratch directory (CPS_BACKUP_ROOT),
with a fake `docker` on PATH standing in for postgres and minio, and real
gpg.

Needs the repo's scripts/ and gpg: skips in the dev image (ci_local and CI
have both).
"""

import gzip
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
PASSPHRASE = "test-only-passphrase-not-a-secret"
SYSTEM_ID = "7111111111111111111"
DEPLOYMENT_ID = "11111111-2222-3333-4444-555555555555"
BUCKET = "cps-attachments"

pytestmark = pytest.mark.skipif(
    not (SCRIPTS / "backup_attachments.sh").exists() or shutil.which("gpg") is None,
    reason="needs the repo's scripts/ and gpg (CI and ci_local have them)",
)

FAKE_DOCKER = r"""#!/usr/bin/env bash
# Stand-in for `docker compose ... exec -T [-e NAME=value ...] <service> <cmd...>`.
# Like real docker, each -e NAME=value becomes the command's environment.
all="$*"
prev=""
for arg in "$@"; do
  [ "$prev" = "-e" ] && case "$arg" in *=*) export "$arg" ;; esac
  prev="$arg"
done
case "$all" in
  *" minio sh -c "*)
    case "${FAKE_MINIO_MODE:-up}" in
      down) echo "service \"minio\" is not running" >&2; exit 1 ;;
      hang) sleep 60; exit 1 ;;
    esac
    case "$all" in
      *"mc admin info"*) printf '{"status":"success","info":{"deploymentID":"%s"}}\n' "$FAKE_DEPLOYMENT_ID" ;;
      *"mc cat"*)
        f="$FAKE_MINIO_DIR/$K"
        [ -f "$f" ] || { echo "mc: <ERROR> Object does not exist." >&2; exit 1; }
        cat "$f" ;;
      *) exit 1 ;;
    esac ;;
  *system_identifier*) echo "$FAKE_SYSTEM_ID" ;;
  *pg_dump*)
    if [ -n "${FAKE_SLOW_DUMP:-}" ]; then
      # 256 KB that gzip cannot shrink, so bytes reach the disk; then stall.
      printf -- '-- fake dump\n'; head -c 262144 /dev/urandom; touch "$FAKE_DUMP_STARTED"; sleep 30
    fi
    printf -- '-- fake dump\nSELECT 1;\n' ;;
  *attachments_attachment*) cat "$FAKE_REFS" ;;
  *) echo "fake docker: unexpected: $all" >&2; exit 1 ;;
esac
"""


def sha(data):
    import hashlib

    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / "docs" / "ops").mkdir(parents=True)
    for name in ("backup.sh", "backup_attachments.sh", "prune_backups.sh"):
        shutil.copy(SCRIPTS / name, repo / "scripts" / name)
    (repo / ".env").write_text(
        f"CPS_BACKUP_ENCRYPTION_PASSPHRASE={PASSPHRASE}\nPOSTGRES_USER=cps\nPOSTGRES_DB=cps\nMINIO_BUCKET={BUCKET}\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    minio = tmp_path / "minio"
    minio.mkdir()
    refs = tmp_path / "refs.tsv"
    refs.write_text("")
    gnupg = tmp_path / "gnupg"
    gnupg.mkdir(mode=0o700)

    class Box:
        root = tmp_path / "backups"
        ops_log = repo / "docs" / "ops" / "backups.log"
        store = tmp_path / "backups" / "attachments"

        def put(self, key, data, status="active", row_sha=None):
            path = minio / key
            path.parent.mkdir(parents=True, exist_ok=True)
            if data is not None:
                path.write_bytes(data)
            body = data if data is not None else b"never uploaded"
            with refs.open("a") as f:
                f.write(f"{key}\t{row_sha or sha(body)}\t{len(body)}\t{status}\n")

        def env(self, mode="up", timeout_s="20"):
            return {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "HOME": str(tmp_path),
                "GNUPGHOME": str(gnupg),
                "CPS_BACKUP_ROOT": str(self.root),
                "CPS_ATT_TIMEOUT": timeout_s,
                "FAKE_MINIO_MODE": mode,
                "FAKE_MINIO_DIR": str(minio),
                "FAKE_REFS": str(refs),
                "FAKE_SYSTEM_ID": SYSTEM_ID,
                "FAKE_DEPLOYMENT_ID": DEPLOYMENT_ID,
            }

        def run(self, mode="up", timeout_s="20"):
            return subprocess.run(
                ["bash", str(repo / "scripts" / "backup.sh"), "test run"],
                env=self.env(mode, timeout_s), capture_output=True, text=True, timeout=120,
            )

        def start(self, slow_dump=False):
            """backup.sh in its own process group, so a test can kill the whole run."""
            started = tmp_path / "dump-started"
            env = {**self.env(), "FAKE_DUMP_STARTED": str(started)}
            if slow_dump:
                env["FAKE_SLOW_DUMP"] = "1"
            proc = subprocess.Popen(
                ["bash", str(repo / "scripts" / "backup.sh"), "test run"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            return proc, started

        def lines(self):
            return [line.split("\t") for line in self.ops_log.read_text().splitlines()]

        def decrypt(self, path):
            return subprocess.run(
                ["gpg", "--batch", "--quiet", "--passphrase-fd", "0", "--decrypt", str(path)],
                input=PASSPHRASE.encode(), capture_output=True, env={**os.environ, "GNUPGHOME": str(gnupg)},
                check=True,
            ).stdout

    return Box()


def _db_line_and_dump(box):
    db_lines = [line for line in box.lines() if line[-1] == f"db=postgres/cps#{SYSTEM_ID}"]
    assert len(db_lines) == 1, box.lines()
    dump = box.root / db_lines[0][2]
    assert gzip.decompress(box.decrypt(dump)).decode().startswith("-- fake dump"), "the dump does not decrypt"
    return db_lines[0]


def _attachment_line(box):
    lines = [line for line in box.lines() if any(f.startswith("minio=") for f in line)]
    assert len(lines) == 1, box.lines()
    return dict(f.split("=", 1) for f in lines[0][4:]), lines[0]


@pytest.mark.parametrize("mode", ["down", "hang"])
def test_the_database_backup_completes_and_exits_0_whatever_minio_does(sandbox, mode):
    sandbox.put("t1/bank/2026/a.png", b"real bytes")
    result = sandbox.run(mode=mode, timeout_s="3")
    assert result.returncode == 0, result.stdout + result.stderr
    db_line = _db_line_and_dump(sandbox)
    fields, _ = _attachment_line(sandbox)
    assert fields["status"] == ("FAILED:minio-unreachable" if mode == "down" else "FAILED:terminated"), fields
    assert fields["pairs"] == Path(db_line[2]).name
    assert "attachment backup did not complete" in result.stderr


def test_every_row_is_backed_up_voided_included_with_the_source_identity(sandbox):
    sandbox.put("t1/bank/2026/active.png", b"\x89PNG active")
    sandbox.put("t1/voucher/2026/voided.pdf", b"%PDF voided", status="voided")
    result = sandbox.run()
    assert result.returncode == 0, result.stdout + result.stderr
    db_line = _db_line_and_dump(sandbox)
    fields, line = _attachment_line(sandbox)
    assert fields["status"] == "OK", fields
    assert fields["minio"] == f"minio/{BUCKET}#{DEPLOYMENT_ID}"
    assert (fields["refs"], fields["new"], fields["kept"], fields["missing"]) == ("2", "2", "0", "0")
    for key, data in (("t1/bank/2026/active.png", b"\x89PNG active"), ("t1/voucher/2026/voided.pdf", b"%PDF voided")):
        assert sandbox.decrypt(sandbox.store / "objects" / f"{key}.gpg") == data
    manifest = sandbox.decrypt(sandbox.root / line[2]).decode().splitlines()
    assert manifest[:3] == [
        "#cps-attachments-manifest\tv1", f"#minio\tminio/{BUCKET}#{DEPLOYMENT_ID}", f"#pairs\t{Path(db_line[2]).name}",
    ]
    rows = {r.split("\t")[0]: r.split("\t") for r in manifest if not r.startswith("#")}
    assert rows["t1/voucher/2026/voided.pdf"][3:] == ["voided", "new"]


def test_a_missing_object_fails_the_step_loudly_but_not_the_database(sandbox):
    sandbox.put("t1/bank/2026/here.png", b"here")
    sandbox.put("t1/bank/2026/gone.png", None)
    result = sandbox.run()
    assert result.returncode == 0, result.stdout + result.stderr
    _db_line_and_dump(sandbox)
    fields, _ = _attachment_line(sandbox)
    assert fields["status"] == "FAILED:missing=1,mismatch=0", fields
    assert "object MISSING from the bucket: t1/bank/2026/gone.png" in result.stderr
    assert (sandbox.store / "objects" / "t1/bank/2026/here.png.gpg").exists()


def test_a_mismatched_object_is_not_stored_and_a_stored_copy_is_never_replaced(sandbox):
    sandbox.put("t1/bank/2026/doc.png", b"original bytes")
    assert sandbox.run().returncode == 0
    stored = sandbox.store / "objects" / "t1/bank/2026/doc.png.gpg"
    before = stored.read_bytes()
    # The source object is overwritten in place, and a new row's bytes do not match it.
    (sandbox.store.parent.parent / "minio" / "t1/bank/2026/doc.png").write_bytes(b"tampered")
    sandbox.put("t1/bank/2026/new.png", b"actual", row_sha=sha(b"what the row says"))
    sandbox.ops_log.write_text("")
    result = sandbox.run()
    assert result.returncode == 0
    fields, _ = _attachment_line(sandbox)
    assert fields["status"] == "FAILED:missing=0,mismatch=1", fields
    assert fields["kept"] == "1"
    assert stored.read_bytes() == before, "a backed-up copy was replaced"
    assert sandbox.decrypt(stored) == b"original bytes"
    assert not (sandbox.store / "objects" / "t1/bank/2026/new.png.gpg").exists()
    assert "sha256 MISMATCH, not stored: t1/bank/2026/new.png" in result.stderr


def test_nothing_in_the_store_is_readable_by_anyone_but_its_owner(sandbox):
    sandbox.put("t1/bank/2026/private.png", b"private")
    assert sandbox.run().returncode == 0
    loose = [p for p in [sandbox.store, *sandbox.store.rglob("*")] if p.stat().st_mode & 0o077]
    assert loose == [], [f"{p} {oct(p.stat().st_mode)}" for p in loose]
