"""Rule 50: scripts/precommit_guard.sh refuses staged secrets.

Until block 8.2.1 only its exclusion-list half was tested
(test_deploy_sh_guards.py). Its credential check had no test, and 8.2.1
narrowed it: in package-lock.json the npm package js-tokens, mapped to a
version range, read as a token with a literal value. These tests pin both
sides: a version-range dependency line passes, and every credential shape
around it is still refused.

The secret-looking inputs are assembled at runtime so this file's own
lines never match the guard it tests.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "scripts" / "precommit_guard.sh"

pytestmark = pytest.mark.skipif(
    not GUARD.exists() or shutil.which("git") is None,
    reason="needs the repo's scripts/ and git (CI and ci_local have them; the dev container does not)",
)

TOKEN = "".join(["to", "ken"])
PASSWORD = "".join(["pass", "word"])


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    for name in ("precommit_guard.sh", "standing_exclusions.sh"):
        shutil.copy(REPO / "scripts" / name, tmp_path / "scripts" / name)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "scripts"], check=True)
    subprocess.run([*git, "commit", "-q", "--no-verify", "-m", "base"], check=True)

    def stage(name, text):
        (tmp_path / name).write_text(text)
        subprocess.run([*git, "add", name], check=True)
        return subprocess.run(["bash", "scripts/precommit_guard.sh"], cwd=tmp_path, capture_output=True, text=True)

    return stage


@pytest.mark.parametrize(
    "line",
    [
        '        "js-' + TOKEN + 's": "^4.0.0",',
        '        "js-' + TOKEN + 's": "^3.0.0 || ^4.0.0"',
        '    "' + TOKEN + 'ize": "1.2.3",',
    ],
)
def test_a_dependency_line_with_only_a_version_range_passes(repo, line):
    result = repo("package-lock.json", "{\n" + line + "\n}\n")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "line",
    [
        '    "api_' + TOKEN + '": "a1b2c3d4e5f6",',
        '    "' + TOKEN + '": "4f9c2e1a77",',
        '    "' + TOKEN + '": "^4.0.0-but-not-a-version",',
        '    "' + TOKEN + '": "^4.0.0", "' + PASSWORD + '": "hunter22"',
        PASSWORD + ' = "correct-horse"',
        "DB_" + PASSWORD.upper() + "=s3cretvalue",
    ],
)
def test_a_credential_with_a_literal_value_is_still_refused(repo, line):
    result = repo("settings.txt", line + "\n")
    assert result.returncode == 1, result.stderr
    assert "settings.txt:1: credential with a literal value" in result.stderr
