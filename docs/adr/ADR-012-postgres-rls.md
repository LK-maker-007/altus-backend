# ADR-012: PostgreSQL Row-Level Security as Second Line of Defence

**Date:** 2026-04-25
**Status:** Accepted
**Deciders:** Engineering (Yali Backend)

---

## Context

Yali is a multi-tenant SaaS platform. Every resident, booking, visitor, package, and maintenance ticket belongs to exactly one residential complex (`complex_id` FK).

Currently, tenant isolation is enforced **only at the application layer** via `ComplexScopedManager`, which adds `WHERE complex_id = :current_complex_id` to every queryset. The ContextVar is set by `ComplexContextMiddleware`.

A Staff-level engineer review identified a critical gap:

> "Application filters are opt-in. One raw SQL query written in a hurry leaks every tenant's data. The DB must be the last line of defence."

Specific failure modes:
1. A developer writes `MyModel.objects.all()` instead of `MyModel.objects.filter(complex_id=...)` in a new view — leaks all tenants' data.
2. A third-party Django package (e.g., DRF filter backends) makes a raw query without knowing about our tenant model.
3. A Celery task accidentally uses `.objects.all()` instead of `.unscoped.filter(complex_id=task_complex_id)`.
4. A Django Admin action uses raw SQL or a queryset that bypasses `ComplexScopedManager`.

---

## Decision

Implement **PostgreSQL Row-Level Security (RLS)** on all 10 tenant-scoped tables as a second, independent line of defence. The application-layer manager remains as the **first** line (performance: avoids DB round-trip for policy evaluation). RLS is the **last** line (security: enforced by the DB regardless of ORM usage).

### Policy design

```sql
-- Per table (example: bookings_booking)
ALTER TABLE bookings_booking ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings_booking FORCE ROW LEVEL SECURITY;

CREATE POLICY complex_isolation ON bookings_booking
  USING (complex_id::text = current_setting('app.current_complex', true))
  WITH CHECK (complex_id::text = current_setting('app.current_complex', true));
```

The GUC `app.current_complex` is set by the existing `ComplexContextMiddleware` via `SET LOCAL app.current_complex = %s` inside a `transaction.atomic()` block.

`current_setting('app.current_complex', true)` — the `true` (missing_ok) argument returns NULL (not an error) when the GUC is not set. This makes the policy **fail-closed**: no GUC → `complex_id = NULL` → false → zero rows.

### Bypass mechanism

- **Migrations:** Run as superuser with `BYPASSRLS`. No GUC is set during migrations. The `FORCE ROW LEVEL SECURITY` clause applies only to non-superuser connections. Migrations can CREATE/ALTER tables freely.
- **Celery tasks:** Tasks that need cross-tenant reads (e.g., expiry jobs) use `.unscoped.filter(complex_id=...)` explicitly. The superuser DB role used in tests bypasses RLS.
- **Platform admin:** Django Admin staff users have their `complex_id` set via `ComplexContextMiddleware` fallback 2 (session auth path). Platform superadmins (no `complex_id`) connect with a separate DB role.

### Tables covered

| Table | RLS Policy |
|---|---|
| `bookings_booking` | `complex_isolation` |
| `community_announcement` | `complex_isolation` |
| `core_unit` | `complex_isolation` |
| `emergency_emergencycontact` | `complex_isolation` |
| `facilities_facility` | `complex_isolation` |
| `lost_found_lostfoundreport` | `complex_isolation` |
| `maintenance_maintenanceticket` | `complex_isolation` |
| `packages_package` | `complex_isolation` |
| `users_user` | `complex_isolation` |
| `visitors_visitor` | `complex_isolation` |

Not covered (correct): `core_complex`, `core_plan`, `core_subscription` — platform-level tables, no per-tenant isolation semantics.

---

## Consequences

### Positive
- **Fail-closed security:** A forgotten `.filter()` returns zero rows, not leaked data.
- **Defence in depth:** Two independent layers. An attacker who bypasses the ORM layer still hits DB enforcement.
- **Audit trail:** RLS policies are visible in `pg_policies` — auditable by security tools.
- **No application changes:** The middleware already sets the correct GUC. Only a migration is needed.

### Negative / Risks
- **Connection pooling:** Must use `SET LOCAL` (not `SET`) — already implemented correctly.
- **Test isolation:** Tests connect as superuser in CI → RLS is bypassed in most tests. Dedicated RLS tests must use a non-superuser role.
- **Performance:** Adds implicit `WHERE` clause to every query. Mitigated by existing `complex_id` index on all affected tables.
- **Migration superuser bypass:** Acceptable — migrations are run by ops, not application users.

---

## Source verification (per research-rule.md)

| Source | Type | Date |
|---|---|---|
| https://www.postgresql.org/docs/current/ddl-rowsecurity.html | Official PG 18 docs | Current |
| rivestack.io — RLS + pgbouncer transaction mode | Dated 2025 article | 2025 |
| imfeld.dev — SET LOCAL + connection pooling | Dated 2025 article | 2025 |
| alasco.tech — Django + RLS production | Dated 2025 article | 2025 |
