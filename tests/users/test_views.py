from __future__ import annotations

from typing import Any

import pytest

from apps.users.models import UserRole
from tests.factories.complex_factory import ComplexFactory


@pytest.mark.django_db
class TestComplexSearchView:

    def test_search_returns_matching_complexes(self, api_client: Any) -> None:
        ComplexFactory(name="Test Sunrise Gardens", slug="test-sunrise", is_active=True)
        ComplexFactory(name="Unrelated Complex", slug="unrelated", is_active=True)

        response = api_client.get("/api/v1/auth/complexes/search/?q=Sunrise")

        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Test Sunrise Gardens"
        result = response.data["results"][0]
        assert "slug" in result
        assert "name" in result
        assert "city" in result
        assert "state" in result

    def test_search_inactive_complex_not_returned(self, api_client: Any) -> None:
        ComplexFactory(name="Test Hidden Complex", slug="hidden", is_active=False)

        response = api_client.get("/api/v1/auth/complexes/search/?q=Hidden")

        assert response.status_code == 200
        assert response.data["results"] == []

    def test_search_no_match_returns_empty(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/auth/complexes/search/?q=NoSuchComplex")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_search_missing_q_returns_400(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/auth/complexes/search/")
        assert response.status_code == 400


@pytest.mark.django_db
class TestLoginView:

    def test_login_known_phone_returns_otp_sent(
        self, api_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = api_client.post(
            "/api/v1/auth/login/",
            data={"phone_number": resident.phone_number},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["status"] == "otp_sent"
        assert response.data["expires_in_seconds"] == 600

    def test_login_missing_phone_returns_400(self, api_client: Any) -> None:
        response = api_client.post("/api/v1/auth/login/", data={}, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
class TestOTPVerifyView:

    def test_valid_otp_returns_tokens_and_user(
        self, api_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = api_client.post(
            "/api/v1/auth/verify-otp/",
            data={
                "phone_number": resident.phone_number,
                "code": "000000",
                "auth_flow": "login",
            },
            format="json",
        )

        assert response.status_code == 200
        assert "access_token" in response.data
        assert "refresh_token" in response.data
        assert "user" in response.data
        assert "role" in response.data["user"]
        assert "id" in response.data["user"]

    def test_invalid_otp_returns_400(
        self, api_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        response = api_client.post(
            "/api/v1/auth/verify-otp/",
            data={
                "phone_number": resident.phone_number,
                "code": "999999",
                "auth_flow": "login",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_missing_fields_returns_400(self, api_client: Any) -> None:
        response = api_client.post(
            "/api/v1/auth/verify-otp/",
            data={"phone_number": "+919000000001"},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestTokenRefreshView:

    def test_valid_refresh_returns_new_pair(
        self, api_client: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        from apps.users.services import AuthService

        tokens = AuthService.issue_tokens(resident)

        response = api_client.post(
            "/api/v1/auth/token/refresh/",
            data={"refresh_token": tokens["refresh_token"]},
            format="json",
        )

        assert response.status_code == 200
        assert "access_token" in response.data
        assert "refresh_token" in response.data

    def test_invalid_refresh_token_returns_401(self, api_client: Any) -> None:
        response = api_client.post(
            "/api/v1/auth/token/refresh/",
            data={"refresh_token": "not.a.valid.jwt"},
            format="json",
        )
        assert response.status_code == 401


@pytest.mark.django_db
class TestLogoutView:

    def test_authenticated_logout_returns_204(
        self, auth_client: Any, resident: Any
    ) -> None:
        from apps.users.services import AuthService

        tokens = AuthService.issue_tokens(resident)

        response = auth_client.post(
            "/api/v1/auth/logout/",
            data={"refresh_token": tokens["refresh_token"]},
            format="json",
        )
        assert response.status_code == 204

    def test_unauthenticated_logout_returns_403(self, api_client: Any) -> None:
        response = api_client.post("/api/v1/auth/logout/", data={}, format="json")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestMeView:

    def test_get_me_returns_user_data(self, auth_client: Any, resident: Any) -> None:
        response = auth_client.get("/api/v1/auth/me/")

        assert response.status_code == 200
        assert str(response.data["id"]) == str(resident.id)
        assert response.data["role"] == UserRole.RESIDENT
        assert "phone_number" in response.data

    def test_get_me_unauthenticated_returns_403(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/auth/me/")
        assert response.status_code in (401, 403)

    def test_patch_me_updates_push_token(self, auth_client: Any, resident: Any) -> None:
        new_token = "ExponentPushToken[patch-test-token]"

        response = auth_client.patch(
            "/api/v1/auth/me/",
            data={"expo_push_token": new_token},
            format="json",
        )

        assert response.status_code == 200
        resident.refresh_from_db()
        assert resident.expo_push_token == new_token

    def test_patch_me_updates_profile_name(
        self, auth_client: Any, resident: Any
    ) -> None:
        response = auth_client.patch(
            "/api/v1/auth/me/",
            data={"name": "Updated Name"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["name"] == "Updated Name"
        resident.refresh_from_db()
        assert resident.name == "Updated Name"
