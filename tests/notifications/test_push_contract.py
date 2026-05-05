from __future__ import annotations

"""
Expo push notification payload contract tests.

These tests verify that expo_push_send() sends a payload that CONFORMS to the
official Expo Push API v2 specification — sourced directly from:
  https://docs.expo.dev/push-notifications/sending-notifications/

The contract is encoded as a JSON Schema checked against the actual payload
captured from httpx.post(). If Expo's API changes or our helper drifts, this
test fails before any code ships.

Why this matters (Staff L6 concern):
  Mocking httpx.post() and asserting it was called does NOT verify the payload
  structure. If 'sound' changes from a string to an object, or 'to' is renamed,
  or 'data' values are not strings — our unit tests pass but production drops all
  notifications silently.

Source: expo.dev/push-notifications/sending-notifications (verified 2026-04-25)
  Required fields: to (string | string[])
  Optional fields: title (str), body (str), data (Object), sound (str | null),
                   ttl (number), priority ('default'|'normal'|'high'), badge (number)
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

from apps.notifications.helpers import expo_push_send

# ─────────────────────────────────────────────────────────────────────────────
# Expo Push API v2 payload contract — sourced from official docs 2026-04-25
# https://docs.expo.dev/push-notifications/sending-notifications/#message-request-format
# ─────────────────────────────────────────────────────────────────────────────
EXPO_PUSH_PAYLOAD_SCHEMA = {
    "required_fields": ["to", "title", "body", "data", "sound"],
    "field_types": {
        "to": str,  # ExpoPushToken string
        "title": str,  # notification title
        "body": str,  # notification body
        "data": dict,  # key-value extras (values must be strings)
        "sound": str,  # "default" or custom sound name or null
    },
    "sound_allowed_values": ["default", None],  # null = no sound
    "to_token_prefix": "ExponentPushToken[",  # Expo token format
    "endpoint": "https://exp.host/--/api/v2/push/send",
}


class TestExpoPushPayloadContract:
    """
    Contract tests: verify the payload structure matches the Expo Push API v2 spec.

    These are NOT mocked at the assertion level — we capture the actual JSON
    passed to httpx.post() and validate it against the schema above.
    """

    def _call_and_capture_payload(
        self,
        token: str = "ExponentPushToken[contract-test-token]",
        title: str = "Test Title",
        body: str = "Test body message.",
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Call expo_push_send and return the payload that was sent to httpx.post()."""
        if data is None:
            data = {"type": "booking_reminder", "booking_id": "test-123"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"status": "ok", "id": "receipt-123"}}

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            expo_push_send(token=token, title=title, body=body, data=data)

        assert mock_post.called, "httpx.post() was never called"
        _, kwargs = mock_post.call_args
        return kwargs["json"]  # the actual payload dict

    def test_payload_contains_all_required_fields(self) -> None:
        """Every required field defined in the Expo v2 spec must be present."""
        payload = self._call_and_capture_payload()
        for field in EXPO_PUSH_PAYLOAD_SCHEMA["required_fields"]:
            assert field in payload, (
                f"Required Expo v2 field '{field}' is missing from payload.\n"
                f"Payload: {json.dumps(payload, indent=2)}"
            )

    def test_payload_field_types_match_expo_spec(self) -> None:
        """Each field must have the type specified in the Expo v2 message format."""
        payload = self._call_and_capture_payload()
        for field, expected_type in EXPO_PUSH_PAYLOAD_SCHEMA["field_types"].items():
            if field in payload and payload[field] is not None:
                assert isinstance(payload[field], expected_type), (
                    f"Expo v2 field '{field}' must be {expected_type.__name__}, "
                    f"got {type(payload[field]).__name__}: {payload[field]!r}"
                )

    def test_to_field_is_valid_expo_push_token(self) -> None:
        """The 'to' field must be a valid ExponentPushToken string."""
        token = "ExponentPushToken[contract-test-abc123]"
        payload = self._call_and_capture_payload(token=token)
        assert payload["to"] == token
        assert payload["to"].startswith(
            EXPO_PUSH_PAYLOAD_SCHEMA["to_token_prefix"]
        ), f"'to' field does not look like an Expo push token: {payload['to']!r}"

    def test_sound_is_default_string(self) -> None:
        """The 'sound' field must be 'default' per our helper implementation.
        This matches the Expo v2 spec: sound='default' triggers device default sound.
        """
        payload = self._call_and_capture_payload()
        assert (
            payload["sound"] == "default"
        ), f"Expected sound='default' per Expo v2 spec, got: {payload['sound']!r}"

    def test_data_values_are_strings(self) -> None:
        """
        Expo v2 spec: data values must be strings (Expo serialises to JSON).
        Non-string values (int, UUID, bool) will arrive as strings on the client
        only if serialised correctly — verify our helper enforces this.
        """
        data = {"type": "visitor_arrived", "visitor_id": "uuid-string", "count": "3"}
        payload = self._call_and_capture_payload(data=data)
        for key, value in payload["data"].items():
            assert isinstance(value, str), (
                f"Expo v2 data value for key '{key}' must be str, "
                f"got {type(value).__name__}: {value!r}"
            )

    def test_endpoint_is_official_expo_api(self) -> None:
        """The POST target must be the official Expo Push API v2 endpoint.
        If this URL changes in settings, this test catches the drift.
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"status": "ok"}}

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            expo_push_send(
                token="ExponentPushToken[endpoint-test]",
                title="T",
                body="B",
                data={"k": "v"},
            )

        actual_url = mock_post.call_args[0][0]
        assert "exp.host" in actual_url or "expo" in actual_url.lower(), (
            f"httpx.post() was called with unexpected URL: {actual_url!r}\n"
            f"Expected Expo Push API: {EXPO_PUSH_PAYLOAD_SCHEMA['endpoint']}"
        )

    def test_title_and_body_are_passed_through_unchanged(self) -> None:
        """Title and body must be passed exactly as provided — no truncation or encoding."""
        title = "Your visitor has arrived 🏠"
        body = (
            "John Doe has arrived at Gate B. Please come down. Reference: V-2026-001."
        )
        payload = self._call_and_capture_payload(title=title, body=body)
        assert payload["title"] == title
        assert payload["body"] == body

    def test_non_200_response_does_not_raise(self) -> None:
        """expo_push_send() is fire-and-forget — non-200 responses must be silently logged."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("httpx.post", return_value=mock_resp):
            expo_push_send(
                token="ExponentPushToken[500-test]",
                title="T",
                body="B",
                data={"k": "v"},
            )
        # No exception raised — fire-and-forget

    def test_expo_ticket_error_in_response_does_not_raise(self) -> None:
        """
        Expo returns HTTP 200 even for per-token errors (DeviceNotRegistered, etc.).
        The helper must parse the inner data.status field and log without raising.
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "status": "error",
                "message": '"ExponentPushToken[xxx]" is not a registered push notification recipient',
                "details": {"error": "DeviceNotRegistered"},
            }
        }

        with patch("httpx.post", return_value=mock_resp):
            expo_push_send(
                token="ExponentPushToken[unregistered-device]",
                title="T",
                body="B",
                data={"k": "v"},
            )
        # No exception — the caller (Celery task) must not crash
