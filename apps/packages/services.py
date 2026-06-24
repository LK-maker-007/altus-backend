from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.packages.exceptions import (
    PackageAlreadyCollectedError,
    PackageNotFoundError,
    PackagePermissionError,
)
from apps.packages.models import Package, PackageStatus
from apps.users.models import User, UserRole


class PackageService:

    @staticmethod
    def log_package(
        security_guard: User,
        unit_number: str,
        building_block: str,
        complex_id: str,
        description: str,
        notes: str,
    ) -> Package:
        from apps.core.models import Unit

        try:
            unit = Unit.objects.select_related("registered_resident").get(
                complex_id=complex_id,
                unit_number=unit_number,
                building_block=building_block,
            )
        except Unit.DoesNotExist:
            raise PackageNotFoundError() from None

        with transaction.atomic():
            package = Package.objects.create(
                complex_id=complex_id,
                unit=unit,
                logged_by=security_guard,
                description=description,
                notes=notes,
                status=PackageStatus.PENDING,
            )

            from apps.packages.tasks import notify_package_arrived

            resident = unit.registered_resident
            if resident and resident.expo_push_token:
                transaction.on_commit(
                    lambda: notify_package_arrived.apply_async(
                        args=(
                            str(package.id),
                            complex_id,
                        ),
                    )
                )

        return Package.unscoped.select_related("unit").get(pk=package.pk)

    @staticmethod
    def mark_collected(
        package_id: str,
        complex_id: str,
        collector: User,
    ) -> Package:
        with transaction.atomic():
            try:
                package = Package.unscoped.select_for_update(nowait=True).get(
                    id=package_id,
                    complex_id=complex_id,
                )
            except Package.DoesNotExist:
                raise PackageNotFoundError() from None

            # A resident may collect only their own unit's package; security/admin
            # collect on anyone's behalf. complex scoping alone is not enough here.
            if (
                collector.role == UserRole.RESIDENT
                and package.unit_id != collector.unit_id
            ):
                raise PackagePermissionError()

            if package.status == PackageStatus.COLLECTED:
                raise PackageAlreadyCollectedError()

            package.status = PackageStatus.COLLECTED
            package.collected_at = timezone.now()
            package.collected_by = collector
            package.save(
                update_fields=[
                    "status",
                    "collected_at",
                    "collected_by_id",
                    "updated_at",
                ]
            )

        return package
