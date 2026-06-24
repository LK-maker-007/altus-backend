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
    path("complexes/search/", ComplexSearchView.as_view(), name="complex-search"),
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("verify-otp/", OTPVerifyView.as_view(), name="auth-verify-otp"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
]
