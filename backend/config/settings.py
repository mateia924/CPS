"""
Django settings for the CPS platform.

Environment-driven configuration — see /opt/cps/.env.example for the full
list of variables read here.
"""

import os
from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(str(BASE_DIR / ".env"))

# Sprint 6.6.3c: pytest itself sets this env var for the duration of the
# session (pytest >= 8.0, documented — the officially recommended way
# to detect "running under pytest" instead of a sys.argv/sys.modules
# guess). Used below to give a handful of settings a safe, deterministic
# default ONLY under pytest (CI's own ubuntu runner, and any other
# clean-room checkout, never provisions real secrets or a pre-existing
# `cps_app` Postgres role) — every real environment (dev/staging/live)
# keeps requiring its own actual value exactly as before, since each
# already supplies one via its own .env/.env.staging.
TESTING = "PYTEST_VERSION" in os.environ

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    # Sprint 6 (block 6.0, item 6 — CFO_REVIEW_1 §7 Q18, sprint 5.7 gap):
    # backs BLACKLIST_AFTER_ROTATION below and POST /api/auth/logout/.
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
]

LOCAL_APPS = [
    "apps.platform",
    "apps.tenants",
    "apps.accounts",
    "apps.organization",
    "apps.access",
    "apps.numbering",
    "apps.approvals",
    "apps.accounting",
    "apps.parties",
    "apps.treasury",
    "apps.assets",
    "apps.sales",
    "apps.attachments",
    "apps.vouchers",
    "apps.reports",
    "apps.inventory",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

AUTH_USER_MODEL = "accounts.User"

# SECURITY: TenantEmailBackend only — do not add ModelBackend back here.
# ModelBackend resolves users by a *global* User.objects.get(email=...)
# lookup (BaseUserManager.get_by_natural_key), with no tenant filtering.
# Since Django's authenticate() tries every backend in this list and
# accepts the first success, adding ModelBackend back would let a login
# with the WRONG subdomain succeed anyway as long as the email/password
# match some user in ANY tenant — a full cross-tenant auth bypass. This
# was caught by the tenant-isolation curl test in the project README.
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.TenantEmailBackend",
]

# auth.W004 fires because User.email (USERNAME_FIELD) is deliberately
# unique only *within* a tenant, not globally (docs/SYSTEM_ANALYSIS.md
# 3.14 login contract: subdomain + email + password). Django's check
# can't know that TenantEmailBackend.authenticate() already handles this
# correctly — it always resolves the user by (tenant, email), never by a
# bare global email lookup. This is a structural design decision, not an
# oversight; silencing is the documented, deliberate response per
# SYSTEM_ANALYSIS.md rule 9 (see also backend/tests/test_tenant_isolation.py).
SILENCED_SYSTEM_CHECKS = ["auth.W004"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Sprint 6.6.3 (item 1): sets a thread-local flag AdminBypassRouter
    # reads (apps/tenants/routers.py) — AuthenticationMiddleware's own
    # request.user is a lazily-evaluated SimpleLazyObject, so the
    # actual DB lookup only happens once something later accesses it,
    # well after this flag is set regardless of the exact ordering
    # between the two; placed here so it reads together with
    # RLSTenantMiddleware right below it as "both halves of the same
    # concern" (that one only ever handles /api/*, this one /admin/*).
    "apps.tenants.middleware.AdminDatabaseRoutingMiddleware",
    # Sprint 6.6.3 (item 1): must run before any view, same reasoning
    # as MustChangePasswordMiddleware right below it — see apps/
    # tenants/middleware.py's own docstring.
    "apps.tenants.middleware.RLSTenantMiddleware",
    # Sprint 6.6.2 (item 2): a global gate no per-view permission_classes
    # override can bypass — see apps/accounts/middleware.py's own
    # docstring for why this has to be middleware, not a permission
    # class, given most ViewSets in this project set their own
    # permission_classes list rather than relying on DRF's defaults.
    "apps.accounts.middleware.MustChangePasswordMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASES = {
    # Sprint 6.6.3 (item 1): the request-serving connection — RLS-bound
    # in every environment that overrides DATABASE_URL to the
    # restricted `cps_app` role (docker-compose.local.yml/staging.yml's
    # APP_DATABASE_URL; docker-compose.dev.yml never does, see
    # apps/tenants/migrations/0016_row_level_security.py). Not
    # ATOMIC_REQUESTS — see apps/tenants/middleware.py's own docstring
    # for why that alone would be too late for `SET LOCAL`; the
    # middleware opens its own transaction.atomic() instead, around
    # the entire rest of the chain.
    "default": env.db("DATABASE_URL"),
    # apps.platform's own cross-tenant queries (the whole point of a
    # platform admin) always use this alias explicitly (`.using(
    # "platform")`) regardless of what "default" is bound to — always
    # the un-restricted role that can already see everything (the
    # project's original superuser `cps`), so migrations/admin
    # commands/Celery need no separate config of their own: they only
    # ever touch "default", which for THEM is that same role too (only
    # the live gunicorn process's own DATABASE_URL differs).
    "platform": {
        **env.db("PLATFORM_DATABASE_URL", default=env("DATABASE_URL")),
        # Mirrors "default"'s own test database instead of creating a
        # second physical one — same server, same DB, just connecting
        # as a different (unrestricted) role for tests too.
        "TEST": {"MIRROR": "default"},
    },
}

