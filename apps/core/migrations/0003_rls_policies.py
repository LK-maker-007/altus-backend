from __future__ import annotations

from django.db import migrations

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

    dependencies = [
        ("core", "0002_initial"),
        ("bookings", "0004_gist_exclusion_constraint_no_overlap"),
        ("community", "0003_initial"),
        ("emergency", "0001_initial"),
        ("facilities", "0001_initial"),
        ("lost_found", "0002_initial"),
        ("maintenance", "0002_initial"),
        ("packages", "0002_initial"),
        ("users", "0001_initial"),
        ("visitors", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="".join(_enable_sql(t) for t in _TENANT_TABLES),
            reverse_sql="".join(_disable_sql(t) for t in _TENANT_TABLES),
        ),
    ]
