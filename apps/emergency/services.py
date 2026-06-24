from __future__ import annotations

from typing import cast

import structlog
from django.core.cache import cache

from apps.emergency.models import EmergencyContact
from apps.emergency.serializers import EmergencyContactSerializer

logger = structlog.get_logger(__name__)

_CONTACTS_CACHE_TTL = 3600


def _cache_key(complex_id: str) -> str:
    return f"complex:{complex_id}:contacts"


class EmergencyService:

    @staticmethod
    def get_contacts(complex_id: str) -> list[dict[str, object]]:
        cache_key = _cache_key(complex_id)
        cached = cache.get(cache_key)
        if cached is not None:
            return cast("list[dict[str, object]]", cached)

        qs = EmergencyContact.unscoped.filter(
            complex_id=complex_id, is_active=True
        ).order_by("display_order")
        data = list(EmergencyContactSerializer(qs, many=True).data)
        cache.set(cache_key, data, timeout=_CONTACTS_CACHE_TTL)

        logger.info("emergency_contacts_cache_miss", complex_id=complex_id)
        return data
