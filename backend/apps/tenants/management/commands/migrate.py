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
- CPS_SKIP_BACKUP_GUARD=1 is a documented, loud, manual escape hatch
  for a genuine emergency — never silent.

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
# inside the container. CPS_BACKUPS_LOG_PATH can override this for a
# non-Docker/manual run (e.g. a bare-metal deploy checkout).
BACKUPS_LOG_PATH = Path(os.environ.get("CPS_BACKUPS_LOG_PATH", "/docs/ops/backups.log"))


class Command(MigrateCommand):
    def handle(self, *args, **options):
        self._guard_recent_backup()
        return super().handle(*args, **options)

    def _guard_recent_backup(self):
        if connection.settings_dict["NAME"].startswith("test_"):
            return
        if os.environ.get("CPS_SKIP_BACKUP_GUARD") == "1":
            self.stderr.write(
                self.style.WARNING(
                    "migrate: تجاوز فحص النسخة الاحتياطية عبر CPS_SKIP_BACKUP_GUARD=1 — تأكد أن هذا مقصود."
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

        last_backup_at = self._last_backup_timestamp()
        if last_backup_at is None:
            reason = (
                "لا يوجد أي سطر في docs/ops/backups.log إطلاقًا"
                if BACKUPS_LOG_PATH.exists()
                else f"الملف {BACKUPS_LOG_PATH} غير موجود من داخل الحاوية"
            )
            raise CommandError(self._refusal_message(reason))

        age = datetime.now(dt_timezone.utc) - last_backup_at
        if age > timedelta(minutes=BACKUP_FRESHNESS_MINUTES):
            reason = (
                f"آخر نسخة احتياطية مسجَّلة كانت قبل {int(age.total_seconds() // 60)} دقيقة "
                f"(الحد المسموح {BACKUP_FRESHNESS_MINUTES} دقيقة)"
            )
            raise CommandError(self._refusal_message(reason))

    def _refusal_message(self, reason):
        return (
            "migrate رُفض: توجد migration(s) معلَّقة تمس قاعدة حقيقية (غير اختبارية) "
            f"بلا نسخة احتياطية حديثة — {reason}.\n"
            "شغِّل scripts/backup.sh أولًا (أو make migrate، الذي يفعل هذا تلقائيًا)، ثم أعد المحاولة.\n"
            "(للحالات الاستثنائية فقط: CPS_SKIP_BACKUP_GUARD=1 يتجاوز هذا الفحص — استخدمه بوعي، لا كعادة.)"
        )

    def _last_backup_timestamp(self):
        if not BACKUPS_LOG_PATH.exists():
            return None
        last_line = None
        with BACKUPS_LOG_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                last_line = line
        if last_line is None:
            return None
        timestamp_field = last_line.split("\t", 1)[0]
        try:
            parsed = datetime.fromisoformat(timestamp_field)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_timezone.utc)
        return parsed
