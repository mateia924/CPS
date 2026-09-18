import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.platform.models import PlatformUser
from apps.platform.services import (
    generate_backup_codes,
    generate_totp_secret,
    totp_provisioning_uri,
    verify_totp,
)


class Command(BaseCommand):
    """docs/SYSTEM_ANALYSIS.md 3.14: "أمر إداري لإنشاء أول SUPER_ADMIN من
    الترمينال" — the ONLY way to create a PlatformUser. 2FA enrollment is
    mandatory and happens right here, interactively, before the account
    is usable at all: there is no way to end up with a PlatformUser that
    has totp_confirmed=False, so the web login flow never needs a
    separate "finish 2FA setup" step.
    """

    help = "Create a platform admin user (Super Admin/Support/Billing), with mandatory 2FA setup."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--full-name", required=True)
        parser.add_argument(
            "--role", choices=[c[0] for c in PlatformUser.Role.choices], default=PlatformUser.Role.SUPER_ADMIN
        )
        parser.add_argument(
            "--noinput", action="store_true", help="Never prompt (for scripted/CI use only)."
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        if PlatformUser.objects.filter(email__iexact=email).exists():
            raise CommandError(f"A platform user with email {email} already exists.")

        if options["noinput"]:
            raise CommandError(
                "--noinput is not supported: 2FA setup is mandatory and requires "
                "an interactive terminal to scan the QR/enter a code."
            )

        password = getpass.getpass("Password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            raise CommandError("Passwords did not match.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages))

        user = PlatformUser.objects.create_user(
            email=email,
            password=password,
            full_name=options["full_name"],
            role=options["role"],
        )

        secret = generate_totp_secret()
        user.totp_secret = secret
        user.save(update_fields=["totp_secret"])

        uri = totp_provisioning_uri(user, secret)
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("2FA setup is mandatory. Scan this in an authenticator app:"))
        self.stdout.write(f"  Secret: {secret}")
        self.stdout.write(f"  URI:    {uri}")
        self.stdout.write("")

        for attempt in range(3):
            code = input("Enter the 6-digit code from your app to confirm: ").strip()
            if verify_totp(secret, code):
                break
            self.stdout.write(self.style.ERROR("Incorrect code, try again."))
        else:
            user.delete()
            raise CommandError("2FA confirmation failed 3 times — user was not created.")

        user.totp_confirmed = True
        user.save(update_fields=["totp_confirmed"])

        codes = generate_backup_codes(user)
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Backup codes (shown once — store them securely):"))
        for code in codes:
            self.stdout.write(f"  {code}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Platform user {email} ({options['role']}) created."))
