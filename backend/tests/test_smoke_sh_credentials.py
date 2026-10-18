"""Rule 50 (docs/SYSTEM_ANALYSIS.md §4): no default value for a credential
in any script. Until 2026-10-17 scripts/smoke.sh:23 fell back to a buried
password for accountant@fatma.test — published with the repo from 389ff53
(2026-09-23) on. smoke.sh now reads SMOKE_PASSWORD from the environment and
stops, loudly and before any request, when it is missing.

These run scripts/smoke.sh with a fake `curl` first on PATH, so no network,
container or database is touched. They need the repo's scripts/ — the dev
container mounts only backend/ at /app. Same declared skip as
tests/test_production_gates.py; scripts/ci_local.sh asserts they PASS there.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SMOKE = SCRIPTS / "smoke.sh"

pytestmark = pytest.mark.skipif(
    not SMOKE.exists(),
    reason="needs the repo's scripts/ (CI and ci_local have it; the dev container mounts only backend/)",
)

# `${SOME_PASSWORD:-literal}` — a fallback that is not another variable.
LITERAL_CREDENTIAL_DEFAULT = re.compile(
    r"\$\{[A-Z_]*(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY)[A-Z_]*:-[^}$]"
)


def _run_smoke(tmp_path, password=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "curl_calls"
    fake_curl = bin_dir / "curl"
    # Records the call and answers 503, so smoke.sh stops at its first step.
    fake_curl.write_text(f'#!/usr/bin/env bash\necho call >> "{calls}"\nprintf 503\n')
    fake_curl.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SMOKE_")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SMOKE_BASE_URL"] = "http://127.0.0.1:9/api"
    if password is not None:
        env["SMOKE_PASSWORD"] = password
    result = subprocess.run(
        ["bash", str(SMOKE)], env=env, capture_output=True, text=True, timeout=30
    )
    return result, (calls.read_text().count("call") if calls.exists() else 0)


def test_smoke_without_password_fails_loudly_before_any_request(tmp_path):
    result, curl_calls = _run_smoke(tmp_path)
    assert result.returncode != 0
    assert "SMOKE_PASSWORD is not set" in result.stderr
    assert curl_calls == 0


def test_smoke_with_password_gets_past_the_guard(tmp_path):
    # The other side of the guard: a set password reaches the login request.
    result, curl_calls = _run_smoke(tmp_path, password="placeholder-not-a-credential")
    assert "SMOKE_PASSWORD is not set" not in result.stderr
    assert curl_calls == 1


def test_no_script_carries_a_literal_credential_default():
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(SCRIPTS.glob("*.sh"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if LITERAL_CREDENTIAL_DEFAULT.search(line)
    ]
    assert offenders == []


# Rule 50, widened 2026-10-18 (Pre-deploy 3): no secret on a command line —
# `ps` shows every process's arguments to every user on the host. A value
# goes through the environment (`-e NAME`, never `-e NAME=value`), a file
# descriptor (`--passphrase-file <(printf ...)`) or stdin.
SECRET_ON_ARGV = re.compile(
    r"--passphrase(?!-file)[ =]|--password[ =]|-e [A-Z_]*(PASSWORD|PASSPHRASE|SECRET|TOKEN|API_KEY)[A-Z_]*="
    # A body or header that interpolates one (smoke.sh's login until Pre-deploy 3).
    r"|-d \".*\$[A-Z_]*(PASSWORD|SECRET|TOKEN)|Authorization: Bearer \$"
)

# Known, still open — each one named, so the list can only shrink: a new
# offender fails, and so does a fixed one left on the list. Not fixed in
# Pre-deploy 3 because they sit on live's backup/restore path (cron 03:00)
# or are throwaway CI/e2e values; each needs its own block.
KNOWN_OPEN_SECRET_ON_ARGV = {
    ("backup.sh", 'gpg --batch --yes --passphrase "$PASSPHRASE"'),
    ("backup.sh", '-e CPS_UPLOAD_SECRET_KEY="$UPLOAD_SECRET_KEY"'),
    ("restore.sh", 'gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE"'),
    ("restore_test.sh", 'gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE"'),
    ("ci_local.sh", "-e POSTGRES_PASSWORD=postgres"),
    ("ci_local.sh", '-e DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY"'),
    ("e2e.sh", '--password "SmokeE2E!2026"'),
}


def test_no_script_puts_a_secret_on_a_command_line_beyond_the_known_open_list():
    found = set()
    for path in sorted(SCRIPTS.glob("*.sh")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#") or not SECRET_ON_ARGV.search(line):
                continue
            known = [
                snippet
                for name, snippet in KNOWN_OPEN_SECRET_ON_ARGV
                if name == path.name and snippet in line
            ]
            found.add((path.name, known[0]) if known else (path.name, line.strip()))
    assert found == KNOWN_OPEN_SECRET_ON_ARGV


def test_smoke_sends_the_password_and_the_token_off_the_command_line(tmp_path):
    """Rule 50 (Pre-deploy 3): sampling `ps` during staging_refresh.sh
    --full caught smoke.sh's password in curl's `-d` and the access token
    in `-H "Authorization: Bearer ..."`. The fake curl logs its argv and
    keeps its stdin: the password must reach the login on stdin, and
    neither value may be in any curl's arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log, stdin_log = tmp_path / "argv", tmp_path / "stdin"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{argv_log}"\n'
        f'[ -t 0 ] || cat >> "{stdin_log}"\n'
        'out=""; prev=""; for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
        '[ -n "$out" ] && printf \'{"access": "tok-secret-123"}\' > "$out"\n'
        "printf 200\n"
    )
    fake_curl.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SMOKE_")}
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env.get('PATH', '')}", SMOKE_BASE_URL="http://127.0.0.1:9/api"
    )
    env["SMOKE_PASSWORD"] = "placeholder-not-a-credential"

    subprocess.run(
        ["bash", str(SMOKE)],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )

    argv = argv_log.read_text()
    assert len(argv.splitlines()) >= 2, "smoke.sh stopped before it used the token"
    assert "placeholder-not-a-credential" not in argv
    assert "tok-secret-123" not in argv
    assert "placeholder-not-a-credential" in stdin_log.read_text()
