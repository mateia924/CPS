"""Sprint 6.6.0: scripts/staging_refresh.sh's own last step, after
restoring a fresh copy of the dev database onto staging — every
tenant user's password gets rewritten to one known, documented value
(the owner's real email stays untouched, only the password changes) so
a human UAT session can log in as anyone without ever having, or
needing, that person's real production password.

Hard-refuses outside CPS_ENVIRONMENT=staging (docker-compose.staging.yml
is the only place that's ever set) — this command is destructive by
design, and the one thing it must never do is run against a real
tenant's real password on the local/live stack or a future production
host.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Rewrites every tenant User's password to a single known value. Staging only."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="The known UAT password to set for every user.")

    def handle(self, *args, **options):
        if os.environ.get("CPS_ENVIRONMENT") != "staging":
            raise CommandError(
                "CPS_ENVIRONMENT is not 'staging' — refusing to reset passwords. "
                "This command only ever runs inside docker-compose.staging.yml."
            )

        password = options["password"]
        users = list(User.objects.all())
        for user in users:
            user.set_password(password)
        User.objects.bulk_update(users, ["password"])

        self.stdout.write(self.style.SUCCESS(f"Reset {len(users)} user password(s) to the staging UAT value."))
