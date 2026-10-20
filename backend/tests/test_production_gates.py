"""Pre-deploy 1, rule 32 (docs/SYSTEM_ANALYSIS.md §4): the staging
rehearsal runs production's own gates. Not "the same list kept in two
places" — one definition, scripts/production_gates.sh, that
scripts/deploy.sh and scripts/staging_refresh.sh both source and run
through cps_run_gates. Before it, the two scripts carried their own
copies and drifted: the rehearsal skipped add_missing_system_accounts and
check_chart_health entirely, and its full mode (the most destructive)
had neither smoke nor the readiness poll.

These read the scripts as text, so they need the repo's scripts/ — the
dev container mounts only backend/ at /app. Same declared skip as
tests/test_deploy_sh_guards.py; scripts/ci_local.sh asserts they PASS
there, so the skip can never quietly become "never runs anywhere".
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
GATES_FILE = SCRIPTS / "production_gates.sh"
CALLERS = ("deploy.sh", "staging_refresh.sh")

# What a gate looks like when someone runs it directly instead of through
# the shared definition — a private copy, i.e. the start of a drift.
GATE_COMMANDS = {
    "backup": r"scripts/backup\.sh",
    "migrate": r"manage\.py\s+migrate\b",
    "setup_rls": r"manage\.py\s+setup_rls\b",
    "verify_rls": r"pg_policies",
    "add_missing_system_accounts": r"add_missing_system_accounts",
    "check_chart_health": r"check_chart_health",
    "ready": r"/admin/login/",
    "smoke": r"smoke\.sh",
}

pytestmark = pytest.mark.skipif(
    not GATES_FILE.exists(),
    reason="needs the repo's scripts/ (CI and ci_local have it; the dev container mounts only backend/)",
)


def _code(path):
    """The script without comment lines and without the messages it
    prints — either may name a gate without running it."""
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith(("#", "echo ", "log "))
    )


def _gate_list():
    match = re.search(r"^CPS_PRODUCTION_GATES=\(\n(.*?)\n\)", _code(GATES_FILE), re.S | re.M)
    assert match, "production_gates.sh must define CPS_PRODUCTION_GATES=( ... )"
    return match.group(1).split()


def test_the_shared_definition_holds_every_production_gate_in_order():
    assert _gate_list() == [
        "backup",
        "migrate",
        "setup_rls",
        "verify_rls",
        "add_missing_system_accounts",
        "check_chart_health",
        "start",
        "ready",
        "smoke",
    ]
    code = _code(GATES_FILE)
    for gate in _gate_list():
        assert re.search(rf"^cps_gate_{gate}\(\) {{", code, re.M), f"no cps_gate_{gate} function"
    assert re.search(r"check_chart_health --fail-on-findings", code)
    assert re.search(r'backup\.sh" --target "\$GATE_BACKUP_TARGET"', code)


@pytest.mark.parametrize("caller", CALLERS)
def test_caller_runs_the_shared_gates_and_holds_none_of_its_own(caller):
    code = _code(SCRIPTS / caller)

    assert re.search(r'^\s*source "\$REPO_DIR/scripts/production_gates\.sh"$', code, re.M), (
        f"{caller} does not source scripts/production_gates.sh"
    )
    runs = re.findall(r"^.*\bcps_run_gates\b.*$", code, re.M)
    assert len(runs) == 1, f"{caller} must call cps_run_gates exactly once, found {runs}"
    # At the top level, not inside one mode's branch: every mode passes it.
    assert not runs[0].startswith((" ", "\t")), (
        f"{caller} calls cps_run_gates inside a branch: {runs[0]!r}"
    )

    assert "CPS_PRODUCTION_GATES" not in code, f"{caller} defines or edits a gate list of its own"
    assert not re.search(r"^\s*cps_gate_\w+\(\)", code, re.M), (
        f"{caller} defines a gate function of its own"
    )

    private = {
        gate: re.findall(rf"^.*{pattern}.*$", code, re.M) for gate, pattern in GATE_COMMANDS.items()
    }
    private = {gate: lines for gate, lines in private.items() if lines}
    assert not private, (
        f"{caller} runs production gates of its own instead of the shared definition: {private}"
    )


# --- Pre-deploy 1 fixes: the scripts' behavior, not only their text. ---
# Each test copies the real scripts into tmp_path and runs them with
# stand-ins for docker, gpg, find and curl that log every call to CALLS
# (and fail the call whose command line contains FAIL_ON), plus stub
# backup.sh/smoke.sh. No container, database or port is ever touched.

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
[ -t 0 ] || cat > /dev/null
if [ -n "${FAIL_ON:-}" ] && [[ "$*" == *"$FAIL_ON"* ]]; then exit 1; fi
case "$*" in
  "inspect -f "*) var="FAKE_INSPECT_${@: -1}"; echo "${!var:-infra-backend sha256:0ld1mage infra backend}" ;;
  *"u.email"*) echo "real.local.part@fatma.staging.test" ;;
  *"settings.EMAIL_BACKEND"*) echo "${FAKE_EMAIL_BACKEND-django.core.mail.backends.dummy.EmailBackend}" ;;
  *" ps -a -q") echo "${FAKE_CONTAINERS:-}" ;;
  *pg_policies*) echo "3 3" ;;
esac
"""


