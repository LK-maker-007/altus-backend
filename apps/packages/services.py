from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.packages.exceptions import PackageAlreadyCollectedError, PackageNotFoundError
from apps.packages.models import Package, PackageStatus
from apps.users.models import User


class PackageService:
    """Business logic for package logging and collection.

    All methods are stateless @staticmethod — class is a namespace (ADR-010).
    """

    @staticmethod
    def log_package(
        security_guard: User,
        unit_number: str,
        building_block: str,
        complex_id: str,
        description: str,
        notes: str,
    ) -> Package:
        """Log an incoming package against a unit (US-024).

        Resolves the unit by number + block within the complex. The unit lookup
        must be strict — security staff can mistype; never silently fall through.
        Enqueues a push notification to the registered resident via on_commit.
        """
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

            # Notify the registered resident if one exists and has a push token.
            # on_commit fires after the outermost transaction commits — not on rollback.
            # Deferred import — breaks services→tasks circular import.
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

        # CRIT-005: select_related avoids refresh_from_db() N+1 in view
        return Package.unscoped.select_related("unit").get(pk=package.pk)

    @staticmethod
    def mark_collected(
        package_id: str,
        complex_id: str,
        collector: User,
    ) -> Package:
        """Mark a package as collected by the resident or security (US-026).

        select_for_update(nowait=True) prevents a race condition where two
        concurrent requests both attempt to collect the same package.
        """
        with transaction.atomic():
            try:
                package = Package.unscoped.select_for_update(nowait=True).get(
                    id=package_id,
                    complex_id=complex_id,
                )
            except Package.DoesNotExist:
                raise PackageNotFoundError() from None

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
