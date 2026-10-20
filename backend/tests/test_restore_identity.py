"""Block A (2026-10-20): restore.sh refuses a backup from the wrong source.

Until today restore.sh checked no identity: backups.log carried each dump's
db=<host>/<name>#<system_identifier> since 2026-10-17, but only the migrate
guard read it, so a staging dump could be restored onto live with nothing in
the way. Now `--from <env>` is required, and both the dump's recorded db=
identity and the attachments manifest's minio= identity (plus its pairs=)
must match what that environment's running services report.

These tests run the real scripts/restore.sh and scripts/restore_lib.sh with a
fake `docker` that answers each environment's identity, and real gpg for the
manifest. A refusal must happen before anything is created or written.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
PASSPHRASE = "test-only-passphrase-not-a-secret"
LIVE_DB, STAGING_DB = "7000000000000000001", "7000000000000000002"
LIVE_MINIO, STAGING_MINIO = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"

pytestmark = pytest.mark.skipif(
    not (SCRIPTS / "restore_lib.sh").exists() or shutil.which("gpg") is None,
    reason="needs the repo's scripts/ and gpg (CI and ci_local have them)",
)

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_CALLS"
all="$*"
case "$all" in *"-p cps-staging"*) env=staging ;; *) env=live ;; esac
case "$all" in
  *system_identifier*) [ "$env" = staging ] && echo "$FAKE_STAGING_DB" || echo "$FAKE_LIVE_DB" ;;
  *"mc admin info"*) id="$FAKE_LIVE_MINIO"; [ "$env" = staging ] && id="$FAKE_STAGING_MINIO"
                     printf '{"info":{"deploymentID":"%s"}}\n' "$id" ;;
  *dropdb*|*createdb*) ;;
  *"information_schema.tables"*) echo 42 ;;
  *psql*) cat > /dev/null ;;
  *) ;;
esac
"""


@pytest.fixture
def box(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / "docs" / "ops").mkdir(parents=True)
    for name in ("restore.sh", "restore_lib.sh"):
        shutil.copy(SCRIPTS / name, repo / "scripts" / name)
    env = f"CPS_BACKUP_ENCRYPTION_PASSPHRASE={PASSPHRASE}\nPOSTGRES_USER=cps\nPOSTGRES_DB=cps\nMINIO_BUCKET=cps-attachments\n"
    (repo / ".env").write_text(env)
    (repo / ".env.staging").write_text("POSTGRES_USER=cps_staging\nPOSTGRES_DB=cps_staging\nMINIO_BUCKET=cps-attachments-staging\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    gnupg = tmp_path / "gnupg"
    gnupg.mkdir(mode=0o700)
    calls = tmp_path / "calls"
    calls.write_text("")
    run_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "GNUPGHOME": str(gnupg),
        "FAKE_CALLS": str(calls), "FAKE_LIVE_DB": LIVE_DB, "FAKE_STAGING_DB": STAGING_DB,
        "FAKE_LIVE_MINIO": LIVE_MINIO, "FAKE_STAGING_MINIO": STAGING_MINIO,
    }

    class Box:
        def dump(self, name, db_identity=None):
            path = tmp_path / name
            path.write_bytes(b"not really a dump")
            line = f"2026-10-20T03:00:01+03:00\tabc1234\t{name}\tnightly"
            if db_identity:
                line += f"\tdb={db_identity}"
            with (repo / "docs" / "ops" / "backups.log").open("a") as f:
                f.write(line + "\n")
            return path

        def manifest(self, minio_identity, pairs):
            (tmp_path / "attachments" / "manifests").mkdir(parents=True, exist_ok=True)
            path = tmp_path / "attachments" / "manifests" / "attachments-20261020-030001.manifest.gpg"
            plain = f"#cps-attachments-manifest\tv1\n#minio\t{minio_identity}\n#pairs\t{pairs}\n"
            # gpg reads the passphrase and the data from separate fds.
            r, w = os.pipe()
            os.write(w, PASSPHRASE.encode())
            os.close(w)
            subprocess.run(
                ["gpg", "--batch", "--yes", "--passphrase-fd", str(r), "--symmetric", "-o", str(path)],
                input=plain.encode(), pass_fds=(r,), capture_output=True, check=True,
                env={**os.environ, "GNUPGHOME": str(gnupg)},
            )
            os.close(r)
            return path

        def restore(self, *args):
            calls.write_text("")
            result = subprocess.run(
                ["bash", str(repo / "scripts" / "restore.sh"), *map(str, args)],
                env=run_env, capture_output=True, text=True, timeout=60,
            )
            return result, calls.read_text()

    return Box()


