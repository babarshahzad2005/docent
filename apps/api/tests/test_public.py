"""Making a Collection public, with an optional expiry (#93; GLOSSARY: Public Collection).

Who may reach a Public Collection, and what a Visitor sees, is in test_leaks.py.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from docent_api.auth import AuthUser
from docent_api.collection_settings import FixedCollection, create_collection, rename_collection
from docent_api.library import ensure_user, list_collections
from docent_api.public import PublicCollectionNotFound, public_collection, set_public


def a_user(conn: Connection[DictRow]) -> AuthUser:
    user = AuthUser(id=uuid4(), email=f"owner-{uuid4().hex[:6]}@example.com")
    ensure_user(conn, user)
    return user


def test_public_with_an_expiry_shows_when_it_ends(conn: Connection[DictRow]) -> None:
    owner = a_user(conn)
    team = create_collection(conn, owner.id, "Handbook").id

    state = set_public(conn, owner.id, team, True, expires_in_days=7)

    assert state.public
    assert state.public_until is not None
    expected = datetime.now(UTC) + timedelta(days=7)
    assert abs(state.public_until - expected) < timedelta(minutes=1)
    listed = next(c for c in list_collections(conn, owner.id) if c.id == team)
    assert listed.public and listed.public_until == state.public_until
    assert public_collection(conn, team).name == "Handbook"
    # Renaming keeps it public, and says so.
    assert rename_collection(conn, owner.id, team, "Staff handbook").public


def test_turning_it_on_again_without_an_expiry_clears_the_old_one(
    conn: Connection[DictRow],
) -> None:
    owner = a_user(conn)
    team = create_collection(conn, owner.id, "Handbook").id
    set_public(conn, owner.id, team, True, expires_in_days=1)

    state = set_public(conn, owner.id, team, True)

    assert state.public and state.public_until is None


def test_private_again(conn: Connection[DictRow]) -> None:
    owner = a_user(conn)
    team = create_collection(conn, owner.id, "Handbook").id
    set_public(conn, owner.id, team, True, expires_in_days=30)

    state = set_public(conn, owner.id, team, False)

    assert not state.public and state.public_until is None
    with pytest.raises(PublicCollectionNotFound):
        public_collection(conn, team)
    listed = next(c for c in list_collections(conn, owner.id) if c.id == team)
    assert not listed.public and listed.public_until is None


def test_the_personal_collection_is_never_public(conn: Connection[DictRow]) -> None:
    owner = a_user(conn)
    personal = list_collections(conn, owner.id)[0]
    assert personal.is_personal

    with pytest.raises(FixedCollection):
        set_public(conn, owner.id, personal.id, True)


def test_only_the_offered_expiries(conn: Connection[DictRow]) -> None:
    owner = a_user(conn)
    team = create_collection(conn, owner.id, "Handbook").id

    with pytest.raises(ValueError):
        set_public(conn, owner.id, team, True, expires_in_days=365)
