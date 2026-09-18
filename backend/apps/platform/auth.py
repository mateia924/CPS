"""Platform authentication is deliberately NOT rest_framework_simplejwt:
simplejwt's JWTAuthentication.get_user() hardcodes get_user_model()
(accounts.User, our AUTH_USER_MODEL) and its SIGNING_KEY is one global
setting — neither can be made to resolve to PlatformUser with a
different key without monkeypatching. A small, explicit PyJWT-based
implementation with its own signing key gives genuine cryptographic
separation instead: a customer token can never verify against
PLATFORM_JWT_SIGNING_KEY and a platform token can never verify against
SIMPLE_JWT's key, regardless of any application bug.
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import jwt
from django.conf import settings
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.authentication import BaseAuthentication

from .models import PlatformUser

ALGORITHM = "HS256"
ACCESS_TYPE = "platform_access"
REFRESH_TYPE = "platform_refresh"


def _encode(payload):
    return jwt.encode(payload, settings.PLATFORM_JWT_SIGNING_KEY, algorithm=ALGORITHM)


def issue_platform_tokens(user):
    now = datetime.now(dt_timezone.utc)
    access = _encode(
        {
            "sub": str(user.id),
            "type": ACCESS_TYPE,
            "role": user.role,
            "iat": now,
            "exp": now + timedelta(minutes=settings.PLATFORM_JWT_ACCESS_MINUTES),
        }
    )
    refresh = _encode(
        {
            "sub": str(user.id),
            "type": REFRESH_TYPE,
            "iat": now,
            "exp": now + timedelta(days=settings.PLATFORM_JWT_REFRESH_DAYS),
        }
    )
    return access, refresh


def decode_platform_token(token, expected_type):
    payload = jwt.decode(token, settings.PLATFORM_JWT_SIGNING_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload


class PlatformJWTAuthentication(BaseAuthentication):
    """Only ever attached to platform/* views. Never raises on a bad or
    missing token — always returns None (anonymous) instead, so a
    tenant user's customer-signed token looks exactly like "no
    credentials" here, which PlatformViewSet.permission_denied() turns
    into a 404 rather than revealing that a platform endpoint exists.
    """

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        try:
            payload = decode_platform_token(token, expected_type=ACCESS_TYPE)
        except jwt.PyJWTError:
            return None
        try:
            user = PlatformUser.objects.get(id=payload["sub"], is_active=True)
        except (PlatformUser.DoesNotExist, ValueError, KeyError):
            return None
        return (user, token)

    def authenticate_header(self, request):
        return "Bearer"


class PlatformViewSet(viewsets.ModelViewSet):
    """Base for every apps.platform ViewSet: platform-only auth, and any
    permission failure — including "not authenticated at all", which is
    exactly what a tenant user's token looks like here — surfaces as 404
    rather than 401/403, so /api/platform/ doesn't even reveal it exists
    to someone who was never meant to reach it (sprint 2 spec section 6).
    A platform user who *is* authenticated but lacks a specific role
    still gets a normal 403 from further permission checks.
    """

    authentication_classes = [PlatformJWTAuthentication]

    def permission_denied(self, request, message=None, code=None):
        if not request.user or not request.user.is_authenticated:
            raise Http404(_("Not found."))
        return super().permission_denied(request, message=message, code=code)
