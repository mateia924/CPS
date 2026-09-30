"""Sprint 6.6.0 (owner decision on the exact anonymization pattern):
scripts/staging_refresh.sh's own last step, after restoring a fresh
copy of the dev database onto staging —

- every user's PASSWORD is rewritten to one known, documented value,
  so a human UAT session can log in as anyone without ever having, or
  needing, that person's real password.
- every user's EMAIL is rewritten to keep its local part but replace
  the domain with "<tenant subdomain>.staging.test" — real addresses
  (Fatma's own Owner login is a real Gmail address, not a synthetic
  .test one) never actually receive anything once they're on staging,
  and the login path itself needs no change at all: it already just
  matches whatever email is stored, and this command is what changed
  that. A local-part collision within the same tenant after rewriting
  (rare, but the (tenant, email) uniqueness constraint would reject it
  outright) gets a numeric suffix instead of failing the whole run.

Hard-refuses outside CPS_ENVIRONMENT=staging (docker-compose.staging.yml
is the only place that's ever set) — this command is destructive by
design, and the one thing it must never do is run against a real
tenant's real email/password on the local/live stack or a future
production host.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Rewrites every tenant User's password and email for a staging UAT session. Staging only."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="The known UAT password to set for every user.")

    def handle(self, *args, **options):
        if os.environ.get("CPS_ENVIRONMENT") != "staging":
            raise CommandError(
                "CPS_ENVIRONMENT is not 'staging' — refusing to anonymize users. "
                "This command only ever runs inside docker-compose.staging.yml."
            )

        password = options["password"]
        users = list(User.objects.select_related("tenant").all())

        used_emails_by_tenant = {}
        for user in users:
            local_part = user.email.split("@", 1)[0]
            domain = f"{user.tenant.subdomain}.staging.test"
            used = used_emails_by_tenant.setdefault(user.tenant_id, set())
            candidate = f"{local_part}@{domain}"
            suffix = 2
            while candidate in used:
                candidate = f"{local_part}-{suffix}@{domain}"
                suffix += 1
            used.add(candidate)
            user.email = candidate
            user.set_password(password)

        User.objects.bulk_update(users, ["email", "password"])

        self.stdout.write(
            self.style.SUCCESS(f"Anonymized {len(users)} user(s) (email domain + password) for staging.")
        )
