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
    is_demo: bool
    role: Role


def ensure_user(conn: Connection[DictRow], user: AuthUser) -> None:
    """Create the User and their Personal Collection on first sign-in, and accept any Invites
    to their address; otherwise do nothing.

    Safe under concurrent first requests: the unique constraint on a Collection's personal
    owner lets exactly one transaction create the Personal Collection. The owner Membership is
    upserted on every call, so a Personal Collection can never be left without its Owner.
    """
    with conn.transaction():
        conn.execute(
            """
            insert into app.users (id, email) values (%(id)s, %(email)s)
            on conflict (id) do update set email = excluded.email
            where excluded.email <> '' and app.users.email is distinct from excluded.email
            """,
            {"id": user.id, "email": user.email},
        )
        conn.execute(
            """
            insert into app.collections (name, personal_owner_id) values (%(name)s, %(id)s)
            on conflict (personal_owner_id) do nothing
            """,
            {"name": PERSONAL_COLLECTION_NAME, "id": user.id},
        )
        conn.execute(
            """
            insert into app.memberships (collection_id, user_id, role)
            select id, %(id)s, 'owner' from app.collections where personal_owner_id = %(id)s
            on conflict (collection_id, user_id) do nothing
            """,
            {"id": user.id},
        )
        # Invites to this address become Memberships (GLOSSARY: Invite). The address comes
        # from the token, which Supabase issues only once the address is verified: Google, a
        # sign-in link, or a confirmed sign-up ("Confirm email" is on; mailer_autoconfirm was
        # false when checked on 2026-11-22). So nobody can claim someone else's invites.
        if user.email:
            # Collections first, then invites: the order Owner actions lock them in
            # (invites.lock_collection_then_invite), so the two never deadlock.
            conn.execute(
                """
                select 1 from app.collections
                where id in (
                    select collection_id from app.invites
                    where email = lower(%(email)s) and accepted_at is null
                )
                order by id
                for key share
                """,
                {"email": user.email},
            )
            conn.execute(
                """
                with accepted as (
                    update app.invites set accepted_by = %(id)s, accepted_at = now()
                    where email = lower(%(email)s) and accepted_at is null
                      and expires_at > now()
                    returning collection_id, role
                )
                insert into app.memberships (collection_id, user_id, role)
                select collection_id, %(id)s, role from accepted
                on conflict (collection_id, user_id) do nothing
                """,
                {"id": user.id, "email": user.email},
            )
        # Every User can ask the Demo Collection, read-only (PRD decision log, 2026-11-18).
        conn.execute(
            """
            insert into app.memberships (collection_id, user_id, role)
            select id, %(id)s, 'viewer' from app.collections where is_demo
            on conflict (collection_id, user_id) do nothing
            """,
            {"id": user.id},
        )


def list_collections(conn: Connection[DictRow], user_id: UUID) -> list[CollectionSummary]:
    """Every Collection the User is a Member of, Personal Collection first."""
    rows = conn.execute(
        """
        select c.id, c.name, c.personal_owner_id is not null as is_personal, c.is_demo, m.role
        from app.memberships m
        join app.collections c on c.id = m.collection_id
        where m.user_id = %(user_id)s
        order by is_personal desc, c.is_demo, lower(c.name)
        """,
        {"user_id": user_id},
    ).fetchall()
    return [CollectionSummary.model_validate(row) for row in rows]
