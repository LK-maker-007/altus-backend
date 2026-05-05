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

# Photo constraints — per api-contract §7
_MAX_PHOTOS = 3
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/heic"})

# ── State Machine — valid ticket status transitions ────────────────────────────
# WHY explicit transition map (not django-fsm):
#   django-fsm adds a dependency and requires model-level decorators which
#   violates ADR-010 (no business logic in models). An explicit dict at the
#   service layer is testable, readable, and dependency-free.
#   Pattern sourced from Stripe's state machine conventions.
#
# Valid transitions:
#   OPEN → IN_PROGRESS (technician picks up the ticket)
#   OPEN → CLOSED     (complex admin closes invalid request)
#   IN_PROGRESS → RESOLVED  (technician marks work done)
#   IN_PROGRESS → OPEN      (unassigned — kick back to queue)
#   RESOLVED → CLOSED       (admin confirms resolution)
#   CLOSED = terminal state, no further transitions allowed
_VALID_TICKET_TRANSITIONS: dict[str, frozenset[str]] = {
    TicketStatus.OPEN: frozenset({TicketStatus.IN_PROGRESS, TicketStatus.CLOSED}),
    TicketStatus.IN_PROGRESS: frozenset({TicketStatus.RESOLVED, TicketStatus.OPEN}),
    TicketStatus.RESOLVED: frozenset({TicketStatus.CLOSED}),
    TicketStatus.CLOSED: frozenset(),  # terminal — no exit
}


def _get_r2_client() -> S3Client:
    """Return a boto3 S3 client configured for Cloudflare R2.

    Return type is S3Client from boto3-stubs[s3] (TYPE_CHECKING only).
    boto3.client("s3", ...) is overloaded in mypy_boto3_s3 to return S3Client
    when the literal "s3" service name is passed — no cast() needed.
    """
    import boto3  # production-only — deferred to avoid ImportError in dev venv

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _validate_photos(photos: list[UploadedFile]) -> None:
    """Validate MIME type, size, and count for uploaded photos.

    Raises TicketPhotoValidationError on any constraint violation.
    Uses python-magic (production.txt) for MIME detection — not the
    browser-declared content_type which can be spoofed.
    """
    import magic  # python-magic — available in production.txt

    if len(photos) > _MAX_PHOTOS:
        raise TicketPhotoValidationError(
            detail=f"Maximum {_MAX_PHOTOS} photos allowed per ticket."
        )

    for photo in photos:
        if photo.size and photo.size > _MAX_PHOTO_BYTES:
            raise TicketPhotoValidationError(
                detail=f"Photo '{photo.name}' exceeds the 5 MB limit."
            )
        # Read first 2048 bytes for MIME sniffing — reset pointer after
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
    """Upload a single photo to Cloudflare R2, return the public URL.

    Object key: tickets/{ticket_id}/{uuid4}.{ext}
    """
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
    except Exception as exc:  # botocore BotoCoreError/ClientError — deferred import
        logger.error("r2_upload_failed", object_key=object_key, error=str(exc))
        raise TicketPhotoValidationError(
            detail="Photo upload failed. Please try again."
        ) from exc

    return f"{settings.R2_PUBLIC_URL}/{object_key}"


def _delete_orphaned_r2_photos(photo_urls: list[str]) -> None:
    """Best-effort deletion of R2 objects that have no corresponding DB row.

    Called in create_ticket() failure paths to compensate for photos that were
    uploaded to R2 before the transaction.atomic() block failed.

    WHY best-effort (no raise on error):
      A deletion failure is less harmful than leaving orphaned objects — they
      accumulate silently but do not corrupt data. The caller has already failed
      and must re-raise the original exception. Raising from a cleanup routine
      would mask the root cause in Sentry/structlog.
      Source: audit §Significant §Photo Upload Before Atomic Block.
    """
    if not photo_urls:
        return

    try:
        client = _get_r2_client()
        for url in photo_urls:
            # Reconstruct the object key from the public URL.
            # R2_PUBLIC_URL + "/" + object_key = full URL
            object_key = url.removeprefix(f"{settings.R2_PUBLIC_URL}/")
            client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=object_key)
            logger.info("r2_orphan_deleted", object_key=object_key)
    except Exception as exc:  # botocore BotoCoreError/ClientError — deferred import
        # BLE001: broad-except intentional — cleanup must never mask the
        # caller's exception.
        logger.error(
            "r2_orphan_delete_failed",
            photo_count=len(photo_urls),
            error=str(exc),
        )


