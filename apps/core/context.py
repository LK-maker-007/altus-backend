from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

# Current tenant for the active request/task. A ContextVar (not threading.local)
# so it survives async views and is isolated per task. Read by the DB backend to
# set the RLS GUC and by ComplexScopedManager to scope ORM queries.
_current_complex_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_complex_id", default=None
)


def _set_context_var_complex_id(complex_id: str) -> None:
    _current_complex_id.set(complex_id)


def _get_current_complex_id() -> str | None:
    return _current_complex_id.get()


def _clear_context_var_complex_id() -> None:
    _current_complex_id.set(None)


# Bind the tenant for work outside the request cycle (Celery tasks, commands),
# where no middleware sets it. Without this, RLS would see no GUC and a
# least-privilege DB role would return zero rows.
@contextlib.contextmanager
def tenant_context(complex_id: str | None) -> Iterator[None]:
    token = _current_complex_id.set(str(complex_id) if complex_id else None)
    try:
        yield
    finally:
        _current_complex_id.reset(token)
