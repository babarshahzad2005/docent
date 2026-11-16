"""Users, Collections, and Memberships (see GLOSSARY.md)."""

from typing import Literal
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api.auth import AuthUser

Role = Literal["owner", "editor", "viewer"]

PERSONAL_COLLECTION_NAME = "Personal"


class CollectionSummary(BaseModel):
    id: UUID
    name: str
    is_personal: bool
    role: Role


def ensure_user(conn: Connection[DictRow], user: AuthUser) -> None:
    """Create the User and their Personal Collection on first sign-in; afterwards do nothing.

    Safe under concurrent first requests: the unique constraint on a Collection's personal
    owner lets exactly one transaction create the Personal Collection and its Membership.
    """
    with conn.transaction():
        conn.execute(
            """
            insert into app.users (id, email) values (%(id)s, %(email)s)
            on conflict (id) do update set email = excluded.email
            where app.users.email is distinct from excluded.email
            """,
            {"id": user.id, "email": user.email},
        )
        created = conn.execute(
            """
            insert into app.collections (name, personal_owner_id) values (%(name)s, %(id)s)
            on conflict (personal_owner_id) do nothing
            returning id
            """,
            {"name": PERSONAL_COLLECTION_NAME, "id": user.id},
        ).fetchone()
        if created is not None:
            conn.execute(
                """
                insert into app.memberships (collection_id, user_id, role)
                values (%(collection_id)s, %(user_id)s, 'owner')
                """,
                {"collection_id": created["id"], "user_id": user.id},
            )


def list_collections(conn: Connection[DictRow], user_id: UUID) -> list[CollectionSummary]:
    """Every Collection the User is a Member of, Personal Collection first."""
    rows = conn.execute(
        """
        select c.id, c.name, c.personal_owner_id is not null as is_personal, m.role
        from app.memberships m
        join app.collections c on c.id = m.collection_id
        where m.user_id = %(user_id)s
        order by is_personal desc, lower(c.name)
        """,
        {"user_id": user_id},
    ).fetchall()
    return [CollectionSummary.model_validate(row) for row in rows]