# Sprint 6.6.3 (item 1): apps.tenants.routers.AdminBypassRouter — routes
# every query to "platform" while apps.tenants.middleware.
# AdminDatabaseRoutingMiddleware's own thread-local flag is set
# (/admin/* requests only). A no-op (returns None, Django's own
# default routing) for every other request.
DATABASE_ROUTERS = ["apps.tenants.routers.AdminBypassRouter"]

# Sprint 6.6.3c: the single source of truth for the restricted `cps_app`
# role's own login credentials — apps.tenants.services.
# configure_database_roles_and_rls (and tests/test_rls.py's own direct
# psycopg connections) read these from here, never os.environ directly,
# so this TESTING-aware default is the only place that needs to exist.
# Genuinely optional outside TESTING (empty string, same as before this
# sprint) — docker-compose.dev.yml deliberately never sets these at all
# (cps-dev stays on the unrestricted role, sprint 6.6.0), and that must
# keep working exactly as today: configure_database_roles_and_rls's own
# guard still refuses to run with an empty user/password, it just now
# never gets called with an empty one *during a pytest run specifically*.
POSTGRES_APP_USER = env("POSTGRES_APP_USER", default="cps_app_test" if TESTING else "")
POSTGRES_APP_PASSWORD = env(
    "POSTGRES_APP_PASSWORD", default="pytest-only-insecure-app-role-password" if TESTING else ""
)

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    # Sprint 6.6.2 (item 2): bumped 8 -> 12 per the sprint's own policy
    # ("12 حرفًا، لا تساوي البريد، ليست من القائمة الشائعة" — the other
    # two clauses are UserAttributeSimilarityValidator and
    # CommonPasswordValidator below, both already in place).
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# i18n / l10n — Arabic default, English secondary, full RTL support in front end
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "ar"
LANGUAGES = [
    ("ar", "العربية"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = env("DJANGO_TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# DRF / JWT
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    # apps.tenants.authentication.TenantAwareJWTAuthentication wraps
    # simplejwt to also enforce Tenant.status (sprint 2) — applies here
    # globally since no customer ViewSet overrides authentication_classes
    # (only permission_classes), unlike apps.platform.* ViewSets, which
    # explicitly set their own (PlatformJWTAuthentication) and are never
    # reachable via this default.
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.tenants.authentication.TenantAwareJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    # Sprint 6 (block 6.0, item 6): was False (CFO_REVIEW_1 §7 Q18 gap
    # — a leaked/rotated refresh token stayed valid for its full 7-day
    # lifetime regardless). A rotated-away token is now blacklisted
    # immediately, and POST /api/auth/logout/ blacklists the current one.
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Platform auth (sprint 2, apps/platform/auth.py) — deliberately its own
# signing key, never DJANGO_SECRET_KEY and never SIMPLE_JWT's key, so a
# customer token and a platform token can never verify against each
# other's key regardless of any application-level bug. Required in
# every real environment (no default); TESTING gets a fixed, clearly-
# named fallback so a clean-room pytest run (CI's own runner, or any
# other checkout with no .env at all) never needs this provisioned.
PLATFORM_JWT_SIGNING_KEY = env(
    "PLATFORM_JWT_SIGNING_KEY",
    default="pytest-only-platform-jwt-signing-key-never-used-outside-tests" if TESTING else env.NOTSET,
)
PLATFORM_JWT_ACCESS_MINUTES = env.int("PLATFORM_JWT_ACCESS_MINUTES", default=30)
PLATFORM_JWT_REFRESH_DAYS = env.int("PLATFORM_JWT_REFRESH_DAYS", default=7)

# Sprint 6 (block 6.0, item 6): days a tenant may stay PAST_DUE before
# apps.tenants.tasks.auto_suspend_past_due_tenants (daily beat)
# transitions it to SUSPENDED automatically.
PAST_DUE_GRACE_DAYS = env.int("PAST_DUE_GRACE_DAYS", default=14)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])

# ---------------------------------------------------------------------------
# Celery / Redis
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = env("REDIS_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://redis:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Sprint 5.1 (3.17 rule 2): weekly SHA-256 re-check of every active
# attachment. `celery -A config worker --beat` (docker-compose.yml) runs
# the scheduler in the same process — fine at this project's scale; a
# separate beat service is a straightforward split later if needed.
CELERY_BEAT_SCHEDULE = {
    "attachment-integrity-check": {
        "task": "apps.attachments.tasks.check_attachment_integrity",
        "schedule": timedelta(days=7),
    },
    # Sprint 6 (block 6.0, item 6).
    "auto-suspend-past-due-tenants": {
        "task": "apps.tenants.tasks.auto_suspend_past_due_tenants",
        "schedule": timedelta(days=1),
    },
    # Sprint 6.1 (decision 2).
    "create-due-fiscal-years": {
        "task": "apps.accounting.tasks.create_due_fiscal_years",
        "schedule": timedelta(days=1),
    },
    # Sprint 6.4 (decision 10): "Celery beat يوميًا 01:00 UTC" — a fixed
    # time of day, unlike the two entries above (CELERY_TIMEZONE=
    # TIME_ZONE, which defaults to UTC, so this really is 01:00 UTC).
    "generate-due-recurring-installments": {
        "task": "apps.accounting.tasks.generate_due_recurring_installments",
        "schedule": crontab(hour=1, minute=0),
    },
    # Sprint 6.8 (decision 17): "beat يوميًا 05:00 UTC".
    "send-pending-approvals-digest": {
        "task": "apps.approvals.tasks.send_pending_approvals_digest",
        "schedule": crontab(hour=5, minute=0),
    },
}

# ---------------------------------------------------------------------------
# Cache / rate limiting (sprint 4.0, ARCH_REVIEW_1.md debt #9)
# ---------------------------------------------------------------------------

# Must be a shared cache (not the per-process LocMemCache default) since
# gunicorn runs multiple workers — apps.common.ratelimit's counters need
# to be visible across all of them to actually limit anything.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://redis:6379/0"),
    }
}

