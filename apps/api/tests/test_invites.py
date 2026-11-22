"""Inviting people to a Collection, against a real database (TEST_DATABASE_URL)."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import FixedCollection, NotOwner, create_collection
from docent_api.db import get_connection
from docent_api.invites import (
    AlreadyMember,
    BadEmail,
    InviteNotFound,
    WrongAccount,
    accept_invite,
    invite,
    list_invites,
    mask,
    revoke_invite,
)
from docent_api.library import ensure_user, list_collections
from docent_api.main import app


def a_user(conn: Connection[DictRow], email: str | None = None) -> AuthUser:
    user = AuthUser(id=uuid4(), email=email or f"{uuid4().hex[:8]}@example.com")
    ensure_user(conn, user)
    conn.commit()
    return user


def an_address() -> str:
    return f"{uuid4().hex[:8]}@example.com"


@pytest.fixture
def owner(conn: Connection[DictRow]) -> AuthUser:
    return a_user(conn)


@pytest.fixture
def team(conn: Connection[DictRow], owner: AuthUser) -> UUID:
    return create_collection(conn, owner.id, "Team").id


def role_of(conn: Connection[DictRow], user: AuthUser, collection_id: UUID) -> str | None:
    roles = {c.id: c.role for c in list_collections(conn, user.id)}
    conn.commit()
    return roles.get(collection_id)


def test_an_invite_waits_until_its_address_signs_in(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    address = an_address()
    sent = invite(conn, owner.id, team, f"  {address.upper()} ", "editor")

    assert (sent.email, sent.role) == (address, "editor")
    assert [i.email for i in list_invites(conn, owner.id, team)] == [address]

    # Signing in for the first time, without the link, is enough.
    invited = a_user(conn, address.upper())

    assert role_of(conn, invited, team) == "editor"
    assert list_invites(conn, owner.id, team) == []


def test_the_link_works_only_for_the_invited_address(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    address = an_address()
    sent = invite(conn, owner.id, team, address, "viewer")
    someone_else = a_user(conn)

    with pytest.raises(WrongAccount) as wrong:
        accept_invite(conn, someone_else.id, someone_else.email, sent.id)
    assert wrong.value.masked_email == mask(address)
    assert address not in wrong.value.masked_email
    assert role_of(conn, someone_else, team) is None


def test_opening_the_link_after_signing_in_leads_to_the_collection(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    address = an_address()
    sent = invite(conn, owner.id, team, address, "viewer")
    invited = a_user(conn, address)  # signing in accepted it already

    assert accept_invite(conn, invited.id, invited.email, sent.id) == team
    assert accept_invite(conn, invited.id, invited.email, sent.id) == team
    assert role_of(conn, invited, team) == "viewer"


def test_a_removed_member_cant_come_back_through_an_old_link(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    address = an_address()
    sent = invite(conn, owner.id, team, address, "viewer")
    invited = a_user(conn, address)
    conn.execute(
        "delete from app.memberships where collection_id = %s and user_id = %s",
        (team, invited.id),
    )
    conn.commit()

    with pytest.raises(InviteNotFound):
        accept_invite(conn, invited.id, invited.email, sent.id)
    # Inviting them again works, with the same link.
    again = invite(conn, owner.id, team, address, "editor")
    assert again.id == sent.id
    assert accept_invite(conn, invited.id, invited.email, sent.id) == team
    assert role_of(conn, invited, team) == "editor"


def test_a_cancelled_or_expired_invite_grants_nothing(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    cancelled, expired = an_address(), an_address()
    first = invite(conn, owner.id, team, cancelled, "viewer")
    second = invite(conn, owner.id, team, expired, "viewer")
    revoke_invite(conn, owner.id, first.id)
    conn.execute(
        "update app.invites set expires_at = now() - interval '1 second' where id = %s",
        (second.id,),
    )
    conn.commit()

    for address, sent in ((cancelled, first), (expired, second)):
        user = a_user(conn, address)
        assert role_of(conn, user, team) is None
        with pytest.raises(InviteNotFound):
            accept_invite(conn, user.id, user.email, sent.id)
    assert list_invites(conn, owner.id, team) == []


def test_inviting_again_updates_the_role_and_keeps_the_link(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    address = an_address()
    first = invite(conn, owner.id, team, address, "viewer")
    second = invite(conn, owner.id, team, address, "editor")

    assert second.id == first.id
    assert [(i.email, i.role) for i in list_invites(conn, owner.id, team)] == [(address, "editor")]


@pytest.mark.parametrize(
    "address", ["", "not-an-email", "a@b", "two@@example.com", "x" * 250 + "@a.co"]
)
def test_only_email_addresses_are_invited(
    conn: Connection[DictRow], owner: AuthUser, team: UUID, address: str
) -> None:
    with pytest.raises(BadEmail):
        invite(conn, owner.id, team, address, "viewer")


def test_nobody_is_invited_twice_or_invites_themselves(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    with pytest.raises(BadEmail):
        invite(conn, owner.id, team, owner.email.upper(), "viewer")
    member = a_user(conn)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer')",
        (team, member.id),
    )
    conn.commit()
    with pytest.raises(AlreadyMember):
        invite(conn, owner.id, team, member.email, "editor")


def test_only_the_owner_invites_and_never_into_the_personal_collection(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    editor = a_user(conn)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'editor')",
        (team, editor.id),
    )
    conn.commit()
    with pytest.raises(NotOwner):
        invite(conn, editor.id, team, an_address(), "viewer")
    with pytest.raises(NotOwner):
        list_invites(conn, editor.id, team)
    sent = invite(conn, owner.id, team, an_address(), "viewer")
    with pytest.raises(NotOwner):
        revoke_invite(conn, editor.id, sent.id)

    personal = list_collections(conn, owner.id)[0].id
    with pytest.raises(FixedCollection):
        invite(conn, owner.id, personal, an_address(), "viewer")


# --- HTTP ---------------------------------------------------------------------------------


def client_for(database_url: str, user: AuthUser) -> TestClient:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_connection] = connection
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_the_invite_endpoints(
    database_url: str, conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    address = an_address()
    as_owner = client_for(database_url, owner)
    sent = as_owner.post(f"/collections/{team}/invites", json={"email": address, "role": "viewer"})
    assert sent.status_code == 201
    invite_id = sent.json()["id"]
    assert as_owner.get(f"/collections/{team}/invites").json()[0]["email"] == address
    bad = as_owner.post(f"/collections/{team}/invites", json={"email": "nope", "role": "viewer"})
    assert bad.status_code == 400
    owner_role = as_owner.post(
        f"/collections/{team}/invites", json={"email": address, "role": "owner"}
    )
    assert owner_role.status_code == 422  # only editor or viewer

    stranger = AuthUser(id=uuid4(), email=an_address())
    wrong = client_for(database_url, stranger).post(f"/invites/{invite_id}/accept")
    assert wrong.status_code == 403
    assert "Sign out, then sign in" in wrong.json()["detail"]
    assert address not in wrong.json()["detail"]

    invited = AuthUser(id=uuid4(), email=address)  # never signed in before
    accepted = client_for(database_url, invited).post(f"/invites/{invite_id}/accept")
    assert (accepted.status_code, accepted.json()["id"], accepted.json()["role"]) == (
        200,
        str(team),
        "viewer",
    )

    gone = client_for(database_url, owner).delete(f"/invites/{uuid4()}")
    assert gone.status_code == 204
    expired = client_for(database_url, invited).post(f"/invites/{uuid4()}/accept")
    assert expired.status_code == 404


def test_cancelling_an_accepted_invite_leaves_its_member_alone(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    address = an_address()
    sent = invite(conn, owner.id, team, address, "viewer")
    invited = a_user(conn, address)

    with pytest.raises(InviteNotFound):
        revoke_invite(conn, owner.id, sent.id)
    assert role_of(conn, invited, team) == "viewer"
    assert accept_invite(conn, invited.id, invited.email, sent.id) == team
