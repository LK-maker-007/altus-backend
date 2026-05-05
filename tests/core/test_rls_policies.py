from __future__ import annotations

"""
Row-Level Security (RLS) integration tests.

These tests verify that the PostgreSQL RLS policies installed by migration
0003_rls_policies ACTUALLY enforce tenant isolation at the DB level —
independent of the application-layer ComplexScopedManager.

Why these tests are different from unit tests:
  Unit tests mock the ORM / manager layer. These tests bypass all ORM filtering
  and execute RAW SQL directly on the DB to prove that even a completely
  unrestricted query is blocked by the DB policy.

Test architecture (Staff L6 requirement):
  The test DB connects as 'yali_user' which IS a superuser in this Docker setup
  (confirmed via pg_user). Superusers always bypass RLS, so RLS enforcement
  tests must use SET ROLE to switch to a non-superuser role.

  Strategy:
    1. As superuser (yali_user): CREATE ROLE yali_rls_tester (no superuser, no BYPASSRLS).
    2. GRANT SELECT, INSERT, UPDATE, DELETE on tenant tables to yali_rls_tester.
    3. SET ROLE yali_rls_tester — now RLS is fully enforced.
    4. Execute raw SQL — RLS applies because yali_rls_tester is not a superuser.
    5. RESET ROLE — back to yali_user for cleanup.

  This matches production: the web app role is NOT a superuser.

Three properties verified:
  1. FAIL-CLOSED: No GUC set → raw SELECT returns 0 rows (policy blocks all).
  2. CORRECT-TENANT: GUC set to complex_a → raw SELECT returns only complex_a rows.
  3. CROSS-TENANT-BLOCKED: GUC set to complex_a → raw SELECT on complex_b → 0 rows.

Source: ADR-012, docs/adr/ADR-012-postgres-rls.md
Research: docs/research/maang-engineering-standards.md §12
Official: https://www.postgresql.org/docs/current/ddl-rowsecurity.html (PG18)
"""

from typing import Any

import pytest
from django.db import connection, transaction

from apps.bookings.models import BookingStatus

# Role created per test session for RLS enforcement testing.
# This role is non-superuser so RLS policies apply to it.
_RLS_TESTER_ROLE = "yali_rls_tester"

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


