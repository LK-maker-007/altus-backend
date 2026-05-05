from __future__ import annotations

"""
Unit tests for apps.notifications.helpers.expo_push_send (lines 41-77).

expo_push_send is fire-and-forget — it never raises, even on HTTP error.
All network calls are patched via mocker.patch("httpx.post") at the deferred
import site (httpx is imported inside the function body, line 31).

Lines covered by these tests:
  47-53  — httpx.HTTPError branch (network failure)
  56-61  — non-200 status code branch
  64-73  — 200 but Expo inner ticket.status == "error" branch
  74-77  — response.json() parse failure branch

The happy-path call (lines 42-46, 55, 63) is already covered indirectly by
every task test that calls expo_push_send without mocking the HTTP layer.
These tests cover the failure paths explicitly.

Patch target: "httpx.post"
  httpx is imported *inside* expo_push_send (deferred, line 31).
  mocker.patch("httpx.post") intercepts it at the module level regardless
  of where it was imported — this is the correct pattern for deferred imports.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.django_db
class TestExpoPushSend:
    """
    Tests for apps.notifications.helpers.expo_push_send.

    All tests patch "httpx.post" — never make real HTTP calls.
    EXPO_PUSH_URL has a default in settings.base ("https://exp.host/...")
    so no settings override is needed.
    """

    def _call(self, mocker: Any, *, post_mock: Any = None) -> Any:
        """Helper: import and call expo_push_send with standard test args."""
        from apps.notifications.helpers import expo_push_send

        expo_push_send(
            token="ExponentPushToken[test-notifications-helper]",
            title="Test title",
            body="Test body",
            data={"key": "value"},
        )

    def test_http_error_does_not_raise(self, mocker: Any) -> None:
        """
        httpx.post raises httpx.HTTPError (network failure, DNS error, timeout).
        expo_push_send must catch it, log a warning, and return — never re-raise.
        Covers lines 47-53.
        """
        import httpx

        from apps.notifications.helpers import expo_push_send

        mocker.patch("httpx.post", side_effect=httpx.HTTPError("connection refused"))

        # Must not raise — fire-and-forget guarantee
        expo_push_send(
            token="ExponentPushToken[helper-http-error]",
            title="T",
            body="B",
            data={},
        )

    def test_non_200_response_does_not_raise(self, mocker: Any) -> None:
        """
        httpx.post returns a 500 response.
        expo_push_send must log a warning and return — never raise.
        Covers lines 56-61.
        """
        from apps.notifications.helpers import expo_push_send

        mock_response = MagicMock()
        mock_response.status_code = 500
        mocker.patch("httpx.post", return_value=mock_response)

        # Must not raise
        expo_push_send(
            token="ExponentPushToken[helper-non-200]",
            title="T",
            body="B",
            data={},
        )

    def test_200_with_expo_ticket_error_does_not_raise(self, mocker: Any) -> None:
        """
        httpx.post returns 200 but the Expo response body contains a per-token error.
        Example: device token expired → {"data": {"status": "error", "message": "..."}}
        expo_push_send must log a warning and return — never raise.
        Covers lines 64-73.
        """
        from apps.notifications.helpers import expo_push_send

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "status": "error",
                "message": "DeviceNotRegistered",
                "details": {"error": "DeviceNotRegistered"},
            }
        }
        mocker.patch("httpx.post", return_value=mock_response)

        # Must not raise
        expo_push_send(
            token="ExponentPushToken[helper-ticket-error]",
            title="T",
            body="B",
            data={},
        )

    def test_200_with_malformed_json_does_not_raise(self, mocker: Any) -> None:
        """
        httpx.post returns 200 but response.json() raises (malformed body).
        expo_push_send catches the bare Exception and logs a warning — never raises.
        Covers lines 74-77.
        """
        from apps.notifications.helpers import expo_push_send

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Expecting value: malformed JSON")
        mocker.patch("httpx.post", return_value=mock_response)

        # Must not raise
        expo_push_send(
            token="ExponentPushToken[helper-malformed-json]",
            title="T",
            body="B",
            data={},
        )

    def test_happy_path_calls_httpx_post_with_correct_payload(
        self, mocker: Any, settings: Any
    ) -> None:
        """
        Successful push — httpx.post called with the exact Expo payload structure.
        Verifies the payload dict keys: to, title, body, data, sound.
        Covers lines 33-46 (the request construction + call).
        """
        from apps.notifications.helpers import expo_push_send

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"status": "ok", "id": "abc123"}}
        mock_post = mocker.patch("httpx.post", return_value=mock_response)

        expo_push_send(
            token="ExponentPushToken[helper-happy-path]",
            title="Pool closed",
            body="The pool is closed for maintenance.",
            data={"announcement_id": "xyz"},
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        # First positional arg is the URL
        assert call_kwargs.args[0] == settings.EXPO_PUSH_URL
        # json payload must match exactly
        payload = call_kwargs.kwargs["json"]
        assert payload["to"] == "ExponentPushToken[helper-happy-path]"
        assert payload["title"] == "Pool closed"
        assert payload["body"] == "The pool is closed for maintenance."
        assert payload["data"] == {"announcement_id": "xyz"}
        assert payload["sound"] == "default"
        assert call_kwargs.kwargs["timeout"] == 10
