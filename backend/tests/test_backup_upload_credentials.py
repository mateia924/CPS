"""Pre-deploy 5, rule 50 (docs/SYSTEM_ANALYSIS.md §4): backup.sh's upload
keys never on a command line. Until this block the off-server upload ran
`docker compose exec -T ... -e CPS_UPLOAD_SECRET_KEY=<value> ...` — every
night at 03:00 on live, readable in `ps` by every process on the host for
the whole upload. Both keys now travel by name only (`-e NAME`), the value
in compose's own environment.

The test runs backup.sh's own upload command, extracted from the file, with
COMPOSE pointing at a recorder: the keys must be absent from its argv AND
present in its environment — a fix that just dropped them would pass the
first half and break every upload. Needs the repo's scripts/: skips in the
dev image; scripts/ci_local.sh asserts it PASSES.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

pytestmark = pytest.mark.skipif(
    not (SCRIPTS / "backup.sh").exists(),
    reason="needs the repo's scripts/ (ci_local runs it)",
)

ACCESS_KEY = "AKIA-not-a-credential-access"
SECRET_KEY = "Zx+/9=q w$ecret 'quoted' tail=="


def _upload_command():
    """backup.sh's upload command: from `if ! ` to `; then` on the block
    that runs upload_backup_to_s3.py."""
    text = (SCRIPTS / "backup.sh").read_text(encoding="utf-8")
    end = text.index("upload_backup_to_s3.py; then")
    start = text.rindex("if ! ", 0, end) + len("if ! ")
    return text[start : end + len("upload_backup_to_s3.py")]


def test_backup_upload_passes_its_keys_by_name_never_on_the_command_line(tmp_path):
    argv_log = tmp_path / "argv"
    env_log = tmp_path / "env"
    recorder = tmp_path / "compose"
    recorder.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" > "{argv_log}"\n'
        f'printf "%s\\n%s\\n" "$CPS_UPLOAD_ACCESS_KEY" "$CPS_UPLOAD_SECRET_KEY" > "{env_log}"\n'
    )
    recorder.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", _upload_command()],
        env={
            "PATH": os.environ["PATH"],
            "COMPOSE": str(recorder),
            "UPLOAD_BUCKET": "cps-backups-interim",
            "UPLOAD_ENDPOINT": "http://minio:9000",
            "UPLOAD_ACCESS_KEY": ACCESS_KEY,
            "UPLOAD_SECRET_KEY": SECRET_KEY,
            "UPLOAD_REGION": "us-east-1",
            "UPLOAD_ENSURE_BUCKET": "1",
            "DUMP_FILE": "/opt/cps-backups/cps-db-test.sql.gz.gpg",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    argv = argv_log.read_text().splitlines()
    assert ACCESS_KEY not in "\n".join(argv)
    assert SECRET_KEY not in "\n".join(argv)
    # Passed by name: compose reads each value from its own environment.
    assert "CPS_UPLOAD_ACCESS_KEY" in argv
    assert "CPS_UPLOAD_SECRET_KEY" in argv
    assert env_log.read_text().splitlines() == [ACCESS_KEY, SECRET_KEY]
    # The rest of the command still reaches the uploader.
    assert argv[-3:] == ["backend", "python3", "/app/scripts/upload_backup_to_s3.py"]
