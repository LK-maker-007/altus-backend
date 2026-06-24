from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.db import OperationalError


@pytest.mark.django_db
class TestHealthCheckView:

    def test_healthy_returns_200_ok(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/health/")

        assert response.status_code == 200
        assert response.data["status"] == "ok"
        assert response.data["checks"]["database"] == "ok"
        assert response.data["checks"]["cache"] == "ok"

    def test_no_auth_required(self, api_client: Any) -> None:
        response = api_client.get("/api/v1/health/")
        assert response.status_code in (200, 503)
        assert "status" in response.data

    def test_database_failure_returns_503(self, api_client: Any) -> None:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = OperationalError(
            "could not connect to server"
        )

        with patch("apps.core.health.connection") as mock_conn:
            mock_conn.cursor.return_value = mock_cursor

            response = api_client.get("/api/v1/health/")

        assert response.status_code == 503
        assert response.data["status"] == "degraded"
        assert "error:" in response.data["checks"]["database"]
        assert response.data["checks"]["cache"] == "ok"

    def test_cache_failure_returns_503(self, api_client: Any) -> None:
        with patch("apps.core.health.cache") as mock_cache:
            mock_cache.set.side_effect = Exception("Connection refused: Redis")

            response = api_client.get("/api/v1/health/")

        assert response.status_code == 503
        assert response.data["status"] == "degraded"
        assert "error:" in response.data["checks"]["cache"]
        assert response.data["checks"]["database"] == "ok"

    def test_both_failures_returns_503(self, api_client: Any) -> None:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = OperationalError("DB down")

        with patch("apps.core.health.connection") as mock_conn:
            with patch("apps.core.health.cache") as mock_cache:
                mock_conn.cursor.return_value = mock_cursor
                mock_cache.set.side_effect = Exception("Redis down")

                response = api_client.get("/api/v1/health/")

        assert response.status_code == 503
        assert response.data["status"] == "degraded"
        assert "error:" in response.data["checks"]["database"]
        assert "error:" in response.data["checks"]["cache"]
