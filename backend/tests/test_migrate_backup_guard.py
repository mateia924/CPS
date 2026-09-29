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


def _write_log(tmp_path, lines):
    log = tmp_path / "backups.log"
    log.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return log


@pytest.mark.django_db
def test_last_backup_timestamp_reads_the_final_non_comment_line(tmp_path):
    log = _write_log(
        tmp_path,
        [
            "# a header comment",
            "2026-09-29T13:59:35+03:00\tabc123\tfile1.sql.gz\tfirst reason",
            "2026-09-29T20:28:15+03:00\tdef456\tfile2.sql.gz\tsecond reason",
        ],
    )
    with patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", log):
        parsed = Command()._last_backup_timestamp()
    assert parsed == datetime.fromisoformat("2026-09-29T20:28:15+03:00")


@pytest.mark.django_db
def test_last_backup_timestamp_none_for_missing_file(tmp_path):
    with patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "does-not-exist.log"):
        assert Command()._last_backup_timestamp() is None


@pytest.mark.django_db
def test_last_backup_timestamp_none_for_comment_only_file(tmp_path):
    log = _write_log(tmp_path, ["# nothing here but comments", "# another one"])
    with patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", log):
        assert Command()._last_backup_timestamp() is None


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
    log = _write_log(tmp_path, [f"{stale.isoformat()}\tabc123\tfile.sql.gz\told backup"])

    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
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
    log = _write_log(tmp_path, [f"{fresh.isoformat()}\tabc123\tfile.sql.gz\trecent backup"])

    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
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
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"):
        Command()._guard_recent_backup()  # must not raise


def test_guard_skips_a_brand_new_database_with_nothing_applied_yet(tmp_path):
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"), \
         patch("apps.tenants.management.commands.migrate.MigrationExecutor") as mock_executor_cls:
        mock_executor = mock_executor_cls.return_value
        mock_executor.loader.applied_migrations = {}

        Command()._guard_recent_backup()  # must not raise


def test_guard_bypass_env_var_skips_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("CPS_SKIP_BACKUP_GUARD", "1")
    with patch.dict(connection.settings_dict, {"NAME": "cps"}), \
         patch("apps.tenants.management.commands.migrate.BACKUPS_LOG_PATH", tmp_path / "missing.log"):
        Command()._guard_recent_backup()  # must not raise, must not even query the DB
