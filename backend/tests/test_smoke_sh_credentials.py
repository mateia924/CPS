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
