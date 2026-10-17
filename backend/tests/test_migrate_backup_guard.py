"""Sprint 6.5.16 (incident: sprint 6.5.15's six data migrations ran
against the live dev database with no prior backup at all —
scripts/backup.sh only ran once, after the fact, at the end of the
block). apps.tenants.management.commands.migrate overrides Django's
own migrate command to refuse a pending migration against a real
(non-test) database with no fresh backups.log entry.
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

import pytest
from django.core.management.base import CommandError
from django.db import connection

from apps.tenants.management.commands.migrate import Command

MODULE = "apps.tenants.management.commands.migrate"
# Pre-deploy 1: what backup.sh writes and the guard computes for its own
# connection. Live and dev share host/name (postgres/cps); only the
# cluster's system_identifier differs — these are their real values.
THIS_DB = "postgres/cps#7691754161498136610"
OTHER_DB = "postgres/cps#7686947508661833762"


def _line(when, db=THIS_DB, reason="backup"):
    fields = [when.isoformat(), "abc123", "cps-db-x.sql.gz.gpg", reason]
    if db is not None:
        fields.append(f"db={db}")
    return "\t".join(fields)


def _pending(mock_executor_cls):
    mock_executor = mock_executor_cls.return_value
    mock_executor.loader.applied_migrations = {"something": True}
    mock_executor.loader.graph.leaf_nodes.return_value = []
    mock_executor.migration_plan.return_value = [("fake_migration",)]


def _write_log(tmp_path, lines):
    log = tmp_path / "backups.log"
    log.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return log


@pytest.mark.django_db
def test_last_backup_timestamp_is_the_newest_line_for_this_database(tmp_path):
    log = _write_log(
        tmp_path,
        [
            "# a header comment",
            "2026-09-29T13:59:35+03:00\tabc123\tfile1.sql.gz\tfirst reason\tdb=" + THIS_DB,
            "2026-09-29T20:28:15+03:00\tdef456\tfile2.sql.gz\tsecond reason\tdb=" + THIS_DB,
            "2026-09-29T21:00:00+03:00\tdef456\tfile3.sql.gz\tanother database\tdb=" + OTHER_DB,
            "2026-09-29T22:00:00+03:00\tdef456\tfile4.sql.gz\told format, no db field",
        ],
    )
    with patch(f"{MODULE}.BACKUPS_LOG_PATH", log):
        parsed = Command()._last_backup_timestamp(THIS_DB)
    assert parsed == datetime.fromisoformat("2026-09-29T20:28:15+03:00")


@pytest.mark.django_db
def test_last_backup_timestamp_none_for_missing_file(tmp_path):
    with patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "does-not-exist.log"):
        assert Command()._last_backup_timestamp(THIS_DB) is None


@pytest.mark.django_db
def test_last_backup_timestamp_none_for_comment_only_file(tmp_path):
    log = _write_log(tmp_path, ["# nothing here but comments", "# another one"])
    with patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", log):
        assert Command()._last_backup_timestamp(THIS_DB) is None


@pytest.mark.django_db
def test_guard_never_blocks_the_pytest_test_database():
    """The exact exemption that makes this whole suite (and pytest-
    django's own internal `migrate` call to build the test database)
    possible at all — connection.settings_dict["NAME"] under pytest
    always starts with "test_"."""
    assert connection.settings_dict["NAME"].startswith("test_")
    with patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", "/definitely/does/not/exist.log"):
        Command()._guard_recent_backup()  # must not raise


def test_guard_refuses_a_real_database_with_no_backup_log(tmp_path):
    """Not @django_db — this test deliberately impersonates a real
    (non-test) database name to exercise the refusal path, so it must
    never touch the actual test database connection at all."""
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"), \
         patch("apps.tenants.management.commands.migrate.MigrationExecutor") as mock_executor_cls:
        mock_executor = mock_executor_cls.return_value
        mock_executor.loader.applied_migrations = {"something": True}
        mock_executor.loader.graph.leaf_nodes.return_value = []
        mock_executor.migration_plan.return_value = [("fake_migration",)]

        with pytest.raises(CommandError, match="migrate رُفض"):
            Command()._guard_recent_backup()


def test_guard_refuses_a_real_database_with_a_stale_backup(tmp_path):
    stale = datetime.now(dt_timezone.utc) - timedelta(minutes=30)
    log = _write_log(tmp_path, [_line(stale)])

    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", log), \
         patch("apps.tenants.management.commands.migrate.MigrationExecutor") as mock_executor_cls:
        mock_executor = mock_executor_cls.return_value
        mock_executor.loader.applied_migrations = {"something": True}
        mock_executor.loader.graph.leaf_nodes.return_value = []
        mock_executor.migration_plan.return_value = [("fake_migration",)]

        with pytest.raises(CommandError, match="آخر نسخة احتياطية"):
            Command()._guard_recent_backup()


def test_guard_passes_a_real_database_with_a_fresh_backup(tmp_path):
    fresh = datetime.now(dt_timezone.utc) - timedelta(minutes=2)
    log = _write_log(tmp_path, [_line(fresh)])

    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", log), \
         patch("apps.tenants.management.commands.migrate.MigrationExecutor") as mock_executor_cls:
        mock_executor = mock_executor_cls.return_value
        mock_executor.loader.applied_migrations = {"something": True}
        mock_executor.loader.graph.leaf_nodes.return_value = []
        mock_executor.migration_plan.return_value = [("fake_migration",)]

        Command()._guard_recent_backup()  # must not raise


def test_guard_skips_when_nothing_is_pending(tmp_path):
    """The routine-restart case — an already-up-to-date real database
    must never be blocked just because backups.log is stale/missing."""
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"), \
         patch("apps.tenants.management.commands.migrate.MigrationExecutor") as mock_executor_cls:
        mock_executor = mock_executor_cls.return_value
        mock_executor.loader.applied_migrations = {"something": True}
        mock_executor.loader.graph.leaf_nodes.return_value = []
        mock_executor.migration_plan.return_value = []

        Command()._guard_recent_backup()  # must not raise


@pytest.mark.django_db
def test_guard_does_not_block_a_real_restart_with_nothing_pending(tmp_path):
    """Integration-level, no MigrationExecutor mock at all — the exact
    thing docker-compose's own `migrate --noinput` runs on every
    backend container restart. The pytest test database is already
    fully migrated by the time any test runs, standing in for "a real,
    up-to-date database"; only the test_-prefix pretense and the
    backups.log path are faked, so this exercises the real Django
    migration executor against a real connection end to end. Without
    the "nothing pending -> skip" check, this would raise even though
    backups.log is missing — exactly the regression this test guards."""
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"):
        Command()._guard_recent_backup()  # must not raise


def test_guard_skips_a_brand_new_database_with_nothing_applied_yet(tmp_path):
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"), \
         patch("apps.tenants.management.commands.migrate.MigrationExecutor") as mock_executor_cls:
        mock_executor = mock_executor_cls.return_value
        mock_executor.loader.applied_migrations = {}

        Command()._guard_recent_backup()  # must not raise


def test_guard_bypass_env_var_skips_everything_in_dev(tmp_path, monkeypatch):
    monkeypatch.setenv("CPS_SKIP_BACKUP_GUARD", "1")
    monkeypatch.setenv("CPS_ENVIRONMENT", "dev")
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"):
        Command()._guard_recent_backup()  # must not raise, must not even query the DB


def test_guard_rejects_even_with_ci_and_github_actions_env_vars_set(tmp_path, monkeypatch):
    """Rule 11 (CI #67): this guard once exempted itself unconditionally
    whenever CI=true or GITHUB_ACTIONS=true — exactly the two vars every
    GitHub Actions runner sets on every job with no opt-in, so the
    guard was silently off for anyone running under CI, not just the
    e2e job's own (fresh-database, never actually blocked) migrate
    call. CPS_ENVIRONMENT=production here too, since the removed
    branch must never come back conditioned on CPS_ENVIRONMENT either —
    this is the one test that proves the off switch is actually gone,
    not just that the two tests above it are green again."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("CPS_ENVIRONMENT", "production")
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"), \
         patch("apps.tenants.management.commands.migrate.MigrationExecutor") as mock_executor_cls:
        mock_executor = mock_executor_cls.return_value
        mock_executor.loader.applied_migrations = {"something": True}
        mock_executor.loader.graph.leaf_nodes.return_value = []
        mock_executor.migration_plan.return_value = [("fake_migration",)]

        with pytest.raises(CommandError, match="migrate رُفض"):
            Command()._guard_recent_backup()


# --- Pre-deploy 1: the guard verifies the database, not the clock ---------
# Rule 49 (docs/SYSTEM_ANALYSIS.md §4): each guard below was disabled by
# name, its test seen failing by name, and the guard restored.


def test_guard_refuses_a_fresh_backup_of_another_database(tmp_path):
    """Live and dev are both postgres/cps: a dump of dev taken a minute
    ago must not let a migration through on live, nor the reverse."""
    fresh = datetime.now(dt_timezone.utc) - timedelta(minutes=1)
    log = _write_log(tmp_path, [_line(fresh, db=OTHER_DB)])
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch(f"{MODULE}.BACKUPS_LOG_PATH", log), \
         patch(f"{MODULE}.MigrationExecutor") as mock_executor_cls:
        _pending(mock_executor_cls)
        with pytest.raises(CommandError, match="لا يوجد في .* أي سطر نسخة لهذه القاعدة"):
            Command()._guard_recent_backup()


def test_guard_refuses_a_fresh_line_in_the_old_format(tmp_path):
    """Fail closed: a line with no db= field names no database."""
    fresh = datetime.now(dt_timezone.utc) - timedelta(minutes=1)
    log = _write_log(tmp_path, [_line(fresh, db=None)])
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch(f"{MODULE}.BACKUPS_LOG_PATH", log), \
         patch(f"{MODULE}.MigrationExecutor") as mock_executor_cls:
        _pending(mock_executor_cls)
        with pytest.raises(CommandError, match="أي سطر نسخة لهذه القاعدة"):
            Command()._guard_recent_backup()


def test_guard_refuses_when_the_database_cannot_say_who_it_is(tmp_path):
    fresh = datetime.now(dt_timezone.utc) - timedelta(minutes=1)
    log = _write_log(tmp_path, [_line(fresh)])
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", side_effect=RuntimeError("permission denied")), \
         patch(f"{MODULE}.BACKUPS_LOG_PATH", log), \
         patch(f"{MODULE}.MigrationExecutor") as mock_executor_cls:
        _pending(mock_executor_cls)
        with pytest.raises(CommandError, match="تعذّر تعريف القاعدة الحالية"):
            Command()._guard_recent_backup()


@pytest.mark.parametrize("environment", ["production", "staging", "ci", None])
def test_skip_guard_is_refused_outside_dev(tmp_path, monkeypatch, environment):
    """Refused, not warned about — and refused even with nothing
    pending, before the executor is consulted at all."""
    monkeypatch.setenv("CPS_SKIP_BACKUP_GUARD", "1")
    if environment is None:
        monkeypatch.delenv("CPS_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("CPS_ENVIRONMENT", environment)
    shown = environment or "غير مضبوط"
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.BACKUPS_LOG_PATH", tmp_path / "missing.log"), \
         patch(f"{MODULE}.MigrationExecutor") as mock_executor_cls:
        with pytest.raises(
            CommandError, match=f"CPS_SKIP_BACKUP_GUARD=1 مسموح فقط حين CPS_ENVIRONMENT=dev.*CPS_ENVIRONMENT={shown}"
        ):
            Command()._guard_recent_backup()
        mock_executor_cls.assert_not_called()


@pytest.mark.parametrize("environment", ["production", "staging", "ci", None])
def test_backups_log_path_override_is_refused_outside_dev(tmp_path, monkeypatch, environment):
    """A log of one's own choosing, with a fresh line for exactly this
    database in it, is refused all the same outside dev."""
    fresh = datetime.now(dt_timezone.utc) - timedelta(minutes=1)
    planted = _write_log(tmp_path, [_line(fresh)])
    monkeypatch.setenv("CPS_BACKUPS_LOG_PATH", str(planted))
    if environment is None:
        monkeypatch.delenv("CPS_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("CPS_ENVIRONMENT", environment)
    shown = environment or "غير مضبوط"
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch(f"{MODULE}.MigrationExecutor") as mock_executor_cls:
        _pending(mock_executor_cls)
        with pytest.raises(
            CommandError, match=f"CPS_BACKUPS_LOG_PATH=.* مسموح فقط حين CPS_ENVIRONMENT=dev.*CPS_ENVIRONMENT={shown}"
        ):
            Command()._guard_recent_backup()


def test_backups_log_path_override_is_honored_in_dev(tmp_path, monkeypatch):
    fresh = datetime.now(dt_timezone.utc) - timedelta(minutes=1)
    planted = _write_log(tmp_path, [_line(fresh)])
    monkeypatch.setenv("CPS_BACKUPS_LOG_PATH", str(planted))
    monkeypatch.setenv("CPS_ENVIRONMENT", "dev")
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch(f"{MODULE}.database_identity", return_value=THIS_DB), \
         patch(f"{MODULE}.BACKUPS_LOG_PATH", tmp_path / "default-missing.log"), \
         patch(f"{MODULE}.MigrationExecutor") as mock_executor_cls:
        _pending(mock_executor_cls)
        Command()._guard_recent_backup()  # must not raise


@pytest.mark.django_db
def test_database_identity_is_host_name_and_system_identifier():
    """The real query against the real (test) connection — the format
    scripts/backup.sh writes: <host>/<name>#<digits>."""
    from apps.tenants.management.commands.migrate import database_identity

    identity = database_identity()
    host_name, _, system_identifier = identity.partition("#")
    assert host_name == f"{connection.settings_dict['HOST']}/{connection.settings_dict['NAME']}"
    assert system_identifier.isdigit()
