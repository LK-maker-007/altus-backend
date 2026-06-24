from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction

from apps.maintenance.exceptions import (
    TicketAccessDeniedError,
    TicketNotFoundError,
    TicketPhotoValidationError,
)
from apps.maintenance.models import (
    MaintenanceTicket,
    TicketPhoto,
    TicketStatus,
    TicketStatusHistory,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

    from apps.users.models import User

logger = structlog.get_logger(__name__)

_MAX_PHOTOS = 3
_MAX_PHOTO_BYTES = 5 * 1024 * 1024
_ALLOWED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/heic"})


def _get_r2_client() -> S3Client:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _validate_photos(photos: list[UploadedFile]) -> None:
    import magic

    if len(photos) > _MAX_PHOTOS:
        raise TicketPhotoValidationError(
            detail=f"Maximum {_MAX_PHOTOS} photos allowed per ticket."
        )

    for photo in photos:
        if photo.size and photo.size > _MAX_PHOTO_BYTES:
            raise TicketPhotoValidationError(
                detail=f"Photo '{photo.name}' exceeds the 5 MB limit."
            )
        header = photo.read(2048)
        photo.seek(0)
        detected_mime = magic.from_buffer(header, mime=True)
        if detected_mime not in _ALLOWED_MIME_TYPES:
            raise TicketPhotoValidationError(
                detail=(
                    f"File type '{detected_mime}' not allowed."
                    " Allowed types: JPEG, PNG, HEIC."
                )
            )


def _upload_photo_to_r2(ticket_id: str, photo: UploadedFile) -> str:
    ext = (photo.name or "photo").rsplit(".", 1)[-1].lower() if photo.name else "jpg"
    object_key = f"tickets/{ticket_id}/{uuid.uuid4()}.{ext}"

    client = _get_r2_client()
    try:
        client.upload_fileobj(
            photo,
            settings.R2_BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": photo.content_type or "image/jpeg"},
        )
    except Exception as exc:
        logger.error("r2_upload_failed", object_key=object_key, error=str(exc))
        raise TicketPhotoValidationError(
            detail="Photo upload failed. Please try again."
        ) from exc

    return f"{settings.R2_PUBLIC_URL}/{object_key}"


def _delete_orphaned_r2_photos(photo_urls: list[str]) -> None:
    if not photo_urls:
        return

    try:
        client = _get_r2_client()
        for url in photo_urls:
            object_key = url.removeprefix(f"{settings.R2_PUBLIC_URL}/")
            client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=object_key)
            logger.info("r2_orphan_deleted", object_key=object_key)
    except Exception as exc:
        logger.error(
            "r2_orphan_delete_failed",
            photo_count=len(photo_urls),
            error=str(exc),
        )


class MaintenanceService:

    @staticmethod
    def create_ticket(
        resident: User,
        category: str,
        description: str,
        photos: list[UploadedFile],
        client_idempotency_key: uuid.UUID | None = None,
        queued_at: str | None = None,
    ) -> MaintenanceTicket:
        from apps.core.models import Unit

        if photos:
            _validate_photos(photos)

        try:
            unit = Unit.objects.get(registered_resident=resident)
        except Unit.DoesNotExist:
            raise TicketNotFoundError(
                detail="No unit is linked to your account."
            ) from None

        ticket_id = str(uuid.uuid4())
        photo_urls: list[str] = []
        for photo in photos:
            url = _upload_photo_to_r2(ticket_id, photo)
            photo_urls.append(url)

        try:
            with transaction.atomic():
                ticket = MaintenanceTicket.objects.create(
                    id=ticket_id,
                    complex_id=str(resident.complex_id),
                    unit=unit,
                    raised_by=resident,
                    category=category,
                    title=description[:200],
                    description=description,
                    status=TicketStatus.OPEN,
                    client_idempotency_key=client_idempotency_key,
                    queued_at=queued_at,
                )

                TicketStatusHistory.objects.create(
                    ticket=ticket,
                    status=TicketStatus.OPEN,
                    changed_by=None,
                )

                for url in photo_urls:
                    TicketPhoto.objects.create(ticket=ticket, photo_url=url)

        except IntegrityError:
            _delete_orphaned_r2_photos(photo_urls)
            if client_idempotency_key is None:
                raise
            ticket = MaintenanceTicket.objects.prefetch_related(
                "photos", "status_history"
            ).get(client_idempotency_key=client_idempotency_key)
            logger.info(
                "ticket_create_idempotent",
                ticket_id=str(ticket.id),
                key=str(client_idempotency_key),
            )
            return ticket
        except Exception:
            _delete_orphaned_r2_photos(photo_urls)
            raise

        logger.info(
            "ticket_created",
            ticket_id=str(ticket.id),
            category=category,
            photo_count=len(photo_urls),
        )
        return ticket

    @staticmethod
    def get_ticket_detail(ticket_id: str, resident: User) -> MaintenanceTicket:
        try:
            ticket = MaintenanceTicket.objects.prefetch_related(
                "photos", "status_history"
            ).get(id=ticket_id)
        except MaintenanceTicket.DoesNotExist:
            raise TicketNotFoundError() from None

        if ticket.raised_by_id != resident.pk:
            raise TicketAccessDeniedError()

        return ticket
