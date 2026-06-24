from __future__ import annotations

from typing import Any

import pytest
from django.db import connection, transaction

from apps.bookings.models import BookingStatus

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
    "visitors_visitor",
]


def _execute_raw(sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def _rls_select(
    sql: str,
    guc_value: str | None,
    params: list[Any] | None = None,
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL ROLE {_RLS_TESTER_ROLE}")
            if guc_value:
                cursor.execute("SET LOCAL app.current_complex = %s", [guc_value])
            else:
                cursor.execute("SET LOCAL app.current_complex = ''")
            cursor.execute(sql, params or [])
            rows = cursor.fetchall()
    return rows


@pytest.fixture(scope="session")
def rls_tester_role(django_db_setup: Any, django_db_blocker: Any) -> None:
    with django_db_blocker.unblock():
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"DROP ROLE IF EXISTS {_RLS_TESTER_ROLE}")
                cursor.execute(
                    f"CREATE ROLE {_RLS_TESTER_ROLE} "
                    f"NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS LOGIN "
                    f"PASSWORD 'rls_test_only'"
                )
                cursor.execute(f"GRANT USAGE ON SCHEMA public TO {_RLS_TESTER_ROLE}")
                for table in _TENANT_TABLES:
                    cursor.execute(
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} "
                        f"TO {_RLS_TESTER_ROLE}"
                    )

    yield

    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute(f"REASSIGN OWNED BY {_RLS_TESTER_ROLE} TO yali_user")
            cursor.execute(f"DROP OWNED BY {_RLS_TESTER_ROLE}")
            cursor.execute(f"DROP ROLE IF EXISTS {_RLS_TESTER_ROLE}")


@pytest.mark.django_db(transaction=True)
class TestRLSMigrationApplied:

    def test_rls_enabled_on_bookings(self) -> None:
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
        rows = _execute_raw(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'bookings_booking'"
        )
        assert rows[0][0] is True, (
            "FORCE ROW LEVEL SECURITY is NOT set on bookings_booking. "
            "The table owner would bypass RLS without FORCE."
        )

    def test_policy_exists_on_all_tenant_tables(self) -> None:
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

    def test_raw_query_without_guc_returns_zero_rows(
        self, rls_tester_role: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
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
            guc_value=None,
        )

        assert len(rows) == 0, (
            f"RLS FAIL-CLOSED VIOLATION: Raw query with NO GUC returned {len(rows)} rows. "
            "Expected 0. A developer forgetting to set tenant context would see ALL tenants' data."
        )

    def test_users_user_intentionally_not_under_rls(
        self, complex_a: Any, resident: Any
    ) -> None:
        rows = _execute_raw(
            "SELECT relrowsecurity, relforcerowsecurity "
            "FROM pg_class WHERE relname = 'users_user'"
        )
        assert rows, "users_user not found in pg_class"
        assert rows[0][0] is False and rows[0][1] is False, (
            "users_user must NOT be under RLS (migration 0006_remove_users_rls). "
            "RLS on the auth table breaks the login bootstrap and null-complex admins."
        )


@pytest.mark.django_db(transaction=True)
class TestRLSCorrectTenantAccess:

    def test_raw_query_with_correct_guc_returns_rows(
        self, rls_tester_role: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
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
        import uuid

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

    def test_correct_guc_allows_own_tenant_data(
        self, rls_tester_role: Any, complex_a: Any, unit_a: Any, resident: Any
    ) -> None:
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
