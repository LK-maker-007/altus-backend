"""
apps/core/jwt_utils.py

Single decode point for all JWT verification across the codebase.

WHY a dedicated module (not inline in jwt_auth.py or services.py):
  There are 3 decode call sites: JWTAuthMiddleware._decode_token(),
  AuthService.refresh_access_token(), and AuthService.revoke_tokens().
  A single decode point ensures zero-downtime key rotation logic is applied
  consistently across ALL sites — missing one site would silently log users
  out mid-rotation or allow replay with a compromised old key.

WHY only retry on InvalidSignatureError (not all InvalidTokenError):
  InvalidSignatureError = "wrong key" → try the next candidate key.
  ExpiredSignatureError = token genuinely expired → reject immediately.
    (Retrying with an old key would NOT fix expiry; accepting an expired
    token signed by a fallback key would be a silent security bypass.)
  DecodeError = malformed token → reject immediately.
    (A different key cannot repair a structurally invalid token.)
  Catching only InvalidSignatureError matches Django's own SECRET_KEY_FALLBACKS
  semantics (Django 4.1+) and PyJWT's exception hierarchy.

WHY algorithms hardcoded to ["HS256"]:
  Algorithm confusion attacks (CVE-2022-29217) exploit libraries that accept
  the algorithm from the token header. We use HS256 exclusively. Hardcoding
  here prevents "none"/"RS256"-confusion attacks regardless of what any token
  header claims. Source: PyJWT 2.x migration guide; OWASP JWT security cheat sheet.

Rotation procedure (zero-downtime):
  1. Set JWT_PREVIOUS_SECRET_KEY = current JWT_SECRET_KEY value.
  2. Deploy. Both keys are now accepted for verification.
  3. Set JWT_SECRET_KEY = new key. Deploy. New tokens signed with new key;
     old tokens (still valid until natural expiry) accepted via previous key.
  4. After JWT_REFRESH_TOKEN_LIFETIME_DAYS (default: 30 days), all old tokens
     have expired. Unset JWT_PREVIOUS_SECRET_KEY. Deploy.
  Run `python manage.py rotate_jwt_secret` for a guided rotation assistant.

Sources:
  Django 4.1 release notes §SECRET_KEY_FALLBACKS
  PyJWT 2.x exception hierarchy (jwt.exceptions)
  auth_patterns_2026.md §JWT Rotation
  docs/runbooks/secrets-rotation.md
"""

from __future__ import annotations

from typing import Any

import jwt
from django.conf import settings


def decode_jwt(
    token: str,
    *,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decode a JWT trying JWT_SECRET_KEY first, then JWT_PREVIOUS_SECRET_KEY.

    Callers must handle:
      jwt.ExpiredSignatureError  — token has expired (raise domain TokenExpiredError)
      jwt.InvalidTokenError      — bad signature, malformed, or missing claims

    Args:
        token:   Raw JWT string (without "Bearer " prefix).
        options: Extra PyJWT decode options, e.g. {"verify_exp": False} for logout
                 revocation where near-expired refresh tokens must still be blacklisted,
                 or {"require": ["exp", "jti"]} for strict claim validation.

    Returns:
        Decoded payload as dict[str, Any].

    Raises:
        jwt.ExpiredSignatureError: Token is expired. Propagates immediately — not a
            key-mismatch issue, retrying with a fallback key would not fix it.
        jwt.InvalidTokenError: Token is invalid for all candidate keys (bad signature,
            malformed header, missing required claim).
    """
    decode_options: dict[str, Any] = options or {}

    # Build candidate key list: current key first, then previous key (if set).
    # JWT_PREVIOUS_SECRET_KEY is empty string by default — falsy → skipped.
    candidate_keys: list[str] = [settings.JWT_SECRET_KEY]
    if settings.JWT_PREVIOUS_SECRET_KEY:
        candidate_keys.append(settings.JWT_PREVIOUS_SECRET_KEY)

    first_signature_exc: jwt.InvalidSignatureError | None = None

    for key in candidate_keys:
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[
                    "HS256"
                ],  # Hardcoded — prevents algorithm confusion attacks
                # WHY type: ignore[arg-type] for options:
                #   Our public API uses dict[str, Any] (callers don't need to import
                #   jwt.types.Options). At runtime, dict[str, Any] is structurally
                #   identical to Options (TypedDict) — mypy nominal-vs-structural gap.
                options=decode_options,  # type: ignore[arg-type]
            )
        except jwt.InvalidSignatureError as exc:
            # Wrong key — save context from the primary key failure, try next.
            if first_signature_exc is None:
                first_signature_exc = exc
            continue
        # jwt.ExpiredSignatureError, jwt.DecodeError, jwt.MissingRequiredClaimError,
        # and all other InvalidTokenError subclasses propagate immediately.
        # They indicate problems with the token itself, not a key mismatch.

    # All candidate keys exhausted — the signature is invalid for all known keys.
    raise jwt.InvalidTokenError(
        f"Token signature invalid for all {len(candidate_keys)} candidate key(s)."
    ) from first_signature_exc
