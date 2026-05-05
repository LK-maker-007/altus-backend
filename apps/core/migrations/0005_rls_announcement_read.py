from __future__ import annotations

"""
Migration 0005: Add community_announcementread to PostgreSQL Row-Level Security.

WHY this table was missing from migration 0003:
  AnnouncementRead has no direct complex_id FK — it is scoped transitively via
  the announcement FK (announcement.complex == user.complex). The 0003 migration
  covered all ComplexScopedModel subclasses (which have a direct complex_id FK).
  AnnouncementRead uses models.Model directly and relies on FK-level scoping.

  The gap: a platform admin or raw SQL connection can SELECT all read receipts
  across all tenants. This is low-severity (not PII) but inconsistent with the
  security posture of the rest of the system.

  FIX: Use a JOIN-based policy instead of a direct complex_id lookup:
    USING (announcement_id IN (
        SELECT id FROM community_announcement
        WHERE complex_id::text = current_setting('app.current_complex', true)
    ))

  WHY JOIN policy not complex_id:
    AnnouncementRead has no complex_id column. The only way to scope it by tenant
    is to check whether its announcement belongs to the current tenant. This is
    the standard PostgreSQL RLS pattern for join-table isolation.
    Source: PostgreSQL 18 docs §row-security §examples §referencing-other-tables.

  WHY no WITH CHECK policy (USING only):
    Writes to AnnouncementRead are only performed via ORM get_or_create() in
    AnnouncementService.mark_read(). The application layer already validates that
    the announcement belongs to the requesting user's complex (via ComplexScoped
    Manager on Announcement). WITH CHECK on a JOIN subquery would also require a
    separate GRANT on community_announcement to the app role — over-engineering
    for a low-sensitivity table. USING is sufficient.

Source: ADR-012 §Tables covered; audit §LOW §announcementread not in RLS list.
"""

from django.db import migrations

_POLICY_NAME = "complex_isolation"
_GUC_KEY = "app.current_complex"
_TABLE = "community_announcementread"
_PARENT_TABLE = "community_announcement"


def _enable_sql() -> str:
    return (
        f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;\n"
        f"CREATE POLICY {_POLICY_NAME} ON {_TABLE}\n"
        f"    USING (\n"
        f"        announcement_id IN (\n"
        f"            SELECT id FROM {_PARENT_TABLE}\n"
        f"            WHERE complex_id::text = current_setting('{_GUC_KEY}', true)\n"
        f"        )\n"
        f"    );"
    )


def _disable_sql() -> str:
    return f"""
        DROP POLICY IF EXISTS {_POLICY_NAME} ON {_TABLE};
        ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;
        ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY;
    """


class Migration(migrations.Migration):
    """Enable RLS on community_announcementread via JOIN-based policy.

    This migration is a security hardening addition to ADR-012.
    It uses a USING subquery to scope read receipts to the current tenant
    without requiring a direct complex_id column on AnnouncementRead.
    """

    dependencies = [
        ("core", "0004_failed_task_dlq"),
        ("community", "0005_add_announcement_read"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_enable_sql(),
            reverse_sql=_disable_sql(),
        ),
    ]
