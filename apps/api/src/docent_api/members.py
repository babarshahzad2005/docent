"""Who has access to a Collection (GLOSSARY: Member, Role, Owner; FLOWS: Share).

Every Member sees who has access. The Owner changes Roles, removes Members, and transfers
ownership; anyone else can leave. Access is checked in the retrieval query itself, so each
change applies from the next question on.
"""

from typing import Literal
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api.collection_settings import CollectionNotFound, require_owner
from docent_api.library import Role

MemberRole = Literal["editor", "viewer"]


class MemberSummary(BaseModel):
    user_id: UUID
    email: str
    role: Role
    is_you: bool


class NotAMember(Exception):
    """The User to change isn't a Member of the Collection."""


class OwnerCantLeave(Exception):
    """The Owner must transfer ownership before leaving (or delete the Collection)."""


class NotShared(Exception):
    """The Personal and Demo Collections have no membership to manage."""


def list_members(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID
) -> list[MemberSummary]:
    """Everyone with access, Owner first, for any Member. Not for the Demo Collection, whose
    Members are every User."""
    shared = _shared(conn, user_id, collection_id)
    if shared is None:
        raise CollectionNotFound(collection_id)
    if not shared:
        raise NotShared(collection_id)
    rows = conn.execute(
        """
        select u.id as user_id, u.email, m.role, u.id = %(me)s as is_you
        from app.memberships m join app.users u on u.id = m.user_id
        where m.collection_id = %(collection)s
        order by m.role = 'owner' desc, m.role = 'editor' desc, lower(u.email)
        """,
        {"me": user_id, "collection": collection_id},
    ).fetchall()
    return [MemberSummary.model_validate(row) for row in rows]


def change_role(
    conn: Connection[DictRow],
    user_id: UUID,
    collection_id: UUID,
    member_id: UUID,
    role: MemberRole,
) -> None:
    """Make a Member an Editor or a Viewer (the Owner). The Owner's own Role changes only by
    transferring ownership."""
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        changed = conn.execute(
            """
            update app.memberships set role = %(role)s
            where collection_id = %(collection)s and user_id = %(member)s and role <> 'owner'
            returning 1
            """,
            {"role": role, "collection": collection_id, "member": member_id},
        ).fetchone()
        if changed is None:
            raise NotAMember(member_id)


def remove_member(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID, member_id: UUID
) -> None:
    """Remove a Member (the Owner), or leave (anyone but the Owner, removing themselves)."""
    with conn.transaction():
        if member_id == user_id:
            shared = _shared(conn, user_id, collection_id, lock=True)
            if shared is None:
                raise CollectionNotFound(collection_id)
            if not shared:
                raise NotShared(collection_id)
            role = _role(conn, collection_id, user_id)
            if role == "owner":
                raise OwnerCantLeave(collection_id)
        else:
            require_owner(conn, user_id, collection_id)
        removed = conn.execute(
            """
            delete from app.memberships
            where collection_id = %s and user_id = %s and role <> 'owner'
            returning 1
            """,
            (collection_id, member_id),
        ).fetchone()
        if removed is None:
            raise NotAMember(member_id)


def transfer_ownership(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID, member_id: UUID
) -> None:
    """Make another Member the Owner; the old Owner stays, as an Editor."""
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        if member_id == user_id:
            return
        promoted = conn.execute(
            """
            update app.memberships set role = 'owner'
            where collection_id = %s and user_id = %s
            returning 1
            """,
            (collection_id, member_id),
        ).fetchone()
        if promoted is None:
            raise NotAMember(member_id)
        conn.execute(
            "update app.memberships set role = 'editor' where collection_id = %s and user_id = %s",
            (collection_id, user_id),
        )


def _shared(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID, lock: bool = False
) -> bool | None:
    """None when the User isn't a Member; else whether the Collection can have Members
    besides its Owner (not Personal, not Demo). `lock` waits for Owner actions under way."""
    row = conn.execute(
        f"""
        select c.personal_owner_id is null and not c.is_demo as shared
        from app.collections c
        join app.memberships m on m.collection_id = c.id and m.user_id = %(user)s
        where c.id = %(id)s
        {"for key share of c" if lock else ""}
        """,
        {"id": collection_id, "user": user_id},
    ).fetchone()
    return None if row is None else bool(row["shared"])


def _role(conn: Connection[DictRow], collection_id: UUID, user_id: UUID) -> str | None:
    row = conn.execute(
        "select role from app.memberships where collection_id = %s and user_id = %s",
        (collection_id, user_id),
    ).fetchone()
    return None if row is None else str(row["role"])
