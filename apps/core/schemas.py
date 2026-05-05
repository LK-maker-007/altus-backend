"""Shared TypedDict schemas for cross-module structured data.

These are the single source of truth for dictionary shapes that cross
module boundaries in the Yali backend. Using TypedDict instead of
dict[str, Any] gives:
  - mypy/pyright key-level type checking (catches missing/misspelled keys)
  - IDE auto-complete on every access site
  - Self-documenting contracts between services and middleware

Reference: same pattern used by Sentry (src/sentry/services/hybrid_cloud/),
Mozilla Kuma, and Netbox for internal payload types.
"""

from __future__ import annotations

from typing import Final, Literal, TypedDict

# ── JWT token type discriminators ──────────────────────────────────────────────
# WHY Final[Literal[...]] not just Final = "...":
#   mypy infers `x: Final = "access"` as `Final[str]`, which does NOT satisfy
#   `token_type: Literal["access"]` in JWTAccessPayload. The explicit
#   `Final[Literal["access"]]` annotation tells mypy the exact literal type so
#   `JWTAccessPayload(token_type=JWT_ACCESS_TYPE)` type-checks without a cast.
#
# WHY module-level constants (not inline literals in services.py):
#   Eliminates bandit S105/S106 false positives — bandit only flags bare string
#   literals in function calls (e.g. token_type="access"), not variable references.
#   Also provides a single source of truth: if the claim name ever changes, one
#   update here propagates to services, middleware, and any future validators.
JWT_ACCESS_TYPE: Final[Literal["access"]] = "access"
JWT_REFRESH_TYPE: Final[Literal["refresh"]] = "refresh"


class JWTAccessPayload(TypedDict):
    """Claims present in every Yali access token (see AuthService.issue_tokens).

    All fields are Required — the decoder enforces this via jwt options.require.
    """

    token_type: Literal["access"]
    user_id: str
    complex_id: str | None
    unit_id: str | None
    role: str
    is_profile_complete: bool
    iat: int
    exp: int
    jti: str


class JWTRefreshPayload(TypedDict):
    """Claims present in every Yali refresh token (see AuthService.issue_tokens)."""

    token_type: Literal["refresh"]
    user_id: str
    iat: int
    exp: int
    jti: str