class MaintenanceService:
    """Business logic for maintenance ticket creation and retrieval.

    All methods are stateless @staticmethod — class is a namespace (ADR-010).
    """

    @staticmethod
    def create_ticket(
        resident: User,
        category: str,
        description: str,
        photos: list[UploadedFile],
        client_idempotency_key: uuid.UUID | None = None,
        queued_at: str | None = None,
    ) -> MaintenanceTicket:
        """Create a maintenance ticket with optional photo upload (US-025).

        Idempotency: if client_idempotency_key is provided, the first successful
        create returns the new ticket; concurrent retries with the same key catch
        IntegrityError on the unique constraint and return the already-created ticket.

        WHY IntegrityError catch instead of pre-check (Google review §TOCTOU):
          The previous pattern did a filter().first() outside any transaction, then
          proceeded to create() if None. Two concurrent requests with the same key
          both pass the filter (both see None), both reach create(), one succeeds and
          one raises IntegrityError. The correct pattern is:
            1. Attempt create() inside transaction.atomic()
            2. Catch IntegrityError on the unique constraint violation
            3. Re-fetch and return the winner's ticket
          This is atomic by construction — no window between check and act.
        """
        from apps.core.models import Unit

        # Validate + upload photos before entering the atomic block.
        # If upload fails, no partial ticket is written to the DB.
        if photos:
            _validate_photos(photos)

        # Resolve the resident's unit — required FK on MaintenanceTicket
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
            # Concurrent request with the same client_idempotency_key already won.
            # Re-fetch and return the existing ticket (idempotent response).
            # WHY delete photo_urls: this request's ticket_id was never committed to
            # the DB. The winner uploaded their own photos under their ticket_id.
            # Our uploads are orphaned — delete them now.
            # Source: audit §Significant §Photo Upload Before Atomic Block.
            _delete_orphaned_r2_photos(photo_urls)
            if client_idempotency_key is None:
                raise  # IntegrityError on a non-idempotency field — re-raise
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
            # WHY broad except here only (noqa: BLE001):
            #   Any non-IntegrityError DB failure (connection drop, constraint not
            #   related to idempotency, etc.) leaves photo_urls permanently orphaned
            #   in R2 with no corresponding ticket row. Delete them before re-raising.
            #   This is the ONLY place a broad except is acceptable —
            #   it always re-raises.
            #   Source: audit §Significant §Photo Upload Before Atomic Block.
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
    def transition_ticket_status(
        ticket_id: str,
        new_status: str,
        actor: User,
    ) -> MaintenanceTicket:
        """Transition a maintenance ticket to a new status (state machine enforced).

        Raises TicketNotFoundError if the ticket doesn't exist.
        Raises TicketAccessDeniedError if the transition is invalid.

        WHY select_for_update(nowait=True) INSIDE atomic():
          select_for_update() requires an active transaction to hold the row lock.
          Calling it outside atomic() raises TransactionManagementError in Celery
          tasks, management commands, and test teardown — anywhere without
          ATOMIC_REQUESTS. Only production view calls are protected by ATOMIC_REQUESTS;
          this service must be callable from any context.
          Pattern: identical to BookingService.create_hold()
          in apps/bookings/services.py.
        """
        from django.utils import timezone

        try:
            with transaction.atomic():
                # Lock the ticket row for the duration of this transaction.
                # nowait=True: raise OperationalError immediately if already locked
                # (concurrent transition in progress) rather than blocking the thread.
                ticket = MaintenanceTicket.objects.select_for_update(nowait=True).get(
                    id=ticket_id
                )

                current_status = ticket.status
                allowed_next = _VALID_TICKET_TRANSITIONS.get(
                    current_status, frozenset()
                )

                if new_status not in allowed_next:
                    allowed_display = sorted(allowed_next) or "none (terminal state)"
                    raise TicketAccessDeniedError(
                        detail=(
                            f"Cannot transition ticket from '{current_status}'"
                            f" to '{new_status}'. Allowed: {allowed_display}."
                        )
                    )

                ticket.status = new_status
                if new_status == TicketStatus.RESOLVED:
                    ticket.resolved_at = timezone.now()
                ticket.save(update_fields=["status", "resolved_at"])

                TicketStatusHistory.objects.create(
                    ticket=ticket,
                    status=new_status,
                    changed_by=actor,
                )

        except MaintenanceTicket.DoesNotExist:
            raise TicketNotFoundError() from None

        logger.info(
            "ticket_status_transitioned",
            ticket_id=ticket_id,
            from_status=current_status,
            to_status=new_status,
            actor_id=str(actor.pk),
        )
        return ticket

    @staticmethod
    def get_ticket_detail(ticket_id: str, resident: User) -> MaintenanceTicket:
        """Fetch ticket detail for the resident — ownership enforced (US-027).

        Raises TicketNotFoundError if ticket does not exist in this complex.
        Raises TicketAccessDeniedError if ticket belongs to another resident.
        """
        try:
            ticket = MaintenanceTicket.objects.prefetch_related(
                "photos", "status_history"
            ).get(id=ticket_id)
        except MaintenanceTicket.DoesNotExist:
            raise TicketNotFoundError() from None

        if ticket.raised_by_id != resident.pk:
            raise TicketAccessDeniedError()

        return ticket
