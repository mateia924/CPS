"""Pre-deploy 4, rule 50 (docs/SYSTEM_ANALYSIS.md §4): the backup passphrase
never on a command line. backup.sh encrypted, and restore.sh/restore_test.sh
decrypted, with `gpg --passphrase "$VALUE"` — readable in `ps` by every
process on the host for the whole run (sampled live 2026-10-18 during
staging_refresh.sh --full). Every site now uses
`--passphrase-file <(printf '%s' "$VALUE")`.

The value did not change, only how it reaches gpg — so the acceptance test
is compatibility in both directions: a backup made the old way must open
with every new decrypt line, and a backup made by backup.sh's new line must
open the old way. A backup that cannot be decrypted is worse than none: it
reads as safety.

Each test runs the scripts' own gpg lines, extracted from the files, with a
real gpg and a fresh GNUPGHOME per invocation (a gpg-agent passphrase cache
shared between the encrypt and the decrypt could make a broken decrypt line
pass). Needs gpg and the repo's scripts/: the dev image has neither, so this
skips there; scripts/ci_local.sh installs gnupg and asserts it PASSES.
"""

import itertools
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
GPG = shutil.which("gpg")

pytestmark = pytest.mark.skipif(
    not GPG or not (SCRIPTS / "backup.sh").exists(),
    reason="needs gpg and the repo's scripts/ (ci_local installs gnupg; the dev image has neither)",
)

# Single line, as every .env value is — with a space, `$`, quotes and the
# base64 characters `openssl rand -base64 48` produces.
PASSPHRASE = "Zx+/9=q w$ord 'quoted' \"double\" tail=="

DECRYPT_SITES = ("restore.sh", "restore_test.sh", "staging_refresh.sh")
# The pre-Pre-deploy-4 commands, verbatim from backup.sh:147 / restore.sh:52.
LEGACY_ENCRYPT = 'gpg --batch --yes --passphrase "$PASSPHRASE" --symmetric --cipher-algo AES256 -o "$DUMP_FILE" "$RAW_DUMP_FILE"'
LEGACY_DECRYPT = (
    'gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE" --decrypt "$BACKUP_FILE"'
)

_homes = itertools.count()


def _gpg_line(script):
    """The script's own gpg command, from `gpg ` to before any `2>/dev/null`
    or line continuation."""
    lines = [
        line
        for line in (SCRIPTS / script).read_text(encoding="utf-8").splitlines()
        if "gpg --batch" in line and not line.lstrip().startswith("#")
    ]
    assert len(lines) == 1, f"{script}: expected one gpg line, found {lines}"
    command = lines[0][lines[0].index("gpg ") :]
    return command.split(" 2>/dev/null")[0].rstrip(" \\")


def _run(tmp_path, command, *, passphrase=PASSPHRASE, argv_log=None, **files):
    """Runs one gpg command under bash, in a fresh GNUPGHOME. With argv_log,
    a gpg shim first on PATH records the arguments it was given."""
    home = tmp_path / f"gnupg-{next(_homes)}"
    home.mkdir(mode=0o700)
    env = {
        "PATH": os.environ["PATH"],
        "GNUPGHOME": str(home),
        "PASSPHRASE": passphrase,
        "CPS_BACKUP_ENCRYPTION_PASSPHRASE": passphrase,
        **{name: str(path) for name, path in files.items()},
    }
    if argv_log is not None:
        shim_dir = tmp_path / "shim"
        shim_dir.mkdir(exist_ok=True)
        shim = shim_dir / "gpg"
        shim.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{argv_log}"\nexec {GPG} "$@"\n')
        shim.chmod(0o755)
        env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    try:
        return subprocess.run(
            ["bash", "-c", command],
            env=env,
            capture_output=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
    finally:
        if shutil.which("gpgconf"):
            subprocess.run(["gpgconf", "--kill", "all"], env=env, capture_output=True, timeout=30)


def _raw(tmp_path):
    raw = tmp_path / "dump.sql.gz"
    raw.write_bytes(os.urandom(4096) + b"-- PostgreSQL database dump complete\n")
    return raw


def test_every_backup_gpg_site_takes_the_passphrase_from_a_file_descriptor():
    for script in ("backup.sh", *DECRYPT_SITES):
        line = _gpg_line(script)
        assert "--passphrase-file <(printf '%s' \"$" in line, f"{script}: {line}"
        assert "--passphrase " not in line, (
            f"{script} puts the passphrase on the command line: {line}"
        )


def test_a_backup_made_before_the_change_opens_with_every_new_decrypt_line(tmp_path):
    raw = _raw(tmp_path)
    old_backup = tmp_path / "old.sql.gz.gpg"
    made = _run(tmp_path, LEGACY_ENCRYPT, DUMP_FILE=old_backup, RAW_DUMP_FILE=raw)
    assert made.returncode == 0, made.stderr

    argv_log = tmp_path / "argv"
    for script in DECRYPT_SITES:
        opened = _run(
            tmp_path,
            _gpg_line(script),
            argv_log=argv_log,
            BACKUP_FILE=old_backup,
            LATEST_BACKUP=old_backup,
        )
        assert opened.returncode == 0, f"{script}: {opened.stderr}"
        assert opened.stdout == raw.read_bytes(), f"{script} did not return the original bytes"
    assert PASSPHRASE not in argv_log.read_text()


def test_a_backup_made_by_the_new_backup_line_opens_the_old_way_and_the_new_way(tmp_path):
    raw = _raw(tmp_path)
    new_backup = tmp_path / "new.sql.gz.gpg"
    argv_log = tmp_path / "argv"
    made = _run(
        tmp_path, _gpg_line("backup.sh"), argv_log=argv_log, DUMP_FILE=new_backup, RAW_DUMP_FILE=raw
    )
    assert made.returncode == 0, made.stderr
    assert PASSPHRASE not in argv_log.read_text()

    # An older checkout's restore.sh (or a human with the old command) still opens it.
    opened_old_way = _run(tmp_path, LEGACY_DECRYPT, BACKUP_FILE=new_backup)
    assert opened_old_way.returncode == 0, opened_old_way.stderr
    assert opened_old_way.stdout == raw.read_bytes()
    for script in DECRYPT_SITES:
        opened = _run(tmp_path, _gpg_line(script), BACKUP_FILE=new_backup, LATEST_BACKUP=new_backup)
        assert opened.returncode == 0, f"{script}: {opened.stderr}"
        assert opened.stdout == raw.read_bytes()


def test_a_wrong_passphrase_opens_nothing(tmp_path):
    """The compatibility tests mean something only if decryption can fail."""
    raw = _raw(tmp_path)
    backup = tmp_path / "b.sql.gz.gpg"
    assert (
        _run(tmp_path, _gpg_line("backup.sh"), DUMP_FILE=backup, RAW_DUMP_FILE=raw).returncode == 0
    )

    opened = _run(
        tmp_path, _gpg_line("restore.sh"), passphrase=PASSPHRASE + "x", BACKUP_FILE=backup
    )
    assert opened.returncode != 0
    assert raw.read_bytes() not in opened.stdout
