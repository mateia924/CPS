from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ChangePasswordView,
    LoginView,
    LogoutAllView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    SessionListView,
    TwoFactorConfirmView,
    TwoFactorDisableView,
    TwoFactorSetupView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("logout-all/", LogoutAllView.as_view(), name="auth-logout-all"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
    path("password-reset/request/", PasswordResetRequestView.as_view(), name="auth-password-reset-request"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    path("2fa/setup/", TwoFactorSetupView.as_view(), name="auth-2fa-setup"),
    path("2fa/confirm/", TwoFactorConfirmView.as_view(), name="auth-2fa-confirm"),
    path("2fa/disable/", TwoFactorDisableView.as_view(), name="auth-2fa-disable"),
    path("sessions/", SessionListView.as_view(), name="auth-sessions"),
]
