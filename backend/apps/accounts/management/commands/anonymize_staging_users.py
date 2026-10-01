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

Sprint 6.6.3b: pays down the debt this file's own docstring (and
scripts/staging_refresh.sh's own comment) documented since 6.6.0, now
that 2FA/must_change_password/session-invalidation actually exist
(sprint 6.6.2) — a user restored from a dev backup could otherwise
carry over a real TOTP secret nobody on a UAT session has the
authenticator app for (permanently locking that login out), a pending
forced-password-change screen, or a still-valid dev-session refresh
token. Every restore now also: wipes TOTP/backup codes entirely (2FA
must be re-enrolled fresh on staging, by design — it was never the
point of this command to preserve it), clears must_change_password,
and blacklists every outstanding refresh token for every user.
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import BackupCode, User, UserSession


class Command(BaseCommand):
    help = "Rewrites every tenant User's password/email and clears 2FA/sessions for a staging UAT session. Staging only."

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
            user.must_change_password = False
            user.totp_secret = ""
            user.totp_confirmed = False

        User.objects.bulk_update(
            users, ["email", "password", "must_change_password", "totp_secret", "totp_confirmed"]
        )
        BackupCode.objects.all().delete()

        outstanding = OutstandingToken.objects.all()
        BlacklistedToken.objects.bulk_create(
            [BlacklistedToken(token=token) for token in outstanding], ignore_conflicts=True
        )
        UserSession.objects.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())

        self.stdout.write(
            self.style.SUCCESS(
                f"Anonymized {len(users)} user(s) (email/password), cleared 2FA/must_change_password, "
                "and invalidated every session."
            )
        )
