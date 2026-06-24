"""Take users_user out of RLS.

RLS can't work on the auth table: the login/JWT lookup happens before any tenant
context exists, and platform_admin rows have complex_id NULL, which an equality
policy never matches. Tenant isolation for users is enforced by app design instead
(no user-enumeration endpoint; every cross-user reference goes through a
complex-scoped, RLS-protected domain table).
"""

from __future__ import annotations

from django.db import migrations

_TABLE = "users_user"
_POLICY_NAME = "complex_isolation"
_GUC_KEY = "app.current_complex"

_DISABLE_SQL = f"""
    DROP POLICY IF EXISTS {_POLICY_NAME} ON {_TABLE};
    ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY;
    ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;
"""

_REENABLE_SQL = f"""
    ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;
    CREATE POLICY {_POLICY_NAME} ON {_TABLE}
        USING (complex_id::text = current_setting('{_GUC_KEY}', true))
        WITH CHECK (complex_id::text = current_setting('{_GUC_KEY}', true));
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_rls_announcement_read"),
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=_DISABLE_SQL, reverse_sql=_REENABLE_SQL),
    ]
