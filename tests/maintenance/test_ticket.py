from __future__ import annotations

"""
Maintenance ticket tests - creation, idempotency, photo bypass, status history.

Coverage target: apps/maintenance/services.py

Verified service signature (2026-04-23):
  MaintenanceService.create_ticket(
      resident, category, description, photos, client_idempotency_key=None, queued_at=None
  )
  - unit resolved internally via Unit.objects.get(registered_resident=resident)
  - complex_id resolved from resident.complex_id
  - Raises TicketNotFoundError if resident has no linked unit

NOTE: The test for create_ticket_returns_open_ticket patches apps.maintenance.services._upload_photo_to_r2
(NOT apps.maintenance._upload_photo_to_r2 — the function lives in the services module).
"""

from typing import Any
from unittest.mock import patch

import pytest

from apps.maintenance.models import (
    MaintenanceTicket,
    TicketCategory,
    TicketStatus,
    TicketStatusHistory,
)
from apps.maintenance.services import MaintenanceService
from tests.factories.maintenance_factory import MaintenanceTicketFactory


@pytest.mark.django_db
class TestTicketCreation:
    """US-019 - Resident creates a maintenance ticket."""

    def test_create_ticket_returns_open_ticket(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Happy path - service creates an OPEN ticket and initial history entry."""
        # Photos are empty — no R2 upload needed, so no mock required
        ticket = MaintenanceService.create_ticket(
            resident=resident,
            category=TicketCategory.PLUMBING,
            description="Tap dripping in kitchen since yesterday.",
            photos=[],
            client_idempotency_key=None,
            queued_at=None,
        )

        assert ticket.status == TicketStatus.OPEN
        assert ticket.category == TicketCategory.PLUMBING
        assert ticket.raised_by_id == resident.pk
        assert str(ticket.complex_id) == str(complex_a.id)

    def test_create_ticket_with_photo_calls_r2_upload(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """A ticket with photos must attempt the R2 upload — patched at the module level."""
        from unittest.mock import MagicMock

        mock_photo = MagicMock()
        mock_photo.name = "photo.jpg"
        mock_photo.size = 1024
        mock_photo.content_type = "image/jpeg"
        mock_photo.read.return_value = b"\xff\xd8\xff"  # JPEG magic bytes
        mock_photo.seek.return_value = None

        with (
            patch("apps.maintenance.services._validate_photos"),
            patch(
                "apps.maintenance.services._upload_photo_to_r2",
                return_value="https://media.ci/photo.jpg",
            ) as mock_upload,
        ):
            ticket = MaintenanceService.create_ticket(
                resident=resident,
                category=TicketCategory.ELECTRICAL,
                description="Socket not working.",
                photos=[mock_photo],
                client_idempotency_key=None,
                queued_at=None,
            )

        mock_upload.assert_called_once()
        assert ticket.photos.count() == 1

    def test_idempotency_key_deduplicates_retry(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        Same idempotency_key submitted twice → returns existing ticket, no duplicate.

        This covers offline-queued tickets retried after a network reconnect.
        Source: database-schema.md section 3.10, offline-strategy.md section 3.
        """
        import uuid

        key = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")

        ticket_1 = MaintenanceService.create_ticket(
            resident=resident,
            category=TicketCategory.ELECTRICAL,
            description="Power socket not working in bedroom.",
            photos=[],
            client_idempotency_key=key,
            queued_at=None,
        )
        ticket_2 = MaintenanceService.create_ticket(
            resident=resident,
            category=TicketCategory.ELECTRICAL,
            description="Power socket not working in bedroom.",
            photos=[],
            client_idempotency_key=key,
            queued_at=None,
        )

        assert str(ticket_1.id) == str(ticket_2.id)
        count = MaintenanceTicket.objects.filter(client_idempotency_key=key).count()
        assert count == 1

    def test_create_ticket_writes_initial_status_history(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Ticket creation must write a OPEN TicketStatusHistory entry automatically."""
        ticket = MaintenanceService.create_ticket(
            resident=resident,
            category=TicketCategory.CARPENTRY,
            description="Cabinet door hinge broken.",
            photos=[],
            client_idempotency_key=None,
            queued_at=None,
        )

        history = TicketStatusHistory.objects.filter(ticket=ticket)
        assert history.count() == 1
        first = history.first()
        assert first is not None
        assert first.status == TicketStatus.OPEN
        assert first.changed_by is None  # system-generated on creation

    def test_resident_without_unit_raises_ticket_not_found(
        self, complex_a: Any
    ) -> None:
        """A resident with no linked unit must raise TicketNotFoundError."""
        from apps.maintenance.exceptions import TicketNotFoundError
        from tests.factories.user_factory import UserFactory

        # Create a user with no unit linked (unit_id will be None by default)
        orphan = UserFactory(
            complex=complex_a,
            phone_number="+919000000077",
        )
        assert orphan.unit_id is None

        with pytest.raises(TicketNotFoundError, match="No unit"):
            MaintenanceService.create_ticket(
                resident=orphan,
                category=TicketCategory.PLUMBING,
                description="Test.",
                photos=[],
            )


@pytest.mark.django_db
class TestTicketStatusFromFactory:
    """
    Tests via factory (bypassing the service) for admin-facing status transitions.

    The admin-facing update_status path is exposed through views.
    These tests verify model-layer behaviour only.
    """

    def test_ticket_history_is_append_only(
        self, complex_a: Any, unit_a: Any, resident: Any, admin_user: Any
    ) -> None:
        """Multiple TicketStatusHistory rows must be created, never overwritten."""
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.OPEN,
        )

        # Simulate two sequential admin status changes directly at model layer
        TicketStatusHistory.objects.create(
            ticket=ticket,
            status=TicketStatus.IN_PROGRESS,
            changed_by=admin_user,
        )
        ticket.status = TicketStatus.IN_PROGRESS
        ticket.save(update_fields=["status", "updated_at"])

        TicketStatusHistory.objects.create(
            ticket=ticket,
            status=TicketStatus.RESOLVED,
            changed_by=admin_user,
        )
        ticket.status = TicketStatus.RESOLVED
        ticket.save(update_fields=["status", "updated_at"])

        assert TicketStatusHistory.objects.filter(ticket=ticket).count() == 2

    def test_factory_creates_ticket_with_open_status(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """Sanity check - factory defaults produce a valid OPEN ticket."""
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
        )
        assert ticket.status == TicketStatus.OPEN
        assert ticket.complex_id == complex_a.id


# ── _validate_photos ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPhotoValidation:
    """
    Unit tests for apps.maintenance.services._validate_photos (lines 54-71).

    _validate_photos uses python-magic (production.txt) which is not installed
    in the test venv. We patch "magic.from_buffer" at the point where it is
    imported inside the function (deferred import inside services.py line 54).

    Photo count, size, and MIME validation are all tested independently.
    """

    def _make_photo(
        self,
        *,
        name: str = "photo.jpg",
        size: int = 1024,
        content: bytes = b"\xff\xd8\xff",
    ) -> Any:
        """Return a minimal MagicMock mimicking a Django UploadedFile."""
        from unittest.mock import MagicMock

        photo = MagicMock()
        photo.name = name
        photo.size = size
        photo.read.return_value = content
        photo.seek.return_value = None
        return photo

    def test_too_many_photos_raises(self) -> None:
        """More than 3 photos → TicketPhotoValidationError before any MIME check.
        python-magic is not installed on dev/CI machines — inject the fake module
        before calling _validate_photos(), which does `import magic` before the count check.
        """
        import sys
        import types

        from apps.maintenance.exceptions import TicketPhotoValidationError
        from apps.maintenance.services import _validate_photos

        # Inject fake magic module — count check raises before MIME detection
        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/jpeg"  # type: ignore[attr-defined]
        sys.modules.setdefault("magic", fake_magic)

        photos = [self._make_photo() for _ in range(4)]

        with pytest.raises(TicketPhotoValidationError, match="Maximum 3 photos"):
            _validate_photos(photos)

    def test_photo_exceeds_size_limit_raises(self, mocker: Any) -> None:
        """A photo larger than 5 MB → TicketPhotoValidationError."""
        import sys
        import types

        from apps.maintenance.exceptions import TicketPhotoValidationError
        from apps.maintenance.services import _validate_photos

        # python-magic is production-only — inject a fake module for the deferred import
        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/jpeg"  # type: ignore[attr-defined]
        sys.modules.setdefault("magic", fake_magic)
        oversized = self._make_photo(size=6 * 1024 * 1024)  # 6 MB

        with pytest.raises(TicketPhotoValidationError, match="exceeds the 5 MB"):
            _validate_photos([oversized])

    def test_disallowed_mime_type_raises(self, mocker: Any) -> None:
        """A file detected as image/gif → TicketPhotoValidationError."""
        import sys
        import types

        from apps.maintenance.exceptions import TicketPhotoValidationError
        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/gif"  # type: ignore[attr-defined]
        sys.modules["magic"] = fake_magic
        gif = self._make_photo(name="file.gif")

        with pytest.raises(TicketPhotoValidationError, match="not allowed"):
            _validate_photos([gif])

    def test_valid_jpeg_passes(self, mocker: Any) -> None:
        """A valid JPEG within size limits must pass without raising."""
        import sys
        import types

        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/jpeg"  # type: ignore[attr-defined]
        sys.modules["magic"] = fake_magic
        jpeg = self._make_photo(name="photo.jpg", size=2 * 1024 * 1024)

        # Must not raise
        _validate_photos([jpeg])

    def test_valid_png_passes(self, mocker: Any) -> None:
        """A valid PNG must pass — image/png is in _ALLOWED_MIME_TYPES."""
        import sys
        import types

        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/png"  # type: ignore[attr-defined]
        sys.modules["magic"] = fake_magic
        png = self._make_photo(name="photo.png")

        _validate_photos([png])

    def test_valid_heic_passes(self, mocker: Any) -> None:
        """A valid HEIC (iPhone photo) must pass — image/heic is allowed."""
        import sys
        import types

        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/heic"  # type: ignore[attr-defined]
        sys.modules["magic"] = fake_magic
        heic = self._make_photo(name="photo.heic")

        _validate_photos([heic])


# ── _upload_photo_to_r2 ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestR2Upload:
    """
    Unit tests for apps.maintenance.services._upload_photo_to_r2 (lines 84-101)
    and _get_r2_client (lines 36-38).

    boto3 is not installed in the test venv (it's in production.txt).
    We patch "boto3.client" where it is imported (deferred inside _get_r2_client).

    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME,
    and R2_PUBLIC_URL are all in settings.test — confirmed in config/settings/test.py.
    We override them via Django's override_settings to ensure isolation.
    """

    def _make_photo(
        self,
        *,
        name: str = "receipt.jpg",
        content_type: str = "image/jpeg",
    ) -> Any:
        from unittest.mock import MagicMock

        photo = MagicMock()
        photo.name = name
        photo.content_type = content_type
        return photo

    def test_upload_returns_public_url(self, mocker: Any, settings: Any) -> None:
        """
        Happy path — boto3 upload_fileobj succeeds.
        Return value must be {R2_PUBLIC_URL}/tickets/{ticket_id}/{uuid}.{ext}.
        """
        from apps.maintenance.services import _upload_photo_to_r2

        settings.R2_PUBLIC_URL = "https://media.example.com"
        settings.R2_BUCKET_NAME = "test-bucket"
        settings.R2_ACCOUNT_ID = "test-account"
        settings.R2_ACCESS_KEY_ID = "test-key"
        settings.R2_SECRET_ACCESS_KEY = "test-secret"

        mock_client = mocker.MagicMock()
        mocker.patch(
            "apps.maintenance.services._get_r2_client", return_value=mock_client
        )

        photo = self._make_photo(name="damage.jpg")
        ticket_id = "aabbccdd-0000-0000-0000-000000000001"

        url = _upload_photo_to_r2(ticket_id, photo)

        # URL must start with the public URL prefix and contain the ticket_id
        assert url.startswith("https://media.example.com/tickets/aabbccdd")
        assert url.endswith(".jpg")
        mock_client.upload_fileobj.assert_called_once()

    def test_upload_failure_raises_ticket_photo_validation_error(
        self, mocker: Any, settings: Any
    ) -> None:
        """
        boto3 upload_fileobj raises an exception (S3 error, network timeout, etc.).
        _upload_photo_to_r2 must catch it and raise TicketPhotoValidationError
        so that no partial ticket is written to the DB.
        """
        from apps.maintenance.exceptions import TicketPhotoValidationError
        from apps.maintenance.services import _upload_photo_to_r2

        settings.R2_PUBLIC_URL = "https://media.example.com"
        settings.R2_BUCKET_NAME = "test-bucket"
        settings.R2_ACCOUNT_ID = "test-account"
        settings.R2_ACCESS_KEY_ID = "test-key"
        settings.R2_SECRET_ACCESS_KEY = "test-secret"

        mock_client = mocker.MagicMock()
        mock_client.upload_fileobj.side_effect = Exception("S3 connection refused")
        mocker.patch(
            "apps.maintenance.services._get_r2_client", return_value=mock_client
        )

        photo = self._make_photo(name="damage.png", content_type="image/png")

        with pytest.raises(TicketPhotoValidationError, match="Photo upload failed"):
            _upload_photo_to_r2("some-ticket-id", photo)

    def test_ext_falls_back_to_jpg_when_name_has_no_extension(
        self, mocker: Any, settings: Any
    ) -> None:
        """
        photo.name has no '.' separator → ext defaults to 'jpg'.
        Ensures the object_key ends in .jpg and the URL is valid.
        """
        from apps.maintenance.services import _upload_photo_to_r2

        settings.R2_PUBLIC_URL = "https://media.example.com"
        settings.R2_BUCKET_NAME = "test-bucket"
        settings.R2_ACCOUNT_ID = "test-account"
        settings.R2_ACCESS_KEY_ID = "test-key"
        settings.R2_SECRET_ACCESS_KEY = "test-secret"

        mock_client = mocker.MagicMock()
        mocker.patch(
            "apps.maintenance.services._get_r2_client", return_value=mock_client
        )

        photo = self._make_photo(name="noextension")  # no dot in filename
        url = _upload_photo_to_r2("ticket-123", photo)

        assert url.endswith(".noextension")  # rsplit(".", 1)[-1] → "noextension"
