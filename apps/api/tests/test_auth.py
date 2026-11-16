import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from docent_api import auth
from docent_api.auth import AuthUnavailable, InvalidToken, SigningKeys, decode_access_token
from docent_api.main import app
from docent_api.settings import get_settings

SUPABASE_URL = "https://project.supabase.test"
ISSUER = f"{SUPABASE_URL}/auth/v1"
KID = "key-1"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    get_settings.cache_clear()
    auth._signing_keys.cache_clear()
    yield
    get_settings.cache_clear()
    auth._signing_keys.cache_clear()


@pytest.fixture(scope="module")
def key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def jwks_for(private_key: ec.EllipticCurvePrivateKey, kid: str = KID) -> dict[str, Any]:
    jwk: dict[str, Any] = jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "alg": "ES256", "use": "sig"}]}


class FakeJwks:
    """Serves a fixed JWKS and counts fetches."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.fetches = 0

    def __call__(self, url: str) -> dict[str, Any]:
        self.fetches += 1
        return self.data


def make_token(private_key: ec.EllipticCurvePrivateKey, kid: str = KID, **overrides: object) -> str:
    claims: dict[str, object] = {
        "sub": str(uuid4()),
        "email": "reader@example.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": kid})


@pytest.fixture
def keys(key: ec.EllipticCurvePrivateKey) -> SigningKeys:
    return SigningKeys("https://jwks.test", fetch=FakeJwks(jwks_for(key)))


def test_a_valid_token_identifies_the_user(
    key: ec.EllipticCurvePrivateKey, keys: SigningKeys
) -> None:
    user_id = uuid4()

    user = decode_access_token(make_token(key, sub=str(user_id)), keys)

    assert user.id == user_id
    assert user.email == "reader@example.com"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 10},
        {"exp": None},
        {"aud": "anon"},
        {"iss": "https://someone-else.supabase.test/auth/v1"},
        {"sub": "not-a-uuid"},
    ],
    ids=["expired", "no-expiry", "wrong-audience", "wrong-issuer", "bad-subject"],
)
def test_invalid_tokens_are_rejected(
    key: ec.EllipticCurvePrivateKey, keys: SigningKeys, overrides: dict[str, object]
) -> None:
    with pytest.raises(InvalidToken):
        decode_access_token(make_token(key, **overrides), keys)


def test_a_token_signed_by_another_key_is_rejected(keys: SigningKeys) -> None:
    other = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(InvalidToken):
        decode_access_token(make_token(other), keys)


def test_unsigned_and_shared_secret_tokens_are_rejected(keys: SigningKeys) -> None:
    claims = {"sub": str(uuid4()), "aud": "authenticated", "iss": ISSUER, "exp": 9999999999}
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": KID})
    hs256 = jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": KID})

    for token in (unsigned, hs256):
        with pytest.raises(InvalidToken):
            decode_access_token(token, keys)


def test_unknown_key_ids_refresh_at_most_once_a_minute(key: ec.EllipticCurvePrivateKey) -> None:
    now = [0.0]
    fake = FakeJwks(jwks_for(key))
    keys = SigningKeys("https://jwks.test", fetch=fake, clock=lambda: now[0])

    decode_access_token(make_token(key), keys)  # first use fetches once
    for _ in range(20):
        with pytest.raises(InvalidToken):
            decode_access_token(make_token(key, kid="made-up"), keys)
    assert fake.fetches == 1

    now[0] += 61
    with pytest.raises(InvalidToken):
        decode_access_token(make_token(key, kid="made-up"), keys)
    assert fake.fetches == 2


def test_rotated_keys_are_picked_up(key: ec.EllipticCurvePrivateKey) -> None:
    now = [0.0]
    new_key = ec.generate_private_key(ec.SECP256R1())
    fake = FakeJwks(jwks_for(key))
    keys = SigningKeys("https://jwks.test", fetch=fake, clock=lambda: now[0])
    decode_access_token(make_token(key), keys)

    fake.data = jwks_for(new_key, kid="key-2")
    now[0] += 61

    assert decode_access_token(make_token(new_key, kid="key-2"), keys).email == "reader@example.com"


def test_unreachable_keys_mean_unavailable_not_invalid(key: ec.EllipticCurvePrivateKey) -> None:
    def down(url: str) -> dict[str, Any]:
        raise AuthUnavailable("network down")

    with pytest.raises(AuthUnavailable):
        decode_access_token(make_token(key), SigningKeys("https://jwks.test", fetch=down))


def test_requests_without_a_session_are_rejected() -> None:
    assert TestClient(app).get("/me").status_code == 401


def test_requests_with_a_malformed_session_are_rejected() -> None:
    response = TestClient(app).get("/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_a_key_outage_is_reported_as_503_not_an_expired_session(
    key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    def outage(self: SigningKeys) -> None:
        raise AuthUnavailable("network down")

    monkeypatch.setattr(SigningKeys, "_refresh", outage)

    response = TestClient(app).get("/me", headers={"Authorization": f"Bearer {make_token(key)}"})

    assert response.status_code == 503


def test_missing_configuration_is_reported_as_503(
    key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    get_settings.cache_clear()

    response = TestClient(app).get("/me", headers={"Authorization": f"Bearer {make_token(key)}"})

    assert response.status_code == 503
