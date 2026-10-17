"""Sprint 6.5.16 (incident: sprint 6.5.15's six data migrations ran
against the live dev database with no prior backup — scripts/backup.sh
was only run once, after the fact, at the end of the block, instead of
before each migration as the standing §11 rule requires — see docs/
sprints/6.5-summary.md §6.5.16 for the incident record).

Overrides Django's own `migrate` command (an app's own command with the
same name always wins over django.core's — documented Django behavior)
so this is enforced no matter how migrate is invoked: `make migrate`,
a bare `python manage.py migrate`, or even the backend container's own
startup command (infra/docker-compose.yml's `migrate --noinput`, which
runs on every restart). Refuses to apply any PENDING migration against
a non-test database unless docs/ops/backups.log has an entry newer
than BACKUP_FRESHNESS_MINUTES — the exact gap that let 6.5.15 happen
silently.

Deliberately narrow:
- A migrate call with nothing left to apply (the ordinary case on most
  container restarts) is never blocked — only an actually-pending
  migration triggers the check, so this can't deadlock a routine
  restart against an already-up-to-date database.
- A brand-new database with zero migrations ever applied (a fresh
  `make dev-up` on a fresh checkout) has no real data to protect yet —
  skipped.
- A test database (pytest-django always names it "test_<NAME>") is
  never subject to this at all — it's thrown away after every run.
- CPS_SKIP_BACKUP_GUARD=1 skips it — under CPS_ENVIRONMENT=dev only
  (Pre-deploy 1, below); anywhere else it is refused, never silent.

Sprint 7.0 (CI #67 investigation): a prior version of this also
exempted `os.environ.get("CI") == "true" or GITHUB_ACTIONS == "true"`
unconditionally. Verified before removing it: the only real
`manage.py migrate` call that ever runs under CI (the e2e job's
docker-compose backend startup command, via `make dev-up
CI_OVERLAY=1`) never receives CI/GITHUB_ACTIONS in its container env
at all (only CPS_ENVIRONMENT=ci, via .env.ci's own env_file) and
always hits a fresh, empty database first (the "nothing real to lose
yet" return above) — no legitimate caller ever needed this branch.
What it actually did: any ambient CI/GITHUB_ACTIONS=true (which every
GitHub Actions runner sets on every job, unconditionally, with no
opt-in) silently defeated this guard for anyone, anywhere, including
the two tests designed to exercise the real refusal path by
impersonating a real database — a self-disabling guard is not a
guard, it is a universally-available off switch.

Pre-deploy 1 (2026-10-17): the guard verifies WHICH database was backed
up, not only how recently something was. Until now "a fresh line ⇒ this
database was dumped" held only because scripts/backup.sh was the sole
writer and always dumped live — nothing enforced either half. Every
backups.log line now carries `db=<host>/<name>#<system_identifier>`
(written by backup.sh from the very database it dumped), and the guard
accepts only the newest line whose identity equals its own connection's.
Host and name alone are not enough: live and dev are both `postgres/cps`
(two compose projects, one service name, one POSTGRES_DB) — the cluster's
system_identifier (pg_control_system(), fixed at initdb) is what tells
them apart. A line with no db= field (the format before 2026-10-17)
matches nothing: fail closed.

The two escape hatches, CPS_SKIP_BACKUP_GUARD and CPS_BACKUPS_LOG_PATH,
are refused outright — not warned about — unless CPS_ENVIRONMENT=dev.
The guard was born of 6.5.15 (migrations with no backup) and shipped
with the means to repeat it in production. Dev no longer needs them
anyway: `scripts/backup.sh --target dev` is the legitimate path.
"""

import os
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path

from django.core.management.base import CommandError
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BACKUP_FRESHNESS_MINUTES = 15
# docs/ is a sibling of backend/ in the repo, not mounted into the
# backend/celery_worker containers by default (only ../backend:/app
# is) — infra/docker-compose.dev.yml mounts ../docs:/docs:ro
# specifically so this command can read the real, committed log from
# inside the container. CPS_BACKUPS_LOG_PATH may point elsewhere, but
# only under CPS_ENVIRONMENT=dev (see the module docstring).
BACKUPS_LOG_PATH = Path("/docs/ops/backups.log")
DB_FIELD_PREFIX = "db="


