import time
from collections.abc import Iterator
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from docent_api.auth import InvalidToken, decode_access_token
from docent_api.main import app
from docent_api.settings import get_settings

SUPABASE_URL = "https://project.supabase.test"
ISSUER = f"{SUPABASE_URL}/auth/v1"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def make_token(key: ec.EllipticCurvePrivateKey, **overrides: object) -> str:
    claims: dict[str, object] = {
        "sub": str(uuid4()),
        "email": "reader@example.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="ES256")


def test_a_valid_token_identifies_the_user(key: ec.EllipticCurvePrivateKey) -> None:
    user_id = uuid4()
    token = make_token(key, sub=str(user_id))

    user = decode_access_token(token, signing_key=key.public_key())

    assert user.id == user_id
    assert user.email == "reader@example.com"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 10},
        {"aud": "anon"},
        {"iss": "https://someone-else.supabase.test/auth/v1"},
        {"sub": "not-a-uuid"},
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "bad-subject"],
)
def test_invalid_tokens_are_rejected(
    key: ec.EllipticCurvePrivateKey, overrides: dict[str, object]
) -> None:
    with pytest.raises(InvalidToken):
        decode_access_token(make_token(key, **overrides), signing_key=key.public_key())


def test_a_token_signed_by_another_key_is_rejected(key: ec.EllipticCurvePrivateKey) -> None:
    other = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(InvalidToken):
        decode_access_token(make_token(other), signing_key=key.public_key())


def test_requests_without_a_session_are_rejected() -> None:
    response = TestClient(app).get("/me")

    assert response.status_code == 401


def test_requests_with_a_malformed_session_are_rejected() -> None:
    response = TestClient(app).get("/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
