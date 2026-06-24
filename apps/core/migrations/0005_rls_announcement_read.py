from __future__ import annotations

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