# tests/conftest.py flips this off by default (an autouse fixture) so the
# rest of the suite's many /api/auth/login/ and /api/platform/auth/login/
# calls don't trip it; the rate-limiting tests themselves turn it back on
# via the `settings` fixture for just that test.
RATELIMIT_ENABLE = env.bool("DJANGO_RATELIMIT_ENABLE", default=True)

# ---------------------------------------------------------------------------
# Attachments: MinIO (S3-compatible) + ClamAV — sprint 5.1 (3.17)
# ---------------------------------------------------------------------------

MINIO_ACCESS_KEY = env("MINIO_ACCESS_KEY", default="")
MINIO_SECRET_KEY = env("MINIO_SECRET_KEY", default="")
MINIO_BUCKET = env("MINIO_BUCKET", default="cps-attachments")
MINIO_ENDPOINT_URL = env("MINIO_ENDPOINT_URL", default="http://minio:9000")

# Sprint 7.0 (CI #56/#61): CI's own GitHub-hosted runner cannot
# reliably pull quay.io/minio/minio at all — "Start MinIO" failed
# Docker-CLI-level (exit 125, a pull/registry failure, never our own
# health-check timeout) on every single run since the native rewrite
# (770c9bd through today, 13 consecutive runs) — not a code bug this
# project can fix, same class of fragile third-party-registry
# dependency CI #48 already removed ClamAV for, and with zero security
# value in CI either way (no test here asserts MinIO-specific
# behavior; see apps.attachments.storage's own ATTACHMENT_STORAGE_BACKEND
# switch and test_attachments.py's `minio`-marked integration test).
ATTACHMENT_STORAGE_BACKEND = env("ATTACHMENT_STORAGE_BACKEND", default="s3")

