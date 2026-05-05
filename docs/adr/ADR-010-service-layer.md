# ADR-010: Stateless Class-Based Service Layer

**Date:** 2026-04-20
**Status:** Accepted
**Deciders:** Engineering (Yali Backend)

---

## Context

Business logic in Django projects tends to accumulate in one of three places:

1. **Fat models** — `model.save()` overrides, model methods that call external APIs
2. **Fat views** — view handlers that contain multi-step DB logic and Celery dispatches
3. **Service modules** — plain Python functions/classes that orchestrate models and external services

Yali's backend serves multiple consumers: a DRF REST API (mobile app), Django Admin, and Celery workers. A decision was needed on where business logic lives and how to keep it accessible to all three consumers without coupling to any single framework.

The critical constraint: **Celery tasks call the same business logic as views**. If business logic lives in DRF views, Celery tasks can't reuse it. If it lives in model.save(), tests become tightly coupled to the ORM lifecycle.

---

## Decision

All business logic above trivial model validation lives in **stateless class-based service modules** (`apps/<domain>/services.py`).

### Rules (enforced by ADR, verified in code review)

1. **Services are framework-agnostic.** Services MUST NOT import from `rest_framework`. They raise domain exceptions (`apps/<domain>/exceptions.py`), not DRF's `PermissionDenied` or `ValidationError`. DRF views may catch domain exceptions — domain exceptions may not depend on DRF.

2. **Services use static methods only.** No instance state. Class is a namespace. Pattern: `class BookingService: @staticmethod def create_hold(...) -> Booking:`. This makes every service method independently callable without instantiation — consistent with how Celery tasks and Django Admin actions call them.

3. **No business logic in `model.save()`.** Model saves use `update_fields` for atomic partial updates. Hooks like `post_save` signals are prohibited — they create hidden coupling that breaks when called from Celery without the full request context.

4. **Views are thin.** Views validate input (serializers), call exactly one service method, and return the response. Zero business logic in views.

5. **Celery tasks are thin.** Tasks unmarshal task arguments (usually UUIDs → fetched objects), call a service method, and log the result. Zero business logic in tasks.

6. **All multi-step DB writes are wrapped in `transaction.atomic()` inside the service method.** See ADR-011 for the Celery + `transaction.on_commit()` dispatch pattern.

### Structure

```
apps/<domain>/
├── exceptions.py   # Domain exceptions (subclass APIException for DRF compat)
├── models.py       # Data structure, constraints, managers
├── serializers.py  # Input/output shapes (DRF layer only)
├── services.py     # Business logic — no DRF, no HTTP concepts
├── tasks.py        # Thin Celery wrappers → service calls
└── views.py        # Thin DRF handlers → serializer → service → Response
```

---

## Consequences

**Positive:**
- Celery tasks, Django Admin actions, and management commands call the same service methods as views — zero duplication.
- Service methods are independently unit-testable without a live HTTP request.
- Domain exceptions carry correct HTTP status codes (via `APIException.status_code`) but contain no DRF logic — they work in any consumer context.
- `update_fields` on every `model.save()` generates targeted `UPDATE` statements — no accidental full-row updates.

**Negative:**
- More files per domain (views.py + services.py vs. just views.py).
- Developers must learn the "no DRF in services" rule and enforce it in review.

---

## Alternatives Considered

| Option | Rejected Reason |
|---|---|
| Fat models (business logic in `model.save()`) | Breaks Celery integration; `save()` hooks run in wrong transaction context |
| Fat views (logic in DRF view methods) | Not reusable from Celery tasks or management commands |
| Repository pattern (explicit data-access layer) | Over-engineered for Django's ORM which already provides QuerySet abstraction |

---

## References

- [HackSoftware Django Styleguide — Services](https://github.com/HackSoftware/Django-Styleguide#services)
- [Two Scoops of Django 3.x — Chapter 8: Best Practices for Class-Based Views](https://www.feldroy.com/books/two-scoops-of-django-3-x)
- Sentry open-source codebase: `src/sentry/services/` pattern
