from __future__ import annotations

from typing import Any, cast

import jwt
from django.conf import settings


# Single decode point for every JWT. Tries the current key then the previous one
# so JWT_SECRET_KEY can be rotated with zero downtime (old tokens stay valid until
# they expire). Only a signature mismatch falls through to the next key; expiry and
# malformed tokens reject immediately.
def decode_jwt(
    token: str,
    *,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decode_options: dict[str, Any] = options or {}

    candidate_keys: list[str] = [settings.JWT_SECRET_KEY]
    if settings.JWT_PREVIOUS_SECRET_KEY:
        candidate_keys.append(settings.JWT_PREVIOUS_SECRET_KEY)

    first_signature_exc: jwt.InvalidSignatureError | None = None

    for key in candidate_keys:
        try:
            return jwt.decode(
                token,
                key,
                # algorithms pinned to HS256 — never trust the token header
                # (defeats the alg-confusion attack, CVE-2022-29217).
                algorithms=["HS256"],
                options=cast(Any, decode_options),
            )
        except jwt.InvalidSignatureError as exc:
            if first_signature_exc is None:
                first_signature_exc = exc
            continue

    raise jwt.InvalidTokenError(
        f"Token signature invalid for all {len(candidate_keys)} candidate key(s)."
    ) from first_signature_exc
