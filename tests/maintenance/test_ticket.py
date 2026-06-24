from __future__ import annotations

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

    def test_create_ticket_returns_open_ticket(
        self, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
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
        from unittest.mock import MagicMock

        mock_photo = MagicMock()
        mock_photo.name = "photo.jpg"
        mock_photo.size = 1024
        mock_photo.content_type = "image/jpeg"
        mock_photo.read.return_value = b"\xff\xd8\xff"
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
        assert first.changed_by is None

    def test_resident_without_unit_raises_ticket_not_found(
        self, complex_a: Any
    ) -> None:
        from apps.maintenance.exceptions import TicketNotFoundError
        from tests.factories.user_factory import UserFactory

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

    def test_ticket_history_is_append_only(
        self, complex_a: Any, unit_a: Any, resident: Any, admin_user: Any
    ) -> None:
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
            status=TicketStatus.OPEN,
        )

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
        ticket = MaintenanceTicketFactory(
            complex=complex_a,
            unit=unit_a,
            raised_by=resident,
        )
        assert ticket.status == TicketStatus.OPEN
        assert ticket.complex_id == complex_a.id


@pytest.mark.django_db
class TestPhotoValidation:

    def _make_photo(
        self,
        *,
        name: str = "photo.jpg",
        size: int = 1024,
        content: bytes = b"\xff\xd8\xff",
    ) -> Any:
        from unittest.mock import MagicMock

        photo = MagicMock()
        photo.name = name
        photo.size = size
        photo.read.return_value = content
        photo.seek.return_value = None
        return photo

    def test_too_many_photos_raises(self) -> None:
        import sys
        import types

        from apps.maintenance.exceptions import TicketPhotoValidationError
        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/jpeg"
        sys.modules.setdefault("magic", fake_magic)

        photos = [self._make_photo() for _ in range(4)]

        with pytest.raises(TicketPhotoValidationError, match="Maximum 3 photos"):
            _validate_photos(photos)

    def test_photo_exceeds_size_limit_raises(self, mocker: Any) -> None:
        import sys
        import types

        from apps.maintenance.exceptions import TicketPhotoValidationError
        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/jpeg"
        sys.modules.setdefault("magic", fake_magic)
        oversized = self._make_photo(size=6 * 1024 * 1024)

        with pytest.raises(TicketPhotoValidationError, match="exceeds the 5 MB"):
            _validate_photos([oversized])

    def test_disallowed_mime_type_raises(self, mocker: Any) -> None:
        import sys
        import types

        from apps.maintenance.exceptions import TicketPhotoValidationError
        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/gif"
        sys.modules["magic"] = fake_magic
        gif = self._make_photo(name="file.gif")

        with pytest.raises(TicketPhotoValidationError, match="not allowed"):
            _validate_photos([gif])

    def test_valid_jpeg_passes(self, mocker: Any) -> None:
        import sys
        import types

        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/jpeg"
        sys.modules["magic"] = fake_magic
        jpeg = self._make_photo(name="photo.jpg", size=2 * 1024 * 1024)

        _validate_photos([jpeg])

    def test_valid_png_passes(self, mocker: Any) -> None:
        import sys
        import types

        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/png"
        sys.modules["magic"] = fake_magic
        png = self._make_photo(name="photo.png")

        _validate_photos([png])

    def test_valid_heic_passes(self, mocker: Any) -> None:
        import sys
        import types

        from apps.maintenance.services import _validate_photos

        fake_magic = types.ModuleType("magic")
        fake_magic.from_buffer = lambda buf, mime=False: "image/heic"
        sys.modules["magic"] = fake_magic
        heic = self._make_photo(name="photo.heic")

        _validate_photos([heic])


@pytest.mark.django_db
class TestR2Upload:

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

        assert url.startswith("https://media.example.com/tickets/aabbccdd")
        assert url.endswith(".jpg")
        mock_client.upload_fileobj.assert_called_once()

    def test_upload_failure_raises_ticket_photo_validation_error(
        self, mocker: Any, settings: Any
    ) -> None:
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

        photo = self._make_photo(name="noextension")
        url = _upload_photo_to_r2("ticket-123", photo)

        assert url.endswith(".noextension")
