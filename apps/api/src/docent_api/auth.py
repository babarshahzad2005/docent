"""Verifies the Supabase access token sent with each request.

Tokens are signed with the project's asymmetric keys, so the API only needs the public keys
(JWKS) and never a shared secret. Keys are cached for at most 10 minutes, matching Supabase's
own cache, so rotated keys are picked up promptly.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from docent_api.settings import get_settings

_ALGORITHMS = ["ES256", "RS256"]
_AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str


class InvalidToken(Exception):
    pass


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(get_settings().jwks_url, cache_keys=True, lifespan=600)


def decode_access_token(token: str, signing_key: Any | None = None) -> AuthUser:
    """Return the signed-in user the token belongs to, or raise InvalidToken."""
    try:
        key = (
            signing_key
            if signing_key is not None
            else _jwks_client().get_signing_key_from_jwt(token).key
        )
        claims = jwt.decode(
            token,
            key,
            algorithms=_ALGORITHMS,
            audience=_AUDIENCE,
            issuer=get_settings().auth_issuer,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
        return AuthUser(id=UUID(claims["sub"]), email=str(claims.get("email") or ""))
    except (jwt.PyJWTError, ValueError, KeyError) as error:
        raise InvalidToken(str(error)) from error


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    """FastAPI dependency: the signed-in user, or 401."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    try:
        return decode_access_token(credentials.credentials)
    except InvalidToken:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again."
        ) from None
