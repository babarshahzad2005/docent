"""Verifies the Supabase access token sent with each request.

Tokens are signed with the project's asymmetric ES256 keys, so the API needs only the public
keys (JWKS) and never a shared secret. Keys are refreshed every 10 minutes, matching Supabase's
own cache. A token naming an unknown key triggers at most one early refresh per minute, so
made-up key IDs can't make the API hammer Supabase.

A bad token is the caller's problem (401). Being unable to fetch keys, or missing
configuration, is the server's problem (503) — never reported as an expired session.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from docent_api.settings import get_settings

_ALGORITHM = "ES256"
_AUDIENCE = "authenticated"
_REFRESH_AFTER_SECONDS = 600
_MIN_REFRESH_INTERVAL_SECONDS = 60

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str


class InvalidToken(Exception):
    """The token is missing, malformed, expired, or not signed by this project."""


class AuthUnavailable(Exception):
    """Tokens can't be checked right now (keys unreachable or the server is misconfigured)."""


def _fetch_jwks(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data: dict[str, Any] = json.load(response)
            return data
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise AuthUnavailable(f"signing keys unavailable: {error}") from error


class SigningKeys:
    """The project's public signing keys, by key ID, with bounded refreshing."""

    def __init__(
        self,
        url: str,
        fetch: Callable[[str], dict[str, Any]] = _fetch_jwks,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._fetch = fetch
        self._clock = clock
        self._keys: dict[str, Any] | None = None
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def get(self, kid: str) -> Any:
        with self._lock:
            age = self._clock() - self._fetched_at
            stale = self._keys is None or age > _REFRESH_AFTER_SECONDS
            unknown = self._keys is not None and kid not in self._keys
            if stale or (unknown and age > _MIN_REFRESH_INTERVAL_SECONDS):
                self._refresh()
            assert self._keys is not None
            if kid not in self._keys:
                raise InvalidToken("token is signed by an unknown key")
            return self._keys[kid]

    def _refresh(self) -> None:
        data = self._fetch(self._url)
        try:
            jwk_set = jwt.PyJWKSet.from_dict(data)
        except jwt.PyJWTError as error:
            raise AuthUnavailable(f"signing keys unreadable: {error}") from error
        self._keys = {k.key_id: k.key for k in jwk_set.keys if k.key_id}
        self._fetched_at = self._clock()


@lru_cache
def _signing_keys() -> SigningKeys:
    settings = get_settings()
    if not settings.supabase_url:
        raise AuthUnavailable("SUPABASE_URL is not configured")
    return SigningKeys(settings.jwks_url)


def decode_access_token(token: str, keys: SigningKeys | None = None) -> AuthUser:
    """Return the signed-in user the token belongs to.

    Raises InvalidToken for a bad token and AuthUnavailable when tokens can't be checked.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as error:
        raise InvalidToken("token is malformed") from error
    kid = header.get("kid")
    if header.get("alg") != _ALGORITHM or not isinstance(kid, str):
        raise InvalidToken("token is not signed with this project's keys")

    key = (keys or _signing_keys()).get(kid)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            issuer=get_settings().auth_issuer,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
        return AuthUser(id=UUID(claims["sub"]), email=str(claims.get("email") or ""))
    except (jwt.PyJWTError, ValueError) as error:
        raise InvalidToken(str(error)) from error


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    """FastAPI dependency: the signed-in user, 401 for a bad session, 503 if checks can't run."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    try:
        return decode_access_token(credentials.credentials)
    except InvalidToken:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again."
        ) from None
    except AuthUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Sign-in can't be checked right now. Try again in a minute.",
        ) from None