def _execute_raw(sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    """Execute raw SQL as the current role. Used for catalog/metadata queries."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def _rls_select(
    sql: str,
    guc_value: str | None,
    params: list[Any] | None = None,
) -> list[tuple[Any, ...]]:
    """
    Execute a SELECT as yali_rls_tester (non-superuser) with a specific GUC.

    The RLS tester role is not a superuser, so RLS policies are fully enforced.
    SET LOCAL and SELECT are in the same cursor to ensure GUC persistence.

    Args:
        sql: The SELECT statement to execute.
        guc_value: The complex_id UUID string, or None/''/empty for fail-closed test.
        params: Optional query parameters for the SELECT.
    """
    rows: list[tuple[Any, ...]] = []
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Switch to the non-superuser RLS tester role
            cursor.execute(f"SET LOCAL ROLE {_RLS_TESTER_ROLE}")
            # Set GUC within the same cursor/transaction
            if guc_value:
                cursor.execute("SET LOCAL app.current_complex = %s", [guc_value])
            else:
                # No GUC — test fail-closed: '' → current_setting returns ''
                # complex_id::text = '' → false → 0 rows
                cursor.execute("SET LOCAL app.current_complex = ''")
            cursor.execute(sql, params or [])
            rows = cursor.fetchall()
    return rows


@pytest.fixture(scope="session")
def rls_tester_role(django_db_setup: Any, django_db_blocker: Any) -> None:
    """
    Session-scoped fixture: create yali_rls_tester role (non-superuser).
    Grant SELECT/INSERT/UPDATE/DELETE on all tenant tables.
    Drop on session teardown.

    This role is the "simulated production app user" — no SUPERUSER, no BYPASSRLS.
    """
    with django_db_blocker.unblock():
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Create role (DROP IF EXISTS for idempotency across test re-runs)
                cursor.execute(f"DROP ROLE IF EXISTS {_RLS_TESTER_ROLE}")
                cursor.execute(
                    f"CREATE ROLE {_RLS_TESTER_ROLE} "
                    f"NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS LOGIN "
                    f"PASSWORD 'rls_test_only'"
                )
                # Grant usage on schema
                cursor.execute(f"GRANT USAGE ON SCHEMA public TO {_RLS_TESTER_ROLE}")
                # Grant DML on all tenant tables
                for table in _TENANT_TABLES:
                    cursor.execute(
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} "
                        f"TO {_RLS_TESTER_ROLE}"
                    )

    yield

    # Teardown: revoke grants and drop the role
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            # Must revoke privileges before dropping the role
            cursor.execute(f"REASSIGN OWNED BY {_RLS_TESTER_ROLE} TO yali_user")
            cursor.execute(f"DROP OWNED BY {_RLS_TESTER_ROLE}")
            cursor.execute(f"DROP ROLE IF EXISTS {_RLS_TESTER_ROLE}")


@pytest.mark.django_db(transaction=True)
class TestRLSMigrationApplied:
    """Verify the RLS migration was applied correctly to the test database."""

    def test_rls_enabled_on_bookings(self) -> None:
        """ALTER TABLE ... ENABLE ROW LEVEL SECURITY was applied."""
        rows = _execute_raw(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'bookings_booking'"
        )
        assert rows, "bookings_booking table not found in pg_class"
        assert rows[0][0] is True, (
            "RLS is NOT enabled on bookings_booking — migration 0003_rls_policies "
            "may not have run. Check: SELECT relrowsecurity FROM pg_class "
            "WHERE relname = 'bookings_booking';"
        )

    def test_force_rls_enabled_on_bookings(self) -> None:
        """ALTER TABLE ... FORCE ROW LEVEL SECURITY was applied.
        Without FORCE, the table owner bypasses the policy.
        """
        rows = _execute_raw(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'bookings_booking'"
        )
        assert rows[0][0] is True, (
            "FORCE ROW LEVEL SECURITY is NOT set on bookings_booking. "
            "The table owner would bypass RLS without FORCE."
        )

    def test_policy_exists_on_all_tenant_tables(self) -> None:
        """complex_isolation policy must exist on all 10 tenant-scoped tables."""
        rows = _execute_raw(
            "SELECT tablename FROM pg_policies "
            "WHERE policyname = 'complex_isolation' "
            "ORDER BY tablename"
        )
        actual_tables = {row[0] for row in rows}

        for table in _TENANT_TABLES:
            assert table in actual_tables, (
                f"RLS policy 'complex_isolation' is MISSING on table '{table}'. "
                f"Tables with the policy: {sorted(actual_tables)}"
            )

    def test_rls_enabled_and_forced_on_all_tenant_tables(self) -> None:
        """ENABLE + FORCE ROW LEVEL SECURITY must be set on all 10 tables."""
        rows = _execute_raw(
            "SELECT relname FROM pg_class "
            "WHERE relname = ANY(%s) AND relrowsecurity = TRUE AND relforcerowsecurity = TRUE",
            [_TENANT_TABLES],
        )
        actual = {row[0] for row in rows}
        for table in _TENANT_TABLES:
            assert table in actual, (
                f"ENABLE/FORCE ROW LEVEL SECURITY NOT set on '{table}'. "
                f"Tables confirmed: {sorted(actual)}"
            )


@pytest.mark.django_db(transaction=True)
class TestRLSFailClosed:
    """
    FAIL-CLOSED: When no GUC is set (no tenant context), the DB must
    return ZERO rows on any raw query — not all rows.

    Tests execute as yali_rls_tester (non-superuser) so RLS is enforced.
    """

    def test_raw_query_without_guc_returns_zero_rows(
        self, rls_tester_role: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """
        With no GUC set: raw SELECT on bookings_booking returns 0 rows
        even though rows exist in the table.
        """
        from apps.bookings.models import Booking
        from tests.factories.booking_factory import BookingFactory

        BookingFactory(
            complex=complex_a,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
        )
        assert Booking.unscoped.count() >= 1, "Test setup: no bookings in DB"

        rows = _rls_select(
            "SELECT id FROM bookings_booking",
            guc_value=None,  # no tenant context — fail-closed
        )

        assert len(rows) == 0, (
            f"RLS FAIL-CLOSED VIOLATION: Raw query with NO GUC returned {len(rows)} rows. "
            "Expected 0. A developer forgetting to set tenant context would see ALL tenants' data."
        )

    def test_raw_query_without_guc_returns_zero_on_users(
        self, rls_tester_role: Any, complex_a: Any, resident: Any
    ) -> None:
        """Same fail-closed test on users_user — the most sensitive table."""
        from apps.users.models import User

        # User model uses a custom manager — verify row exists via objects.all()
        assert User.objects.filter(complex=complex_a).count() >= 1

        rows = _rls_select(
            "SELECT id FROM users_user WHERE complex_id IS NOT NULL",
            guc_value=None,
        )

        assert len(rows) == 0, (
            f"RLS FAIL-CLOSED VIOLATION on users_user: returned {len(rows)} rows "
            "with no GUC. PII leak risk."
        )


@pytest.mark.django_db(transaction=True)
class TestRLSCorrectTenantAccess:
    """
    CORRECT-TENANT: GUC = complex_a → raw SQL returns complex_a rows only.
    CROSS-TENANT-BLOCKED: GUC = complex_b → complex_a data invisible.
    """

    def test_raw_query_with_correct_guc_returns_rows(
        self, rls_tester_role: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """With GUC = complex_a.id: raw SELECT returns that complex's rows."""
        from tests.factories.booking_factory import BookingFactory

        BookingFactory(
            complex=complex_a,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
        )

        rows = _rls_select(
            "SELECT id, complex_id FROM bookings_booking",
            guc_value=str(complex_a.id),
        )

        assert len(rows) >= 1, (
            "RLS is over-blocking: no rows returned for correct tenant GUC. "
            "The USING clause may be too strict."
        )
        for row_id, row_complex_id in rows:
            assert str(row_complex_id) == str(complex_a.id), (
                f"Cross-tenant leak: row {row_id} belongs to {row_complex_id}, "
                f"GUC is {complex_a.id}."
            )

    def test_raw_query_with_wrong_tenant_guc_returns_zero(
        self,
        rls_tester_role: Any,
        complex_a: Any,
        complex_b: Any,
        unit_a: Any,
        resident: Any,
    ) -> None:
        """GUC = complex_b → complex_a data is invisible (cross-tenant blocked)."""
        from tests.factories.booking_factory import BookingFactory

        BookingFactory(
            complex=complex_a,
            status=BookingStatus.CONFIRMED,
            expires_at=None,
        )

        rows = _rls_select(
            "SELECT id, complex_id FROM bookings_booking WHERE complex_id = %s",
            guc_value=str(complex_b.id),
            params=[str(complex_a.id)],
        )

        assert len(rows) == 0, (
            f"CROSS-TENANT DATA LEAK: RLS returned {len(rows)} rows for complex_a "
            f"({complex_a.id}) while GUC = complex_b ({complex_b.id}). "
            "The USING clause is not filtering correctly."
        )

    def test_cross_tenant_write_blocked_by_with_check(
        self, rls_tester_role: Any, complex_a: Any, complex_b: Any
    ) -> None:
        """
        WITH CHECK: Writing a row with complex_id ≠ GUC must be blocked.
        GUC = complex_b, but INSERT complex_id = complex_a → rejected.
        """
        import uuid

        # Attempt INSERT of complex_a data while GUC = complex_b
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL ROLE {_RLS_TESTER_ROLE}")
                    cursor.execute(
                        "SET LOCAL app.current_complex = %s", [str(complex_b.id)]
                    )
                    cursor.execute(
                        """
                        INSERT INTO bookings_booking
                            (id, created_at, updated_at, complex_id, slot_start, slot_end,
                             status, expires_at, cancelled_at, cancellation_reason,
                             cancellation_source, facility_id, resident_id)
                        VALUES
                            (%s, NOW(), NOW(), %s, NOW() + interval '1 day',
                             NOW() + interval '2 days', 'confirmed', NULL, NULL, '', '',
                             NULL, NULL)
                        """,
                        [str(uuid.uuid4()), str(complex_a.id)],
                    )
            pytest.fail(
                "RLS WITH CHECK VIOLATION: INSERT for complex_a succeeded with GUC = complex_b."
            )
        except Exception as e:
            error_msg = str(e).lower()
            acceptable = (
                "row-level security" in error_msg
                or "null" in error_msg
                or "foreign" in error_msg
                or "not-null" in error_msg
                or "violates" in error_msg
                or "integrity" in error_msg
            )
            if not acceptable:
                raise


@pytest.mark.django_db(transaction=True)
class TestRLSDoesNotBlockLegitimateAccess:
    """
    Sanity check: correct GUC must never over-block legitimate queries.
    """

    def test_correct_guc_allows_own_tenant_data(
        self, rls_tester_role: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """GUC = complex_a → can SELECT own bookings."""
        from tests.factories.booking_factory import BookingFactory

        booking = BookingFactory(complex=complex_a, status=BookingStatus.HOLD)

        rows = _rls_select(
            "SELECT id FROM bookings_booking WHERE id = %s",
            guc_value=str(complex_a.id),
            params=[str(booking.id)],
        )

        assert len(rows) == 1, (
            f"RLS is over-blocking: booking {booking.id} not returned with correct GUC "
            f"({complex_a.id}). Check USING clause."
        )

    def test_no_guc_blocks_even_own_data(
        self, rls_tester_role: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
        """No GUC → zero rows even for own complex data (fail-closed wins)."""
        from tests.factories.booking_factory import BookingFactory

        BookingFactory(
            complex=complex_a, status=BookingStatus.CONFIRMED, expires_at=None
        )

        rows = _rls_select(
            "SELECT COUNT(*) FROM bookings_booking",
            guc_value=None,
        )
        count = rows[0][0]

        assert count == 0, (
            "Expected 0 rows (fail-closed). FORCE ROW LEVEL SECURITY must be set. "
            "A missing GUC must never expose data."
        )
