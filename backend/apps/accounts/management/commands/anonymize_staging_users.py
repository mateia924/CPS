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

Pre-deploy 1 (2026-10-17): scripts/staging_refresh.sh --full now runs
this RIGHT AFTER the restore, before the first gate — so on live's
restored schema, BEFORE `migrate`, with the new code's models. Every
query here therefore names its columns (values()/bulk_update(fields)/
update()) and never loads a whole row: a model loaded whole SELECTs
every field the NEW code has, and the first deploy that adds a column
to User or Tenant would fail here on a column the restored schema does
not have yet. Only columns this command itself rewrites are named —
all of them present since 6.6.2.

Pre-deploy 3 (2026-10-18), rule 50: the password comes from the
STAGING_UAT_PASSWORD environment variable, never from an option. It was
`--password <value>`, which put it on the command line — readable in
`ps` by every process on the host for as long as the command ran
(scripts/staging_refresh.sh passes the variable's NAME to `compose run
-e`, the value travels in the environment). There is no option at all
now, so a secret on the command line cannot happen by habit either.
"""

import os

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import BackupCode, User, UserSession


class Command(BaseCommand):
    help = (
        "Rewrites every tenant User's password (STAGING_UAT_PASSWORD from the environment)/email "
        "and clears 2FA/sessions for a staging UAT session. Staging only."
    )

    def handle(self, *args, **options):
        if os.environ.get("CPS_ENVIRONMENT") != "staging":
            raise CommandError(
                "CPS_ENVIRONMENT is not 'staging' — refusing to anonymize users. "
                "This command only ever runs inside docker-compose.staging.yml."
            )

        password = os.environ.get("STAGING_UAT_PASSWORD", "")
        if not password:
            raise CommandError(
                "STAGING_UAT_PASSWORD is empty — set it in .env.staging; it is read from the "
                "environment, never from the command line."
            )
        rows = list(User.objects.values("pk", "email", "tenant_id", "tenant__subdomain"))

        users = []
        used_emails_by_tenant = {}
        for row in rows:
            local_part = row["email"].split("@", 1)[0]
            domain = f"{row['tenant__subdomain']}.staging.test"
            used = used_emails_by_tenant.setdefault(row["tenant_id"], set())
            candidate = f"{local_part}@{domain}"
            suffix = 2
            while candidate in used:
                candidate = f"{local_part}-{suffix}@{domain}"
                suffix += 1
            used.add(candidate)
            users.append(
                User(
                    pk=row["pk"],
                    email=candidate,
                    password=make_password(password),
                    must_change_password=False,
                    totp_secret="",
                    totp_confirmed=False,
                )
            )

        User.objects.bulk_update(
            users, ["email", "password", "must_change_password", "totp_secret", "totp_confirmed"]
        )
        BackupCode.objects.all().delete()

        BlacklistedToken.objects.bulk_create(
            [
                BlacklistedToken(token_id=pk)
                for pk in OutstandingToken.objects.values_list("pk", flat=True)
            ],
            ignore_conflicts=True,
        )
        UserSession.objects.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())

        self.stdout.write(
            self.style.SUCCESS(
                f"Anonymized {len(users)} user(s) (email/password), cleared 2FA/must_change_password, "
                "and invalidated every session."
            )
        )