def _wrote_nothing(calls):
    return not any(word in calls for word in ("createdb", "dropdb", "mc pipe", "mc mb"))


def test_a_staging_dump_named_as_live_is_refused_by_name(box):
    dump = box.dump("cps-db-20261020-030001.sql.gz.gpg", f"postgres/cps_staging#{STAGING_DB}")
    result, calls = box.restore("--from", "live", dump)
    assert result.returncode == 1
    assert (
        f"REFUSED: cps-db-20261020-030001.sql.gz.gpg was taken from postgres/cps_staging#{STAGING_DB}, "
        f"not from live (postgres/cps#{LIVE_DB})."
    ) in result.stderr
    assert _wrote_nothing(calls), calls


def test_a_dump_with_no_recorded_source_is_refused(box):
    dump = box.dump("cps-db-20260923-112327.sql.gz")
    result, calls = box.restore("--from", "live", dump)
    assert result.returncode == 1
    assert "has no recorded source" in result.stderr
    assert _wrote_nothing(calls), calls


def test_restoring_into_lives_own_database_needs_a_live_dump(box):
    dump = box.dump("cps-db-20261020-030002.sql.gz.gpg", f"postgres/cps_staging#{STAGING_DB}")
    result, calls = box.restore("--from", "staging", dump, "cps")
    assert result.returncode == 1
    assert "REFUSED: restoring into live's own database (cps) needs a dump from live, not from staging." in result.stderr
    assert _wrote_nothing(calls), calls


def test_a_staging_manifest_with_a_live_dump_is_refused_by_name(box):
    dump = box.dump("cps-db-20261020-030001.sql.gz.gpg", f"postgres/cps#{LIVE_DB}")
    manifest = box.manifest(f"minio/cps-attachments-staging#{STAGING_MINIO}", dump.name)
    result, calls = box.restore("--from", "live", dump, "--attachments", manifest, "--attachments-into", "rt-minio")
    assert result.returncode == 1
    assert (
        f"REFUSED: attachments-20261020-030001.manifest.gpg was taken from minio/cps-attachments-staging#{STAGING_MINIO}, "
        f"not from live (minio/cps-attachments#{LIVE_MINIO})."
    ) in result.stderr
    assert _wrote_nothing(calls), calls


def test_a_manifest_paired_with_another_dump_is_refused(box):
    dump = box.dump("cps-db-20261020-030001.sql.gz.gpg", f"postgres/cps#{LIVE_DB}")
    manifest = box.manifest(f"minio/cps-attachments#{LIVE_MINIO}", "cps-db-20261019-030001.sql.gz.gpg")
    result, calls = box.restore("--from", "live", dump, "--attachments", manifest, "--attachments-into", "rt-minio")
    assert result.returncode == 1
    assert "belongs with cps-db-20261019-030001.sql.gz.gpg, not with cps-db-20261020-030001.sql.gz.gpg" in result.stderr
    assert _wrote_nothing(calls), calls


def test_the_right_source_restores(box):
    dump = box.dump("cps-db-20261020-030001.sql.gz.gpg", f"postgres/cps#{LIVE_DB}")
    result, calls = box.restore("--from", "live", dump)
    assert "Source check: cps-db-20261020-030001.sql.gz.gpg was taken from live" in result.stdout
    assert "createdb" in calls, calls