# Signs this app's own short-lived download links (apps.attachments.
# services.sign_link/verify_link) — deliberately a separate secret from
# DJANGO_SECRET_KEY, same reasoning as PLATFORM_JWT_SIGNING_KEY: a leak
# of one must never let an attacker forge the other.
ATTACHMENT_LINK_SIGNING_KEY = env("ATTACHMENT_LINK_SIGNING_KEY", default=SECRET_KEY)
ATTACHMENT_LINK_TTL_SECONDS = 5 * 60

CLAMD_HOST = env("CLAMD_HOST", default="clamav")
CLAMD_PORT = env.int("CLAMD_PORT", default=3310)
ATTACHMENT_SCAN_ENABLED = env.bool("ATTACHMENT_SCAN_ENABLED", default=True)
ATTACHMENT_DEFAULT_MAX_FILE_MB = env.int("ATTACHMENT_DEFAULT_MAX_FILE_MB", default=20)

# docker-compose.prod.yml is the only place CPS_ENVIRONMENT=production is
# ever set (dev's overlay never sets it) — see the comment there. Prompt
# decision 8: "الإنتاج يرفض الإقلاع" with scanning disabled.
if env("CPS_ENVIRONMENT", default="") == "production" and not ATTACHMENT_SCAN_ENABLED:
    raise ImproperlyConfigured(
        "ATTACHMENT_SCAN_ENABLED=false is not allowed in production — "
        "every uploaded file must be virus-scanned before it's served."
    )

# ---------------------------------------------------------------------------
# Email (sprint 6.8, decision 17): the daily pending-approvals digest —
# console backend (prints to the backend/celery_worker container log,
# never a real send) unless EMAIL_HOST is set, same "no env var means
# dev" convention as ATTACHMENT_SCAN_ENABLED above. docker-compose.prod
# .yml is the only place EMAIL_HOST etc. are ever set.
# ---------------------------------------------------------------------------

EMAIL_HOST = env("EMAIL_HOST", default="")
# Sprint 6.6.0 (owner decision, staging_refresh.sh's own email-
# anonymization pattern): staging emails are real people's addresses
# with only the domain swapped, not synthetic .test ones — a future
# .env.staging that ever picks up a real EMAIL_HOST (copy-paste from
# .env.example, say) must never be able to make staging actually mail
# one of them. Hard override, checked before EMAIL_HOST at all.
if env("CPS_ENVIRONMENT", default="") == "staging":
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
elif EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@cps-erp.com")
# The link inside the digest email — points at the frontend, not this
# API. Dev default matches this host's own frontend port (README
# "Reserved ports"); the prod host sets it to the real domain.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:3000")
