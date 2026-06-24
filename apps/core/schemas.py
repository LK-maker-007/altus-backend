from __future__ import annotations

from typing import Final, Literal, TypedDict

JWT_ACCESS_TYPE: Final[Literal["access"]] = "access"
JWT_REFRESH_TYPE: Final[Literal["refresh"]] = "refresh"


class JWTAccessPayload(TypedDict):

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

    token_type: Literal["refresh"]
    user_id: str
    iat: int
    exp: int
    jti: str
