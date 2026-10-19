import logging

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        # 2026-10-19: which email backend this process will use, once at
        # startup — the class path only, never a host or credential. Live
        # sent password-reset links to the console log for weeks without
        # anyone seeing that it did.
        from django.conf import settings

        logging.getLogger("cps.startup").info("email backend: %s", settings.EMAIL_BACKEND)
