"""
config/db_backend/base.py

Custom PostgreSQL database backend that injects SET LOCAL app.current_complex
into every database cursor when the multi-tenant ContextVar is active.

WHY this is needed:
  migration 0003_rls_policies.py installs PostgreSQL Row-Level Security policies:
    USING (complex_id::text = current_setting('app.current_complex', true))
  current_setting() returns NULL when the GUC has never been SET → policy
  evaluates complex_id::text = NULL → false for every row → all RLS-protected
  tables silently return zero rows (or BYPASSRLS suppresses enforcement entirely).
  ComplexContextMiddleware sets the ContextVar for application-layer filtering
  (ComplexScopedManager) but that does NOT propagate to the PostgreSQL GUC.
  This backend bridges the gap: every cursor sees the correct tenant GUC.

WHY create_cursor() not execute_wrapper():
  execute_wrapper() fires per-statement. Calling connection.cursor() inside a
  wrapper to inject SET LOCAL causes infinite recursion (wrapper re-enters itself).
  create_cursor() is called once per cursor object, before any statements
  execute — the only non-recursive hook available.
  Source: django-pgschemas custom backend pattern; Django docs §low-level-sql.

WHY SET LOCAL not SET:
  SET LOCAL is transaction-scoped — it resets on COMMIT or ROLLBACK.
  With PgBouncer in transaction mode (CONN_MAX_AGE=0), connections are returned
  to the pool at transaction end. SET LOCAL values never bleed between requests.
  SET (session-level) would persist until the connection is recycled, risking
  tenant data leaks if PgBouncer pool reuse races with context clearing.

WHY one SET LOCAL per cursor (not once per transaction):
  Django can create multiple cursors within the same transaction. SET LOCAL is
  idempotent — calling it multiple times with the same value is safe.
  Tracking "already injected" state across cursors is complex and error-prone;
  the extra round-trip cost is negligible against typical query latency.
"""

from __future__ import annotations

from typing import Any

from django.db.backends.postgresql import base as pg_base


class DatabaseWrapper(pg_base.DatabaseWrapper):
    """PostgreSQL backend that auto-injects SET LOCAL app.current_complex per cursor."""

    def create_cursor(self, name: str | None = None) -> Any:
        cursor = super().create_cursor(name)
        # Local import prevents circular: context → models → db → context.
        from apps.core.context import _get_current_complex_id

        complex_id = _get_current_complex_id()
        if complex_id is not None:
            # WHY psycopg transaction_status check (not Django's needs_rollback):
            #   When transaction.atomic() catches an error (e.g. IntegrityError),
            #   it calls savepoint_rollback() which creates a cursor via _cursor().
            #   At that moment the PostgreSQL connection is in INERROR state —
            #   SET LOCAL raises InFailedSqlTransaction, savepoint_rollback() fails,
            #   and atomic.__exit__ then sets needs_rollback=True. In other words,
            #   needs_rollback is False DURING the problematic cursor creation and
            #   True only AFTER the damage is done. The psycopg3
            #   connection.info.transaction_status reflects the real PG wire state
            #   immediately — INERROR before any ROLLBACK is issued.
            #   Skipping SET LOCAL here is safe: ROLLBACK TO SAVEPOINT clears the
            #   inerror state, and the next clean cursor re-injects SET LOCAL.
            #   Source: psycopg3 docs §transaction-status;
            #   Django source atomic.__exit__ §savepoint_rollback error handling.
            try:
                from psycopg.pq import TransactionStatus  # psycopg3 only

                if (
                    self.connection is not None
                    and self.connection.info.transaction_status
                    == TransactionStatus.INERROR
                ):
                    return cursor
            except ImportError, AttributeError:
                # Not psycopg3, or connection not yet established — proceed.
                pass
            cursor.execute("SET LOCAL app.current_complex = %s", (complex_id,))
        return cursor
