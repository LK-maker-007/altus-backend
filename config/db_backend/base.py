"""PostgreSQL backend that binds the current tenant to every cursor.

The RLS policies (migration 0003) filter on ``current_setting('app.current_complex')``.
Setting that GUC per-cursor here is what makes the database enforce tenant
isolation independently of application code. SET LOCAL is transaction-scoped, so
the value resets on COMMIT/ROLLBACK and never leaks across pooled connections.
"""

from __future__ import annotations

from typing import Any

from django.db.backends.postgresql import base as pg_base


class DatabaseWrapper(pg_base.DatabaseWrapper):
    def create_cursor(self, name: str | None = None) -> Any:
        cursor = super().create_cursor(name)
        from apps.core.context import _get_current_complex_id

        complex_id = _get_current_complex_id()
        if complex_id is not None:
            # During savepoint rollback Django opens a cursor while the connection
            # is already INERROR; issuing SET LOCAL there raises. Skip it — the next
            # clean cursor re-injects the GUC after ROLLBACK clears the error state.
            try:
                from psycopg.pq import TransactionStatus

                if (
                    self.connection is not None
                    and self.connection.info.transaction_status
                    == TransactionStatus.INERROR
                ):
                    return cursor
            except (ImportError, AttributeError):
                pass
            cursor.execute("SET LOCAL app.current_complex = %s", (complex_id,))
        return cursor
