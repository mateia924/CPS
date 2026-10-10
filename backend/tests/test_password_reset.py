"""Sprint 7.2.9 (§8.9): self-service "forgot password" for a user who
cannot log in at all — distinct from ChangePasswordView (already
authenticated, tests/test_must_change_password.py) and
apps.access.views' admin reset_password (forbidden for this flow by
owner decision, 2026-10-08).

R-7.2.9.7's five guards each get a negative test proving the rejection
actually happens (not just that the happy path works) — every one of
the five was additionally proven by Rule 11 during implementation
(temporarily removing that exact guard's code, confirming that exact
test fails named, restoring it, confirming green again); see the
closure note in docs/prompts/sprint-7.md §8.9 for the literal
before/after output of each.
"""

import uuid
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetToken, User
from apps.accounts.tasks import send_password_reset_email_task

from .factories import TenantFactory, UserFactory

PASSWORD = "OldPass!2026"
NEW_PASSWORD = "BrandNewPass!2026"
_FROZEN_TIMESTAMP = 1_700_000_000.0


def _unique(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _clear_ratelimit_keys():
    # Same technique as tests/test_rate_limiting.py — deletes only
    # django_ratelimit's own "rl:"-prefixed keys, never a raw FLUSHDB
    # (which would also wipe Celery's broker db in the same Redis).
    client = cache._cache.get_client()
    keys = client.keys("*rl:*")
    if keys:
        client.delete(*keys)


@pytest.fixture(autouse=True)
def _isolated_ratelimit_keys():
    _clear_ratelimit_keys()
    yield
    _clear_ratelimit_keys()


@contextmanager
def _frozen():
    with patch("django_ratelimit.core.time.time", return_value=_FROZEN_TIMESTAMP):
        yield


def _setup_locked_out_user(email=None):
    subdomain = _unique("pwreset")
    tenant = TenantFactory(subdomain=subdomain)
    user = UserFactory(tenant=tenant, email=email or f"locked@{subdomain}.test", password=PASSWORD)
    return tenant, user


def _issue_token(user, tenant=None):
    """Runs the real task function directly (same convention as
    tests/test_approval_digest.py calling send_pending_approvals_digest()
    without .delay()) — issues a real token and sends the real email
    via Django's locmem test backend, synchronously, no Celery worker
    needed."""
    send_password_reset_email_task(tenant.subdomain if tenant else user.tenant.subdomain, user.email)
    return PasswordResetToken.objects.filter(user=user).latest("created_at")


def _raw_token_from_outbox():
    """The raw token only ever exists in the email body (§0.3 — never
    logged) — tests read it from Django's test mailbox, exactly as a
    real user would read it from their inbox, same convention
    docs/prompts/sprint-7.md §8.9 item 1 specifies for the staging
    walkthrough."""
    assert len(mail.outbox) >= 1
    body = mail.outbox[-1].body
    return body.split("token=")[1].split("\n")[0].strip()


# ---------------------------------------------------------------------------
# R-7.2.9.3: the request endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_returns_identical_response_whether_account_exists_or_not():
    """R-7.2.9.7-د (no enumeration): same status, same body, for a
    real account and a nonexistent one."""
    tenant, user = _setup_locked_out_user()
    client = APIClient()

    real = client.post(
        "/api/auth/password-reset/request/", {"subdomain": tenant.subdomain, "email": user.email}, format="json"
    )
    fake = client.post(
        "/api/auth/password-reset/request/",
        {"subdomain": tenant.subdomain, "email": f"nobody-{uuid.uuid4().hex[:8]}@example.test"},
        format="json",
    )

    assert real.status_code == fake.status_code == 200
    assert real.data == fake.data


@pytest.mark.django_db
def test_request_enqueues_the_task_without_doing_any_lookup_itself():
    """The view must do zero account-existence-dependent work on the
    response path — proven by mocking .delay() and asserting the view
    never touched PasswordResetToken/mail.outbox itself."""
    tenant, user = _setup_locked_out_user()
    client = APIClient()

    with patch("apps.accounts.views.send_password_reset_email_task.delay") as mocked_delay:
        response = client.post(
            "/api/auth/password-reset/request/",
            {"subdomain": tenant.subdomain, "email": user.email},
            format="json",
        )

    assert response.status_code == 200
    mocked_delay.assert_called_once_with(tenant.subdomain, user.email)
    assert PasswordResetToken.objects.filter(user=user).count() == 0
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_request_runs_zero_account_dependent_database_queries_on_the_response_path(django_assert_num_queries):
    """R-7.2.9.3, encoded as a hard assertion rather than a sentence in
    a docstring: any query the VIEW OR SERIALIZER ever adds to this
    path in the future trips this immediately and by name — no
    flakiness, no timing measurement, the exact failure mode a timing
    side-channel on this endpoint would otherwise need a
    statistics-based test to catch at all.

    The baseline is 3, not 0 — verified with -v before picking this
    number: `SAVEPOINT` / `SET LOCAL cps.tenant_id = DEFAULT` /
    `RELEASE SAVEPOINT`, all three from apps.tenants.middleware.
    RLSTenantMiddleware, which unconditionally wraps EVERY `/api/...`
    request (authenticated or not — `clear_local_tenant_id` is exactly
    what runs here, since this request carries no JWT) in its own
    transaction.atomic(). That's universal per-request overhead this
    view has no control over and that every other `/api/` endpoint
    pays too, not account-existence-dependent work — asserting 0 would
    make this test permanently red, catching nothing real on top of a
    pre-existing fact."""
    tenant, user = _setup_locked_out_user()
    client = APIClient()

    with patch("apps.accounts.views.send_password_reset_email_task.delay"):
        with django_assert_num_queries(3):
            response = client.post(
                "/api/auth/password-reset/request/",
                {"subdomain": tenant.subdomain, "email": user.email},
                format="json",
            )

    assert response.status_code == 200


@pytest.mark.django_db
def test_request_with_malformed_body_is_a_plain_400_not_a_leak():
    client = APIClient()
    response = client.post("/api/auth/password-reset/request/", {"subdomain": "x"}, format="json")
    assert response.status_code == 400
    assert "email" in response.data


# ---------------------------------------------------------------------------
# apps.accounts.tasks.send_password_reset_email_task itself
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_creates_a_hashed_token_and_sends_an_email_with_the_tenant_subdomain_link():
    tenant, user = _setup_locked_out_user()

    send_password_reset_email_task(tenant.subdomain, user.email)

    token = PasswordResetToken.objects.get(user=user)
    assert token.tenant_id == tenant.id
    assert token.used_at is None
    assert token.expires_at > timezone.now()
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == [user.email]
    # Scheme mirrors whatever FRONTEND_BASE_URL actually is (http in
    # dev, https on live) — the test asserts the per-tenant subdomain
    # insertion (R-7.2.9.5), not a hardcoded scheme.
    assert f"://{tenant.subdomain}." in sent.body
    assert "reset-password?token=" in sent.body

    # R-7.2.9.2: hashed, not plaintext — the raw value sent in the
    # email never appears in the stored row at all.
    raw_token = sent.body.split("token=")[1].split("\n")[0].strip()
    assert len(token.token_hash) == 64  # sha256 hex digest length
    assert token.token_hash != raw_token
    assert token.token_hash == PasswordResetToken.hash_token(raw_token)


@pytest.mark.django_db
def test_task_is_a_silent_noop_for_an_unknown_tenant_or_email():
    send_password_reset_email_task("no-such-tenant-at-all", "nobody@example.test")
    assert PasswordResetToken.objects.count() == 0
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_issuing_a_new_token_invalidates_the_previous_one_for_the_same_user():
    tenant, user = _setup_locked_out_user()
    send_password_reset_email_task(tenant.subdomain, user.email)
    first = PasswordResetToken.objects.get(user=user)

    send_password_reset_email_task(tenant.subdomain, user.email)

    assert not PasswordResetToken.objects.filter(pk=first.pk).exists()
    assert PasswordResetToken.objects.filter(user=user).count() == 1


# ---------------------------------------------------------------------------
# R-7.2.9.4/.7: the confirm endpoint and its five guards
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_confirm_with_a_valid_token_sets_the_new_password_clears_must_change_password_and_ends_old_sessions():
    tenant, user = _setup_locked_out_user()
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])

    old_client = APIClient()
    old_login = old_client.post(
        "/api/auth/login/", {"subdomain": tenant.subdomain, "email": user.email, "password": PASSWORD},
        format="json",
    )
    assert old_login.status_code == 200, old_login.data
    old_refresh = old_login.data["refresh"]

    _issue_token(user, tenant)
    raw_token = _raw_token_from_outbox()

    client = APIClient()
    confirm = client.post(
        "/api/auth/password-reset/confirm/",
        {"subdomain": tenant.subdomain, "token": raw_token, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert confirm.status_code == 204, confirm.data

    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.check_password(NEW_PASSWORD)
    assert not user.check_password(PASSWORD)

    # R-7.2.9.4: sessions/refresh tokens active before the reset are
    # ended by it, same enforcement ChangePasswordView already uses.
    refresh_attempt = APIClient().post("/api/auth/refresh/", {"refresh": old_refresh}, format="json")
    assert refresh_attempt.status_code == 401, refresh_attempt.data

    fresh_login = APIClient().post(
        "/api/auth/login/", {"subdomain": tenant.subdomain, "email": user.email, "password": NEW_PASSWORD},
        format="json",
    )
    assert fresh_login.status_code == 200, fresh_login.data


@pytest.mark.django_db
def test_confirm_rejects_an_expired_token():
    """R-7.2.9.7-أ."""
    tenant, user = _setup_locked_out_user()
    token = _issue_token(user, tenant)
    raw_token = _raw_token_from_outbox()
    token.expires_at = timezone.now() - timedelta(minutes=1)
    token.save(update_fields=["expires_at"])

    client = APIClient()
    response = client.post(
        "/api/auth/password-reset/confirm/",
        {"subdomain": tenant.subdomain, "token": raw_token, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert "token" in response.data
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


@pytest.mark.django_db
def test_confirm_rejects_an_already_used_token():
    """R-7.2.9.7-ب."""
    tenant, user = _setup_locked_out_user()
    _issue_token(user, tenant)
    raw_token = _raw_token_from_outbox()
    client = APIClient()
    payload = {"subdomain": tenant.subdomain, "token": raw_token, "new_password": NEW_PASSWORD}

    first = client.post("/api/auth/password-reset/confirm/", payload, format="json")
    assert first.status_code == 204, first.data

    second = client.post(
        "/api/auth/password-reset/confirm/",
        {**payload, "new_password": "SomethingElse!2026"},
        format="json",
    )
    assert second.status_code == 400
    assert "token" in second.data


@pytest.mark.django_db
def test_confirm_rejects_a_token_issued_for_a_different_tenant():
    """R-7.2.9.7-ج: the exact multi-tenant leak this block exists to
    close — a token minted for tenant A's user must never work when
    the confirm request is scoped to tenant B's subdomain."""
    tenant_a, user_a = _setup_locked_out_user()
    tenant_b, _user_b = _setup_locked_out_user()
    _issue_token(user_a, tenant_a)
    raw_token = _raw_token_from_outbox()

    client = APIClient()
    response = client.post(
        "/api/auth/password-reset/confirm/",
        {"subdomain": tenant_b.subdomain, "token": raw_token, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert "token" in response.data
    user_a.refresh_from_db()
    assert user_a.check_password(PASSWORD)


@pytest.mark.django_db
def test_confirm_rejects_a_manually_entered_subdomain_that_does_not_match_the_tokens_own_tenant():
    """R-7.2.9.7-ج, specifically through the manual company-name field
    (frontend/src/app/reset-password/page.tsx's fallback for an
    IP-only host like staging, where subdomainFromHostname returns
    null and there is no auto-detected subdomain at all to be
    confused with). The backend cannot tell a manually typed value
    from an auto-detected one — both arrive as the same `subdomain`
    POST field — so this is the one test proving the guard holds on
    that exact channel: a real token issued for tenant A, submitted
    with a DIFFERENT tenant B typed into the field by hand, must be
    rejected exactly as it would be via a mismatched host."""
    tenant_a, user_a = _setup_locked_out_user()
    tenant_b, _user_b = _setup_locked_out_user()
    _issue_token(user_a, tenant_a)
    raw_token = _raw_token_from_outbox()

    client = APIClient()
    response = client.post(
        "/api/auth/password-reset/confirm/",
        # tenant_b.subdomain stands in for whatever a user typed into
        # the manual field — the token itself is the only thing that
        # actually names tenant_a.
        {"subdomain": tenant_b.subdomain, "token": raw_token, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert "token" in response.data
    user_a.refresh_from_db()
    assert user_a.check_password(PASSWORD)


@pytest.mark.django_db
def test_confirm_rejects_a_token_that_never_existed():
    tenant, _user = _setup_locked_out_user()
    client = APIClient()
    response = client.post(
        "/api/auth/password-reset/confirm/",
        {"subdomain": tenant.subdomain, "token": "not-a-real-token-at-all", "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert "token" in response.data


@pytest.mark.django_db
def test_confirm_enforces_the_same_password_strength_rule_as_change_password():
    tenant, user = _setup_locked_out_user()
    _issue_token(user, tenant)
    raw_token = _raw_token_from_outbox()

    client = APIClient()
    response = client.post(
        "/api/auth/password-reset/confirm/",
        {"subdomain": tenant.subdomain, "token": raw_token, "new_password": user.email},
        format="json",
    )
    assert response.status_code == 400
    assert "new_password" in response.data


@pytest.mark.django_db
def test_request_is_rate_limited_after_5_attempts_per_ip_and_email(settings):
    """R-7.2.9.7-هـ (request side)."""
    settings.RATELIMIT_ENABLE = True
    tenant, user = _setup_locked_out_user()
    client = APIClient()
    payload = {"subdomain": tenant.subdomain, "email": user.email}

    with _frozen():
        responses = [
            client.post("/api/auth/password-reset/request/", payload, format="json") for _ in range(6)
        ]

    assert [r.status_code for r in responses[:5]] == [200] * 5
    assert responses[5].status_code == 429


@pytest.mark.django_db
def test_confirm_is_rate_limited_after_5_attempts_per_ip(settings):
    """R-7.2.9.7-هـ (confirm side) — keyed on IP alone (see
    PasswordResetConfirmView's own comment): every attempt below uses
    a DIFFERENT guessed token on purpose, proving the limiter still
    fires even though the "key" the guard usually varies on (the
    token) is never the same twice."""
    settings.RATELIMIT_ENABLE = True
    tenant, _user = _setup_locked_out_user()
    client = APIClient()

    with _frozen():
        responses = [
            client.post(
                "/api/auth/password-reset/confirm/",
                {
                    "subdomain": tenant.subdomain,
                    "token": f"guess-{i}",
                    "new_password": NEW_PASSWORD,
                },
                format="json",
            )
            for i in range(6)
        ]

    assert [r.status_code for r in responses[:5]] == [400] * 5
    assert responses[5].status_code == 429
