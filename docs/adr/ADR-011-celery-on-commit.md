# ADR-011: Celery Task Dispatch via `transaction.on_commit()`

**Date:** 2026-04-20
**Status:** Accepted
**Deciders:** Engineering (Yali Backend)

---

## Context

Celery tasks are dispatched from service methods after a database write succeeds. The canonical naive pattern is:

```python
# WRONG — task dispatched before DB commit
def confirm_hold(booking_id):
    booking.status = "confirmed"
    booking.save()
    send_booking_reminder.apply_async(args=(str(booking.id),))  # ← races the commit
```

**The race condition:** `apply_async()` publishes a message to the broker (RabbitMQ/Redis) immediately. The Celery worker may pick it up and try to fetch `Booking.objects.get(id=booking_id)` **before** the caller's database transaction has committed. The worker gets `Booking.DoesNotExist` and either retries indefinitely or silently fails.

This race is especially dangerous with `ATOMIC_REQUESTS = True` (production setting) because the entire request runs in a single transaction — any `apply_async()` inside a view handler fires before the transaction commits.

---

## Decision

**All `apply_async()` calls inside a `transaction.atomic()` block MUST be wrapped in `transaction.on_commit()`.**

```python
# CORRECT pattern
with transaction.atomic():
    booking.status = "confirmed"
    booking.save(update_fields=["status", "updated_at"])

    transaction.on_commit(
        lambda: send_booking_reminder.apply_async(
            args=(str(booking.id), str(booking.complex_id)),
            eta=booking.slot_start - timedelta(minutes=30),
        )
    )
```

### How `transaction.on_commit()` Works

- **Inside `transaction.atomic()`:** Callback is queued. It fires exactly once, after the outermost transaction commits successfully.
- **On rollback:** Callback is discarded. The Celery task is never published. No orphan tasks.
- **Nested `transaction.atomic()` (savepoints):** Callback fires after the outermost commit, not after the savepoint. This is the correct behaviour — the data must be durably committed before the worker can access it.
- **With `ATOMIC_REQUESTS = True`:** The entire request is a transaction. `on_commit()` fires after Django finishes writing the response and commits. The Celery worker can safely fetch the record.

### Deferred Task Imports

All task imports inside service methods use deferred local imports to break the circular dependency `services → tasks → services`:

```python
# Inside the service method, inside transaction.on_commit callback:
from apps.bookings.tasks import send_booking_reminder  # deferred — avoids circular import
```

This is the standard Django circular-import mitigation. The import cost is a one-time module load cached by Python's import system.

---

## Consequences

**Positive:**
- Zero "task sees missing record" race conditions.
- If the transaction rolls back (e.g., due to a GiST constraint violation), the Celery task is never published. No phantom notifications.
- Compatible with `ATOMIC_REQUESTS = True` in production.
- `countdown` and `eta` parameters on `apply_async()` work correctly — the task is published after commit, so the countdown starts from the correct time.

**Negative:**
- Tasks are not published in test environments unless `@pytest.mark.django_db(transaction=True)` is used (savepoints do not trigger `on_commit`). Tests mock `transaction.on_commit` or use `transaction=True`.
- Lambda closures capture variables by reference — all variables used in the lambda must be stable after the `on_commit` registration. UUID strings (`str(booking.id)`) are preferred over ORM objects to avoid stale reference bugs.

---

## Active Call Sites (2026-04-20)

| Service | Task | Pattern |
|---|---|---|
| `BookingService.create_hold()` | `expire_booking_hold` | countdown=5min |
| `BookingService.confirm_hold()` | `send_booking_reminder` | eta=slot_start-30min |
| `VisitorService.mark_arrived()` | `notify_visitor_arrived` | immediate |
| `PackageService.log_package()` | `notify_package_arrived` | immediate |
| `MaintenanceService.create_ticket()` | `notify_maintenance_created` | immediate |
| `MaintenanceService.update_ticket_status()` | `notify_maintenance_updated` | immediate |

---

## References

- [Django docs — `transaction.on_commit()`](https://docs.djangoproject.com/en/stable/topics/db/transactions/#performing-actions-after-commit)
- [Celery docs — Task best practices](https://docs.celeryq.dev/en/stable/userguide/tasks.html#avoid-launching-synchronous-subtasks)
- ADR-010: Service Layer — defines where `apply_async()` calls originate
