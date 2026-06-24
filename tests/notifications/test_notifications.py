from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.django_db
class TestExpoPushSend:

    def _call(self, mocker: Any, *, post_mock: Any = None) -> Any:
        from apps.notifications.helpers import expo_push_send

        expo_push_send(
            token="ExponentPushToken[test-notifications-helper]",
            title="Test title",
            body="Test body",
            data={"key": "value"},
        )

    def test_http_error_does_not_raise(self, mocker: Any) -> None:
        import httpx

        from apps.notifications.helpers import expo_push_send

        mocker.patch("httpx.post", side_effect=httpx.HTTPError("connection refused"))

        expo_push_send(
            token="ExponentPushToken[helper-http-error]",
            title="T",
            body="B",
            data={},
        )

    def test_non_200_response_does_not_raise(self, mocker: Any) -> None:
        from apps.notifications.helpers import expo_push_send

        mock_response = MagicMock()
        mock_response.status_code = 500
        mocker.patch("httpx.post", return_value=mock_response)

        expo_push_send(
            token="ExponentPushToken[helper-non-200]",
            title="T",
            body="B",
            data={},
        )

    def test_200_with_expo_ticket_error_does_not_raise(self, mocker: Any) -> None:
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

        expo_push_send(
            token="ExponentPushToken[helper-ticket-error]",
            title="T",
            body="B",
            data={},
        )

    def test_200_with_malformed_json_does_not_raise(self, mocker: Any) -> None:
        from apps.notifications.helpers import expo_push_send

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Expecting value: malformed JSON")
        mocker.patch("httpx.post", return_value=mock_response)

        expo_push_send(
            token="ExponentPushToken[helper-malformed-json]",
            title="T",
            body="B",
            data={},
        )

    def test_happy_path_calls_httpx_post_with_correct_payload(
        self, mocker: Any, settings: Any
    ) -> None:
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
        assert call_kwargs.args[0] == settings.EXPO_PUSH_URL
        payload = call_kwargs.kwargs["json"]
        assert payload["to"] == "ExponentPushToken[helper-happy-path]"
        assert payload["title"] == "Pool closed"
        assert payload["body"] == "The pool is closed for maintenance."
        assert payload["data"] == {"announcement_id": "xyz"}
        assert payload["sound"] == "default"
        assert call_kwargs.kwargs["timeout"] == 10
