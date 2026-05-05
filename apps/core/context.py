from __future__ import annotations

import contextvars

# ContextVar is async-safe — scoped to the current task/coroutine, not the OS thread.
# threading.local() breaks under async Django views and asyncio.gather().
_current_complex_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_complex_id", default=None
)


def _set_context_var_complex_id(complex_id: str) -> None:
    _current_complex_id.set(complex_id)


def _get_current_complex_id() -> str | None:
    return _current_complex_id.get()


def _clear_context_var_complex_id() -> None:
    _current_complex_id.set(None)
