from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import UserRole
from tests.factories.complex_factory import ComplexFactory
from tests.factories.unit_factory import UnitFactory
from tests.factories.user_factory import UserFactory


def _build_test_qr_token(complex_slug: str, ttl_seconds: int = 3600) -> str:
    secret = settings.QR_TOKEN_SECRET.encode()
    exp = int(time.time()) + ttl_seconds
    sig = hmac.new(
        secret,
        f"{complex_slug}:{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    payload = json.dumps({"slug": complex_slug, "exp": exp, "sig": sig}).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


@pytest.mark.django_db
class TestRegistration:

    def test_valid_registration_sends_otp(self, api_client: APIClient) -> None:
        complex_ = ComplexFactory()
        unit = UnitFactory(complex=complex_)

        token = _build_test_qr_token(complex_.slug)

        with patch("apps.users.services.OTPService.send") as mock_send:
            mock_send.return_value = None
            response = api_client.post(
                "/api/v1/auth/register/",
                {
                    "registration_token": token,
                    "complex_slug": complex_.slug,
                    "phone_number": "+919876543210",
                    "unit_number": unit.unit_number,
                    "building_block": unit.building_block,
                },
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "otp_sent"
        mock_send.assert_called_once()

    def test_invalid_unit_returns_generic_error(self, api_client: APIClient) -> None:
        complex_ = ComplexFactory()
        token = _build_test_qr_token(complex_.slug)

        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "registration_token": token,
                "complex_slug": complex_.slug,
                "phone_number": "+919876543210",
                "unit_number": "Z-999",
                "building_block": "Z",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "REGISTRATION_FAILED"

    def test_already_registered_unit_returns_generic_error(
        self, api_client: APIClient
    ) -> None:
        complex_ = ComplexFactory()
        unit = UnitFactory(complex=complex_)
        existing_user = UserFactory(complex=complex_, role=UserRole.RESIDENT)
        unit.registered_resident = existing_user
        unit.save(update_fields=["registered_resident_id"])

        token = _build_test_qr_token(complex_.slug)

        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "registration_token": token,
                "complex_slug": complex_.slug,
                "phone_number": "+919111111111",
                "unit_number": unit.unit_number,
                "building_block": unit.building_block,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "REGISTRATION_FAILED"

    def test_expired_registration_token_is_rejected(
        self, api_client: APIClient
    ) -> None:
        complex_ = ComplexFactory()
        unit = UnitFactory(complex=complex_)

        expired_token = _build_test_qr_token(complex_.slug, ttl_seconds=-1)

        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "registration_token": expired_token,
                "complex_slug": complex_.slug,
                "phone_number": "+919876543210",
                "unit_number": unit.unit_number,
                "building_block": unit.building_block,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_tampered_token_is_rejected(self, api_client: APIClient) -> None:
        complex_ = ComplexFactory()
        unit = UnitFactory(complex=complex_)

        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "registration_token": "this.is.not.a.valid.token",
                "complex_slug": complex_.slug,
                "phone_number": "+919876543210",
                "unit_number": unit.unit_number,
                "building_block": unit.building_block,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_registration_endpoint_is_public_no_jwt_needed(
        self, api_client: APIClient
    ) -> None:
        response = api_client.post("/api/v1/auth/register/", {}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestOTPVerification:

    def test_valid_otp_returns_jwt_tokens(self, api_client: APIClient) -> None:
        user = UserFactory(phone_number="+919000000050", role=UserRole.RESIDENT)

        response = api_client.post(
            "/api/v1/auth/verify-otp/",
            {
                "phone_number": user.phone_number,
                "code": "000000",
                "auth_flow": "registration",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access_token" in response.data
        assert "refresh_token" in response.data

    def test_invalid_otp_returns_error(self, api_client: APIClient) -> None:
        user = UserFactory(phone_number="+919000000051", role=UserRole.RESIDENT)

        response = api_client.post(
            "/api/v1/auth/verify-otp/",
            {
                "phone_number": user.phone_number,
                "code": "999999",
                "auth_flow": "registration",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "access_token" not in response.data

    def test_nonexistent_phone_returns_same_error_as_wrong_otp(
        self, api_client: APIClient
    ) -> None:
        response = api_client.post(
            "/api/v1/auth/verify-otp/",
            {
                "phone_number": "+919999999999",
                "code": "000000",
                "auth_flow": "registration",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "access_token" not in response.data


@pytest.mark.django_db
class TestTokenRefresh:

    def test_valid_refresh_token_returns_new_access_token(
        self, api_client: APIClient
    ) -> None:
        from apps.users.services import AuthService

        user = UserFactory(role=UserRole.RESIDENT)
        tokens = AuthService.issue_tokens(user)

        response = api_client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh_token": tokens["refresh_token"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access_token" in response.data

    def test_expired_refresh_token_returns_401(self, api_client: APIClient) -> None:
        response = api_client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh_token": "tampered.invalid.token"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestMeEndpoint:

    def test_authenticated_resident_can_get_profile(
        self, auth_client: APIClient
    ) -> None:
        response = auth_client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK

    def test_unauthenticated_cannot_access_me(self, api_client: APIClient) -> None:
        response = api_client.get("/api/v1/auth/me/")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_incomplete_profile_can_patch_name(self, api_client: APIClient) -> None:
        incomplete_user = UserFactory(
            role=UserRole.RESIDENT,
            is_profile_complete=False,
        )
        client = APIClient()
        client.force_authenticate(user=incomplete_user)

        response = client.patch(
            "/api/v1/auth/me/",
            {"name": "Test Resident"},
            format="json",
        )

        assert response.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT)
        incomplete_user.refresh_from_db()
        assert incomplete_user.name == "Test Resident"

    def test_me_response_contains_expected_fields(self, auth_client: APIClient) -> None:
        response = auth_client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert "phone_number" in response.data
        assert "role" in response.data
        assert "is_profile_complete" in response.data
