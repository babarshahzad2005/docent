"""Who has access to a Collection, against a real database (TEST_DATABASE_URL)."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import CollectionNotFound, NotOwner, create_collection
from docent_api.db import get_connection
from docent_api.library import ensure_user, list_collections
from docent_api.main import app
from docent_api.members import (
    NotAMember,
    NotShared,
    OwnerCantLeave,
    change_role,
    list_members,
    remove_member,
    transfer_ownership,
)
from docent_api.retrieval import readable_scope


def a_user(conn: Connection[DictRow]) -> AuthUser:
    user = AuthUser(id=uuid4(), email=f"{uuid4().hex[:8]}@example.com")
    ensure_user(conn, user)
    conn.commit()
    return user


def join(conn: Connection[DictRow], collection_id: UUID, user: AuthUser, role: str) -> None:
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, %s)",
        (collection_id, user.id, role),
    )
    conn.commit()


def roles(conn: Connection[DictRow], collection_id: UUID, viewer: AuthUser) -> dict[UUID, str]:
    found = {m.user_id: m.role for m in list_members(conn, viewer.id, collection_id)}
    conn.commit()
    return found


@pytest.fixture
def owner(conn: Connection[DictRow]) -> AuthUser:
    return a_user(conn)


@pytest.fixture
def team(conn: Connection[DictRow], owner: AuthUser) -> UUID:
    return create_collection(conn, owner.id, "Team").id


def test_every_member_sees_who_has_access_owner_first(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    viewer, editor = a_user(conn), a_user(conn)
    join(conn, team, viewer, "viewer")
    join(conn, team, editor, "editor")

    listed = list_members(conn, viewer.id, team)

    assert [(m.user_id, m.role) for m in listed] == [
        (owner.id, "owner"),
        (editor.id, "editor"),
        (viewer.id, "viewer"),
    ]
    assert [m.is_you for m in listed] == [False, False, True]
    with pytest.raises(CollectionNotFound):
        list_members(conn, a_user(conn).id, team)


def test_the_demo_and_personal_collections_have_no_members_to_list(
    conn: Connection[DictRow], owner: AuthUser
) -> None:
    personal = list_collections(conn, owner.id)[0].id
    with pytest.raises(NotShared):
        list_members(conn, owner.id, personal)
    with pytest.raises(NotShared):
        remove_member(conn, owner.id, personal, owner.id)


def test_the_owner_changes_roles_and_others_cant(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    member, other = a_user(conn), a_user(conn)
    join(conn, team, member, "viewer")
    join(conn, team, other, "editor")

    change_role(conn, owner.id, team, member.id, "editor")
    assert roles(conn, team, owner)[member.id] == "editor"

    with pytest.raises(NotOwner):
        change_role(conn, other.id, team, member.id, "viewer")
    with pytest.raises(NotAMember):  # the Owner's Role changes only by transfer
        change_role(conn, owner.id, team, owner.id, "viewer")
    with pytest.raises(NotAMember):
        change_role(conn, owner.id, team, a_user(conn).id, "viewer")


def test_a_removed_member_loses_access_from_the_next_question(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    member = a_user(conn)
    join(conn, team, member, "editor")
    assert team in readable_scope(conn, member.id, [team])

    remove_member(conn, owner.id, team, member.id)
    conn.commit()

    assert readable_scope(conn, member.id, [team]) == []
    assert team not in [c.id for c in list_collections(conn, member.id)]


def test_only_the_owner_removes_others(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    editor, viewer = a_user(conn), a_user(conn)
    join(conn, team, editor, "editor")
    join(conn, team, viewer, "viewer")

    with pytest.raises(NotOwner):
        remove_member(conn, editor.id, team, viewer.id)
    with pytest.raises(NotOwner):  # nor the Owner, by anyone
        remove_member(conn, editor.id, team, owner.id)


def test_members_leave_but_the_owner_cant(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    viewer = a_user(conn)
    join(conn, team, viewer, "viewer")

    remove_member(conn, viewer.id, team, viewer.id)
    assert viewer.id not in roles(conn, team, owner)

    with pytest.raises(OwnerCantLeave):
        remove_member(conn, owner.id, team, owner.id)


def test_transferring_ownership_makes_the_old_owner_an_editor(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    viewer = a_user(conn)
    join(conn, team, viewer, "viewer")

    transfer_ownership(conn, owner.id, team, viewer.id)

    assert roles(conn, team, owner) == {viewer.id: "owner", owner.id: "editor"}
    with pytest.raises(NotOwner):
        transfer_ownership(conn, owner.id, team, owner.id)
    # The old Owner can leave now.
    remove_member(conn, owner.id, team, owner.id)
    assert list(roles(conn, team, viewer)) == [viewer.id]


def test_ownership_goes_only_to_a_member(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    with pytest.raises(NotAMember):
        transfer_ownership(conn, owner.id, team, a_user(conn).id)
    assert roles(conn, team, owner) == {owner.id: "owner"}


def test_racing_transfers_leave_one_owner(
    database_url: str, conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    first, second = a_user(conn), a_user(conn)
    join(conn, team, first, "viewer")
    join(conn, team, second, "viewer")

    def transfer_to(member: AuthUser) -> str:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            try:
                transfer_ownership(own, owner.id, team, member.id)
                return "moved"
            except NotOwner:
                return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(transfer_to, [first, second]))

    assert results == ["moved", "refused"]
    owners = [r for r in roles(conn, team, owner).values() if r == "owner"]
    assert owners == ["owner"]


def test_the_database_allows_one_owner(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    with pytest.raises(psycopg.errors.UniqueViolation):
        join(conn, team, a_user(conn), "owner")
    conn.rollback()


# --- HTTP ---------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def client_for(database_url: str, user: AuthUser) -> TestClient:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_connection] = connection
    return TestClient(app)


def test_the_member_endpoints(
    database_url: str, conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    member = a_user(conn)
    join(conn, team, member, "viewer")
    as_owner = client_for(database_url, owner)

    listed = as_owner.get(f"/collections/{team}/members").json()
    assert [m["role"] for m in listed] == ["owner", "viewer"]
    changed = as_owner.patch(f"/collections/{team}/members/{member.id}", json={"role": "editor"})
    assert changed.status_code == 204
    bad = as_owner.patch(f"/collections/{team}/members/{member.id}", json={"role": "owner"})
    assert bad.status_code == 422
    leave = as_owner.delete(f"/collections/{team}/members/{owner.id}")
    assert leave.status_code == 409
    assert "Make someone else the owner first" in leave.json()["detail"]

    moved = as_owner.post(f"/collections/{team}/owner", json={"user_id": str(member.id)})
    assert moved.status_code == 204
    as_member = client_for(database_url, member)
    assert as_member.delete(f"/collections/{team}/members/{owner.id}").status_code == 204
    assert [m["role"] for m in as_member.get(f"/collections/{team}/members").json()] == ["owner"]
