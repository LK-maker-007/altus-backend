"""
apps/emergency/services.py

EmergencyService — business logic for emergency contact retrieval.

WHY a service layer for a simple read operation:
  ADR-010 mandates that all business logic lives in the service layer, not views.
  Even a "simple" read involves caching strategy (TTL, key format, invalidation).
  Moving this logic to a service makes it:
    - Testable without HTTP: unit tests call the service directly.
    - Reusable: any future caller (Celery task, admin command, GraphQL resolver)
      gets the same caching behaviour without duplicating it.
    - Consistent: follows the same pattern as BookingService, MaintenanceService.
  Source: audit §P2 §emergency app violates ADR-010;
          HackSoftware Django Styleguide §Services.
"""

from __future__ import annotations

from typing import cast

import structlog
from django.core.cache import cache

from apps.emergency.models import EmergencyContact
from apps.emergency.serializers import EmergencyContactSerializer

logger = structlog.get_logger(__name__)

# 1-hour TTL — per api-contract §9. Contacts change infrequently; cache
# invalidation is handled in EmergencyContactAdmin.save_model / delete_model.
_CONTACTS_CACHE_TTL = 3600


def _cache_key(complex_id: str) -> str:
    return f"complex:{complex_id}:contacts"


class EmergencyService:
    """Service layer for emergency contact operations."""

    @staticmethod
    def get_contacts(complex_id: str) -> list[dict[str, object]]:
        """Return active emergency contacts for a complex (cache-first).

        Contacts are served from Redis cache with a 1-hour TTL. Cache is
        invalidated by EmergencyContactAdmin.save_model and delete_model on
        any admin change.

        Args:
            complex_id: UUID string of the complex whose contacts to retrieve.

        Returns:
            List of serialised EmergencyContact dicts, ordered by display_order.
        """
        cache_key = _cache_key(complex_id)
        cached = cache.get(cache_key)
        if cached is not None:
            return cast("list[dict[str, object]]", cached)

        qs = EmergencyContact.objects.filter(is_active=True).order_by("display_order")
        data = list(EmergencyContactSerializer(qs, many=True).data)
        cache.set(cache_key, data, timeout=_CONTACTS_CACHE_TTL)

        logger.info("emergency_contacts_cache_miss", complex_id=complex_id)
        return data
