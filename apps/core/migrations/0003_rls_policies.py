from __future__ import annotations

"""
Migration 0003: Enable PostgreSQL Row-Level Security on all tenant-scoped tables.

This is a SECURITY migration — no schema change, no data change.
It adds DB-level tenant isolation as a second line of defence behind the
application-layer ComplexScopedManager.

Decision: ADR-012 — docs/adr/ADR-012-postgres-rls.md
Research: docs/research/maang-engineering-standards.md §12

Policy design (per official PostgreSQL 18 docs, verified 2026-04-25):
  USING (complex_id::text = current_setting('app.current_complex', true))

  current_setting('app.current_complex', true):
    - 'true' (missing_ok=True) returns NULL instead of raising an error when
      the GUC is not set. This makes the policy FAIL-CLOSED:
      no GUC → complex_id::text = NULL → false → ZERO rows returned.

  SET LOCAL app.current_complex = %s:
    - Set by ComplexContextMiddleware in transaction.atomic() on every request.
    - SET LOCAL scopes the GUC to the current transaction only.
    - On COMMIT/ROLLBACK the GUC resets automatically — pooled connections are safe.

Migration superuser bypass:
  Migrations run as PostgreSQL superuser (BYPASSRLS attribute).
  FORCE ROW LEVEL SECURITY applies only to NON-superuser roles.
  Therefore migrations can CREATE/ALTER/INSERT without setting the GUC.

Tables covered (all ComplexScopedModel subclasses + users_user):
  bookings_booking, community_announcement, core_unit,
  emergency_emergencycontact, facilities_facility,
  lost_found_lostfoundreport, maintenance_maintenanceticket,
  packages_package, users_user, visitors_visitor

Tables NOT covered (platform-level, no per-tenant semantics):
  core_complex, core_plan, core_subscription
"""

from django.db import migrations

# All tenant-scoped tables. Order does not matter for RLS.
# Verified against django.apps.apps.get_models() 2026-04-25.
_TENANT_TABLES = [
    "bookings_booking",
    "community_announcement",
    "core_unit",
    "emergency_emergencycontact",
    "facilities_facility",
    "lost_found_lostfoundreport",
    "maintenance_maintenanceticket",
    "packages_package",
    "users_user",
    "visitors_visitor",
]

_POLICY_NAME = "complex_isolation"

# GUC key must match ComplexContextMiddleware exactly.
# Change both here and in middleware atomically if renaming.
_GUC_KEY = "app.current_complex"


def _enable_sql(table: str) -> str:
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {_POLICY_NAME} ON {table}
            USING (complex_id::text = current_setting('{_GUC_KEY}', true))
            WITH CHECK (complex_id::text = current_setting('{_GUC_KEY}', true));
    """


def _disable_sql(table: str) -> str:
    return f"""
        DROP POLICY IF EXISTS {_POLICY_NAME} ON {table};
        ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
    """


class Migration(migrations.Migration):
    """
    Enable PostgreSQL RLS on all 10 tenant-scoped tables.

    This migration is idempotent in reverse (DROP POLICY IF EXISTS).
    It is NOT idempotent in forward — running twice will fail with
    'policy already exists'. This is intentional: double-apply is a
    deployment error that should be visible, not silently swallowed.
    """

    dependencies = [
        ("core", "0002_initial"),
        # RLS policies use complex_id which is added by 0002_initial in each app
        # (circular-import-safe migration pattern: 0001 creates the table without FKs,
        #  0002 adds all FK fields including complex_id).
        # Depend on the LATEST migration of each app to guarantee complex_id exists.
        ("bookings", "0004_gist_exclusion_constraint_no_overlap"),
        ("community", "0003_initial"),
        ("emergency", "0001_initial"),  # single-migration app — complex FK in 0001
        ("facilities", "0001_initial"),  # single-migration app
        ("lost_found", "0002_initial"),
        ("maintenance", "0002_initial"),
        ("packages", "0002_initial"),
        ("users", "0001_initial"),  # single-migration app
        ("visitors", "0001_initial"),  # single-migration app
    ]

    operations = [
        migrations.RunSQL(
            sql="".join(_enable_sql(t) for t in _TENANT_TABLES),
            reverse_sql="".join(_disable_sql(t) for t in _TENANT_TABLES),
        ),
    ]
