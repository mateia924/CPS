"""
Django settings for the CPS platform.

Environment-driven configuration — see /opt/cps/.env.example for the full
list of variables read here.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(str(BASE_DIR / ".env"))

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
    "corsheaders",
    "django_filters",
]

LOCAL_APPS = [
    "apps.platform",
    "apps.tenants",
    "apps.accounts",
    "apps.organization",
    "apps.access",
    "apps.accounting",
    "apps.parties",
    "apps.treasury",
    "apps.assets",
    "apps.sales",
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
    "default": env.db("DATABASE_URL"),
}

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
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
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Platform auth (sprint 2, apps/platform/auth.py) — deliberately its own
# signing key, never DJANGO_SECRET_KEY and never SIMPLE_JWT's key, so a
# customer token and a platform token can never verify against each
# other's key regardless of any application-level bug.
PLATFORM_JWT_SIGNING_KEY = env("PLATFORM_JWT_SIGNING_KEY")
PLATFORM_JWT_ACCESS_MINUTES = env.int("PLATFORM_JWT_ACCESS_MINUTES", default=30)
PLATFORM_JWT_REFRESH_DAYS = env.int("PLATFORM_JWT_REFRESH_DAYS", default=7)

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