def database_identity(conn=connection):
    """`<host>/<name>#<system_identifier>` — the same string
    scripts/backup.sh writes for the database it dumped."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT system_identifier FROM pg_control_system()")
        system_identifier = cursor.fetchone()[0]
    return f"{conn.settings_dict['HOST']}/{conn.settings_dict['NAME']}#{system_identifier}"


class Command(MigrateCommand):
    def handle(self, *args, **options):
        self._guard_recent_backup()
        return super().handle(*args, **options)

    def _guard_recent_backup(self):
        if connection.settings_dict["NAME"].startswith("test_"):
            return
        environment = os.environ.get("CPS_ENVIRONMENT", "")
        log_path = self._backups_log_path(environment)
        if os.environ.get("CPS_SKIP_BACKUP_GUARD") == "1":
            if environment != "dev":
                raise CommandError(self._hatch_refusal("CPS_SKIP_BACKUP_GUARD=1", environment))
            self.stderr.write(
                self.style.WARNING(
                    "migrate: تجاوز فحص النسخة الاحتياطية عبر CPS_SKIP_BACKUP_GUARD=1 (CPS_ENVIRONMENT=dev) — "
                    "الطريق المعتاد: scripts/backup.sh --target dev."
                )
            )
            return

        executor = MigrationExecutor(connection)
        if not executor.loader.applied_migrations:
            # A genuinely fresh database (first-ever `make dev-up` on a
            # new checkout) — nothing real to lose yet.
            return
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if not plan:
            # Nothing pending — the ordinary case on most container
            # restarts. Never block an up-to-date database.
            return

        try:
            identity = database_identity()
        except Exception as exc:  # fail closed: an unknown identity matches nothing
            raise CommandError(self._refusal_message(f"تعذّر تعريف القاعدة الحالية ({exc})")) from exc

        if not log_path.exists():
            raise CommandError(self._refusal_message(f"الملف {log_path} غير موجود من داخل الحاوية"))
        last_backup_at = self._last_backup_timestamp(identity, log_path)
        if last_backup_at is None:
            raise CommandError(
                self._refusal_message(f"لا يوجد في {log_path} أي سطر نسخة لهذه القاعدة ({identity})")
            )

        age = datetime.now(dt_timezone.utc) - last_backup_at
        if age > timedelta(minutes=BACKUP_FRESHNESS_MINUTES):
            reason = (
                f"آخر نسخة احتياطية مسجَّلة لهذه القاعدة ({identity}) كانت قبل "
                f"{int(age.total_seconds() // 60)} دقيقة (الحد المسموح {BACKUP_FRESHNESS_MINUTES} دقيقة)"
            )
            raise CommandError(self._refusal_message(reason))

    def _backups_log_path(self, environment):
        override = os.environ.get("CPS_BACKUPS_LOG_PATH")
        if not override or Path(override) == BACKUPS_LOG_PATH:
            return BACKUPS_LOG_PATH
        if environment != "dev":
            raise CommandError(self._hatch_refusal(f"CPS_BACKUPS_LOG_PATH={override}", environment))
        return Path(override)

    def _hatch_refusal(self, setting, environment):
        shown = environment or "غير مضبوط"
        return (
            f"migrate رُفض: {setting} مسموح فقط حين CPS_ENVIRONMENT=dev، "
            f"والبيئة هنا CPS_ENVIRONMENT={shown}. "
            "خارج dev لا تجاوز لفحص النسخة الاحتياطية: شغِّل scripts/backup.sh --target <البيئة> ثم أعد المحاولة."
        )

    def _refusal_message(self, reason):
        return (
            "migrate رُفض: توجد migration(s) معلَّقة تمس قاعدة حقيقية (غير اختبارية) "
            f"بلا نسخة احتياطية حديثة لها هي — {reason}.\n"
            "شغِّل scripts/backup.sh --target <dev|staging|live> للقاعدة التي تهاجرها أولًا "
            "(أو make migrate لـdev، الذي يفعل هذا تلقائيًا)، ثم أعد المحاولة."
        )

    def _last_backup_timestamp(self, identity, log_path=None):
        """The newest line whose db= field equals `identity`. A line
        without a db= field (the pre-2026-10-17 format) never matches."""
        log_path = log_path or BACKUPS_LOG_PATH
        if not log_path.exists():
            return None
        newest = None
        with log_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t")
                db_fields = [x[len(DB_FIELD_PREFIX):] for x in fields[1:] if x.startswith(DB_FIELD_PREFIX)]
                if db_fields != [identity]:
                    continue
                try:
                    parsed = datetime.fromisoformat(fields[0])
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_timezone.utc)
                if newest is None or parsed > newest:
                    newest = parsed
        return newest
