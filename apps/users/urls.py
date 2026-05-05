from __future__ import annotations

from django.urls import URLPattern, URLResolver, path

from apps.users.views import (
    ComplexSearchView,
    LoginView,
    LogoutView,
    MeView,
    OTPVerifyView,
    RegisterView,
    TokenRefreshView,
)

urlpatterns: list[URLPattern | URLResolver] = [
    # Discovery
    path("complexes/search/", ComplexSearchView.as_view(), name="complex-search"),
    # Registration flow
    path("register/", RegisterView.as_view(), name="auth-register"),
    # Login flow
    path("login/", LoginView.as_view(), name="auth-login"),
    # Shared OTP verification (context: registration | login)
    path("verify-otp/", OTPVerifyView.as_view(), name="auth-verify-otp"),
    # Token lifecycle
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    # Profile
    path("me/", MeView.as_view(), name="auth-me"),
]