def _fake_tree(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "infra").mkdir()
    for name in ("staging_refresh.sh", "production_gates.sh"):
        (repo / "scripts" / name).write_text(
            (SCRIPTS / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (repo / ".env").write_text("CPS_BACKUP_ENCRYPTION_PASSPHRASE=test-passphrase\n")
    (repo / ".env.staging").write_text(
        "POSTGRES_USER=postgres\nPOSTGRES_DB=cps\nSTAGING_UAT_PASSWORD=uat-pass\n"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        bin_dir / "docker": FAKE_DOCKER,
        bin_dir
        / "gpg": '#!/usr/bin/env bash\necho "gpg $*" >> "$CALLS"\nprintf "SELECT 1;\\n" | gzip -c\n',
        bin_dir / "find": '#!/usr/bin/env bash\necho "1 /opt/cps-backups/cps-db-test.sql.gz.gpg"\n',
        bin_dir
        / "curl": '#!/usr/bin/env bash\necho "curl" >> "$CALLS"\nprintf "%s" "${CURL_STATUS:-502}"\n',
        repo / "scripts" / "backup.sh": '#!/usr/bin/env bash\necho "backup.sh $*" >> "$CALLS"\n',
        repo
        / "scripts"
        / "smoke.sh": '#!/usr/bin/env bash\necho "smoke.sh $SMOKE_EMAIL" >> "$CALLS"\n',
    }
    for path, body in stubs.items():
        path.write_text(body)
        path.chmod(0o755)

    calls = tmp_path / "calls.log"
    calls.write_text("")
    env = {
        "PATH": f"{bin_dir}:/usr/local/bin:/usr/bin:/bin",
        "CALLS": str(calls),
        "HOME": str(tmp_path),
    }
    return repo, calls, env


def _run(cmd, cwd, env, **extra_env):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env={**env, **extra_env},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    "args, named",
    [
        (["--code-onyl"], '"--code-onyl"'),
        (["--full", "--code-onyl"], '"--code-onyl"'),
        (["--full", "--code-only"], "--code-only"),
        ([], "--full"),
    ],
)
def test_staging_refresh_refuses_a_typo_or_a_missing_mode_before_touching_anything(
    tmp_path, args, named
):
    """`--code-onyl` used to mean "full": wipe staging's UAT data."""
    repo, calls, env = _fake_tree(tmp_path)

    result = _run(["bash", "scripts/staging_refresh.sh", *args], repo, env)

    assert result.returncode == 2
    assert named in result.stderr
    assert "Usage: scripts/staging_refresh.sh --full | --code-only" in result.stderr
    assert calls.read_text() == "", f"ran something before refusing: {calls.read_text()}"


def test_full_refresh_anonymizes_before_the_first_gate_so_a_failed_gate_leaves_no_real_data(
    tmp_path,
):
    repo, calls, env = _fake_tree(tmp_path)

    result = _run(
        ["bash", "scripts/staging_refresh.sh", "--full"], repo, env, FAIL_ON="manage.py migrate"
    )

    assert result.returncode == 1
    assert 'failed production gate "migrate"' in result.stderr
    log = calls.read_text().splitlines()
    restore = next(i for i, line in enumerate(log) if line.startswith("gpg "))
    anonymize = [i for i, line in enumerate(log) if "anonymize_staging_users" in line]
    first_gate = next(
        i
        for i, line in enumerate(log)
        if "backup.sh --target staging staging_refresh.sh --full (pre-migrate" in line
    )
    assert (
        len(anonymize) == 1
        and "run --rm -e STAGING_UAT_PASSWORD --entrypoint  backend" in log[anonymize[0]]
    )
    assert restore < anonymize[0] < first_gate
    assert any("manage.py migrate" in line for line in log[first_gate:])
    # The gate's failure is not an anonymize failure: the data stays.
    assert not any("--force" in line for line in log)


def test_full_refresh_drops_the_database_if_anonymize_does_not_finish(tmp_path):
    repo, calls, env = _fake_tree(tmp_path)

    result = _run(
        ["bash", "scripts/staging_refresh.sh", "--full"],
        repo,
        env,
        FAIL_ON="anonymize_staging_users",
    )

    assert result.returncode != 0
    log = calls.read_text().splitlines()
    assert "dropdb -U postgres --if-exists --force cps" in log[-1]
    assert "Dropping the staging database" in result.stderr
    assert not any("pre-migrate" in line or "manage.py migrate" in line for line in log), (
        "a gate ran on real data"
    )


@pytest.mark.parametrize("status", ["502", "503", "504", "000"])
def test_ready_waits_180s_and_on_timeout_says_502_and_prints_the_rollback(tmp_path, status):
    """504 included: rule 36's outage — nginx's own 60s proxy timeout
    while every container was `Up` — must not read as "ready"."""
    shipped = re.search(r"^CPS_READY_TIMEOUT_SECONDS=(\d+)$", _code(GATES_FILE), re.M)
    assert shipped and int(shipped.group(1)) >= 180
    # One request outlives nginx's 60s, so a hung backend ends as a 504.
    max_time = re.search(r"curl -s -o /dev/null --max-time (\d+) ", _code(GATES_FILE))
    assert max_time and int(max_time.group(1)) > 60

    repo, calls, env = _fake_tree(tmp_path)
    script = """
source scripts/production_gates.sh
GATE_REPO_DIR="$PWD" GATE_COMPOSE="docker compose -p infra" GATE_BACKUP_TARGET=live GATE_HTTP_PORT=3000
cps_gate_start || exit 9
CPS_READY_TIMEOUT_SECONDS=3
cps_gate_ready
"""
    result = _run(["bash", "-c", script], repo, env, FAKE_CONTAINERS="c1", CURL_STATUS=status)

    assert result.returncode == 1
    log = calls.read_text()
    assert re.search(r"^docker tag sha256:0ld1mage infra-backend:rollback-\d{8}-\d{6}$", log, re.M)
    assert log.index("tag sha256:0ld1mage") < log.index("compose -p infra up -d")
    assert "live (port 3000) MAY BE SERVING 502" in result.stderr
    assert re.search(
        r"^  cd \S+/infra && docker tag infra-backend:rollback-\d{8}-\d{6} infra-backend:latest && "
        r"docker compose -p infra up -d --no-build && docker compose -p infra restart nginx$",
        result.stderr,
        re.M,
    )
    assert f"last status: {status}" in result.stderr
    assert "Nothing was rolled back automatically" in result.stderr


def test_ready_accepts_any_status_that_came_from_django(tmp_path):
    repo, calls, env = _fake_tree(tmp_path)
    script = """
source scripts/production_gates.sh
GATE_REPO_DIR="$PWD" GATE_COMPOSE="docker compose -p infra" GATE_BACKUP_TARGET=live GATE_HTTP_PORT=3000
cps_gate_ready
"""
    result = _run(["bash", "-c", script], repo, env, CURL_STATUS="200")
    assert result.returncode == 0, result.stderr


# --- Pre-deploy 2, rule 50: the secrets preflight runs before the first gate. ---

_GATES_SCRIPT = """
source scripts/production_gates.sh
GATE_REPO_DIR="$PWD" GATE_COMPOSE="docker compose -p infra" GATE_BACKUP_TARGET=live
GATE_BACKUP_REASON=test GATE_HTTP_PORT=3000
cps_run_gates
rc=$?
echo "failed gate: $CPS_FAILED_GATE"
exit $rc
"""


def _secrets_dir(tmp_path, repo, content=None, mode=0o600):
    """A stand-in for /etc/cps-secrets. The path is a literal in
    production_gates.sh, with no variable to point it elsewhere — so the
    test rewrites its own copy of the script, never the real one."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    if content is not None:
        (secrets / "smoke_password").write_text(content)
        (secrets / "smoke_password").chmod(mode)
    gates = repo / "scripts" / "production_gates.sh"
    text = gates.read_text(encoding="utf-8")
    assert "/etc/cps-secrets" in text
    text = text.replace("/etc/cps-secrets", str(secrets))
    # 2026-10-20 (CI coverage): GitHub's runner is uid 1001, so a file this
    # test creates can never be root-owned, and the preflight's "owner is
    # uid 0" check refused every one (4 failures the first time CI ran this
    # file at all). As with the path above, only this test's copy changes:
    # the expected owner becomes the uid running the test. The real script
    # keeps requiring root; as root (the dev container) nothing is rewritten.
    if os.getuid() != 0:
        owner_check = '[ "$owner" != "0" ]'
        assert text.count(owner_check) == 1, "the preflight's owner check moved; update this test"
        text = text.replace(owner_check, f'[ "$owner" != "{os.getuid()}" ]')
    gates.write_text(text, encoding="utf-8")
    return secrets


def test_secrets_preflight_stops_the_deploy_before_the_first_gate_when_the_smoke_password_is_missing(
    tmp_path,
):
    repo, calls, env = _fake_tree(tmp_path)
    secrets = _secrets_dir(tmp_path, repo)

    result = _run(["bash", "-c", _GATES_SCRIPT], repo, env, CURL_STATUS="200")

    assert result.returncode == 1
    assert "failed gate: secrets preflight" in result.stdout
    assert f"{secrets}/smoke_password does not exist" in result.stderr
    assert "root:root, mode 600" in result.stderr
    assert calls.read_text() == "", f"a gate ran before the preflight: {calls.read_text()}"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_secrets_preflight_refuses_a_smoke_password_file_others_can_read(tmp_path, mode):
    repo, calls, env = _fake_tree(tmp_path)
    _secrets_dir(tmp_path, repo, "s3cret-value\n", mode)

    result = _run(["bash", "-c", _GATES_SCRIPT], repo, env, CURL_STATUS="200")

    assert result.returncode == 1
    assert f"mode {mode:o}" in result.stderr and "must be root:root, mode 600" in result.stderr
    assert "s3cret-value" not in result.stdout + result.stderr
    assert calls.read_text() == ""


def test_secrets_preflight_hands_smoke_the_password_without_its_trailing_newline(tmp_path):
    repo, calls, env = _fake_tree(tmp_path)
    _secrets_dir(tmp_path, repo, "s3cret-value\r\n")
    (repo / "scripts" / "smoke.sh").write_text(
        '#!/usr/bin/env bash\n[ "$SMOKE_PASSWORD" = "s3cret-value" ] && echo "smoke.sh exact" >> "$CALLS"\n'
    )

    # verify_rls and the rest need a real stack: preflight, then gate smoke alone.
    script = """
source scripts/production_gates.sh
GATE_REPO_DIR="$PWD" GATE_HTTP_PORT=3000 GATE_BACKUP_TARGET=live
cps_gates_preflight && cps_gate_smoke
"""
    result = _run(
        ["bash", "-c", script],
        repo,
        env,
        SMOKE_PASSWORD="stale-shell-value",
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines()[-1] == "smoke.sh exact"
    assert "s3cret-value" not in result.stdout + result.stderr


def test_deploy_runs_the_secrets_preflight_before_build():
    code = _code(SCRIPTS / "deploy.sh")
    preflight = re.search(r"^cps_gates_preflight \|\| fail ", code, re.M)
    build = re.search(r"^\$COMPOSE build\b", code, re.M)
    assert preflight and build and preflight.start() < build.start()


@pytest.mark.parametrize("mode", ["--code-only", "--full"])
def test_staging_refresh_passes_the_same_preflight_before_build_or_wipe(tmp_path, mode):
    repo, calls, env = _fake_tree(tmp_path)
    (repo / ".env.staging").write_text("POSTGRES_USER=postgres\nPOSTGRES_DB=cps\n")

    result = _run(["bash", "scripts/staging_refresh.sh", mode], repo, env)

    assert result.returncode == 1
    assert "secrets preflight: SMOKE_PASSWORD is empty" in result.stderr
    if mode == "--full":
        assert "secrets preflight: STAGING_UAT_PASSWORD is empty" in result.stderr
    assert calls.read_text() == "", f"ran something before the preflight: {calls.read_text()}"


@pytest.mark.parametrize(
    "injected",
    [
        {"GATE_SMOKE_PASSWORD_FROM": "env"},
        {"GATE_SMOKE_PASSWORD_FROM": "staging"},
        {"CPS_SECRETS_DIR": "elsewhere"},
    ],
)
def test_secrets_preflight_on_live_has_no_switch_that_skips_the_file_check(tmp_path, injected):
    """Rules 49/50: a variable that turns a guard off is a kill switch, not
    a guard. Whatever the environment says, live reads the one fixed path
    and checks it — here it is missing, so the run must stop."""
    repo, calls, env = _fake_tree(tmp_path)
    secrets = _secrets_dir(tmp_path, repo)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "smoke_password").write_text("s3cret-value\n")
    (other / "smoke_password").chmod(0o600)
    extra = {k: (str(other) if v == "elsewhere" else v) for k, v in injected.items()}

    result = _run(
        ["bash", "-c", _GATES_SCRIPT],
        repo,
        env,
        CURL_STATUS="200",
        SMOKE_PASSWORD="from-the-shell",
        **extra,
    )

    assert result.returncode == 1
    assert "failed gate: secrets preflight" in result.stdout
    assert f"{secrets}/smoke_password does not exist" in result.stderr
    assert calls.read_text() == ""


def test_secrets_preflight_refuses_a_target_that_is_neither_live_nor_staging(tmp_path):
    repo, calls, env = _fake_tree(tmp_path)
    script = _GATES_SCRIPT.replace("GATE_BACKUP_TARGET=live", "GATE_BACKUP_TARGET=dev")

    result = _run(["bash", "-c", script], repo, env, CURL_STATUS="200", SMOKE_PASSWORD="x")

    assert result.returncode == 1
    assert "failed gate: secrets preflight" in result.stdout
    assert 'knows GATE_BACKUP_TARGET live and staging only, got "dev"' in result.stderr
    assert calls.read_text() == ""


@pytest.mark.parametrize("mode", ["--full", "--code-only"])
def test_staging_refresh_runs_to_the_end_without_printing_the_staging_password(tmp_path, mode):
    """Rule 50 (2026-10-18): the end of a full run used to print
    STAGING_UAT_PASSWORD "once" — into every terminal scrollback, CI log
    and Claude Code session log that captured it. It names the variable
    and its source now, never the value."""
    repo, calls, env = _fake_tree(tmp_path)

    result = _run(["bash", "scripts/staging_refresh.sh", mode], repo, env, CURL_STATUS="200")

    assert result.returncode == 0, result.stderr
    assert any(line.startswith("smoke.sh ") for line in calls.read_text().splitlines())
    output = result.stdout + result.stderr
    assert "uat-pass" not in output
    if mode == "--full":
        assert "STAGING_UAT_PASSWORD from .env.staging" in result.stdout


def _live_reads():
    """Every image tag live's containers read: the external images the
    shared compose file pins, and infra-<service> for each built one."""
    compose = (SCRIPTS.parent / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    external = set(re.findall(r"^\s+image:\s*(\S+)\s*$", compose, re.M))
    assert {"postgres:16-alpine", "redis:7-alpine"} <= external
    built = {f"infra-{name}:latest" for name in ("backend", "celery_worker", "frontend")}
    return external | built


def test_start_on_staging_changes_no_image_tag_that_live_reads(tmp_path):
    """Pre-deploy 3: staging and live share the host's one image store.
    `start` tagged every container's image, and the printed rollback
    re-tagged postgres:16-alpine & co. — tags live's containers read —
    to staging's images. Run `start` on staging, then the rollback it
    prints: neither may write a tag live reads, and every tag either
    writes must carry the staging project's name."""
    repo, calls, env = _fake_tree(tmp_path)
    containers = {
        "sb": "cps-staging-backend sha256:stagingbackend cps-staging backend",
        "sw": "cps-staging-celery_worker sha256:stagingworker cps-staging celery_worker",
        "sp": "postgres:16-alpine sha256:stagingpostgres cps-staging postgres",
        "sn": "nginx:1.27-alpine sha256:stagingnginx cps-staging nginx",
        "sr": "redis:7-alpine sha256:stagingredis cps-staging redis",
    }
    script = """
source scripts/production_gates.sh
GATE_REPO_DIR="$PWD" GATE_COMPOSE="docker compose -p cps-staging" GATE_BACKUP_TARGET=staging GATE_HTTP_PORT=3001
cps_gate_start || exit 9
echo "ROLLBACK=$CPS_ROLLBACK_COMMAND"
eval "$CPS_ROLLBACK_COMMAND"
"""
    result = _run(
        ["bash", "-c", script],
        repo,
        env,
        FAKE_CONTAINERS=" ".join(containers),
        **{f"FAKE_INSPECT_{cid}": info for cid, info in containers.items()},
    )

    assert result.returncode == 0, result.stderr
    written = [
        line.split()[-1]
        for line in calls.read_text().splitlines()
        if line.startswith("docker tag ")
    ]
    assert written, "start tagged nothing — the rollback target is gone"
    assert not set(written) & _live_reads(), (
        f"wrote a tag live reads: {set(written) & _live_reads()}"
    )
    assert all(tag.startswith("cps-staging-") for tag in written), written
    rollback = re.search(r"^ROLLBACK=(.*)$", result.stdout, re.M).group(1)
    # Image references, not service names (`restart nginx` is the service).
    for external in ("postgres:", "nginx:", "redis:"):
        assert external not in rollback, rollback
    assert "not tagged (external, pinned by their own tag" in result.stdout


def test_staging_refresh_puts_no_secret_on_a_command_line(tmp_path):
    """Rule 50 (Pre-deploy 3): `ps` shows every process's arguments to
    every user on the host. The fake docker and gpg log their own argv:
    neither the anonymize password nor the backup passphrase may be in
    it — the password travels in the environment (`-e` names it), the
    passphrase through a file descriptor."""
    repo, calls, env = _fake_tree(tmp_path)

    result = _run(["bash", "scripts/staging_refresh.sh", "--full"], repo, env, CURL_STATUS="200")

    assert result.returncode == 0, result.stderr
    argv = calls.read_text()
    assert "uat-pass" not in argv
    assert "test-passphrase" not in argv
    assert re.search(
        r"^docker compose .* run --rm -e STAGING_UAT_PASSWORD .*anonymize_staging_users$",
        argv,
        re.M,
    )
    assert re.search(r"^gpg .*--passphrase-file /dev/fd/\d+ ", argv, re.M)


def test_staging_refresh_describes_the_owner_account_without_printing_their_email(tmp_path):
    """Pre-deploy 3: the local part of an email survives anonymize — it is
    the real person's. The last lines describe the account; the fake
    answers an email query with one, and it must not reach the output."""
    repo, calls, env = _fake_tree(tmp_path)

    result = _run(["bash", "scripts/staging_refresh.sh", "--full"], repo, env, CURL_STATUS="200")

    assert result.returncode == 0, result.stderr
    assert "real.local.part" not in result.stdout + result.stderr
    assert "Fatma's Owner (" in result.stdout and "not printed (rule 50)" in result.stdout


# --- 2026-10-19: what the target does with mail is printed before gate 1. ---


def test_the_email_backend_the_new_image_selects_is_printed_before_the_first_gate(tmp_path):
    repo, calls, env = _fake_tree(tmp_path)
    _secrets_dir(tmp_path, repo, content="pw\n")

    result = _run(["bash", "-c", _GATES_SCRIPT], repo, env, CURL_STATUS="200")

    assert result.returncode == 0, result.stderr
    out = result.stdout
    line = "email backend for live: django.core.mail.backends.dummy.EmailBackend"
    assert line in out
    assert out.index("secrets preflight passed.") < out.index(line) < out.index("gate 1/9: backup")
    assert "manage.py shell -c from django.conf import settings" in calls.read_text()


@pytest.mark.parametrize("answer", ["", "Traceback (most recent call last):"])
def test_no_readable_email_backend_stops_the_run_before_the_first_gate(tmp_path, answer):
    repo, calls, env = _fake_tree(tmp_path)
    _secrets_dir(tmp_path, repo, content="pw\n")

    result = _run(["bash", "-c", _GATES_SCRIPT], repo, env, CURL_STATUS="200", FAKE_EMAIL_BACKEND=answer)

    assert result.returncode == 1
    assert "failed gate: email backend report" in result.stdout
    assert "could not read the email backend" in result.stderr
    assert "gate 1/9: backup" not in result.stdout
    assert "backup.sh" not in calls.read_text()
