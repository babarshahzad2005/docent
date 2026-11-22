"""Inviting people to a Collection (GLOSSARY: Invite; FLOWS: Share).

Docent sends no email (PRD decision log, 2026-11-22). The Owner copies the invite's link and
passes it on; the link is only the invite's id, which grants nothing without signing in as the
invited address. Signing in as that address accepts it, through the link or not
(library.ensure_user); an accepted invite stays, so its link keeps leading to the Collection.
"""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api.collection_settings import require_owner

InviteRole = Literal["editor", "viewer"]
INVITE_DAYS = 14  # the column default in migration 0014
# Deliberately loose: one @, something either side, a dot in the domain. Signing in proves it.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class InviteSummary(BaseModel):
    id: UUID
    email: str
    role: InviteRole
    expires_at: datetime


class BadEmail(Exception):
    """Not an email address, or the Owner's own; the message says which."""


class AlreadyMember(Exception):
    """Someone with that address already has access."""


class InviteNotFound(Exception):
    """No such invite, or it expired or was revoked."""


class WrongAccount(Exception):
    """The invite is for another address. Carries it, partly hidden, to say which."""

    def __init__(self, masked_email: str) -> None:
        super().__init__(masked_email)
        self.masked_email = masked_email


def normal_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        raise BadEmail("Enter an email address, like name@example.com.")
    return email


def invite(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID, email: str, role: InviteRole
) -> InviteSummary:
    """Invite `email` with `role`. Inviting the same address again updates its Role and gives
    it another 14 days, keeping its link; so does inviting someone again after they left."""
    email = normal_email(email)
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        own = conn.execute("select email from app.users where id = %s", (user_id,)).fetchone()
        if own and own["email"].lower() == email:
            raise BadEmail("That’s your own address: you already own this collection.")
        member = conn.execute(
            """
            select 1 from app.memberships m join app.users u on u.id = m.user_id
            where m.collection_id = %s and lower(u.email) = %s
            """,
            (collection_id, email),
        ).fetchone()
        if member:
            raise AlreadyMember(email)
        row = conn.execute(
            """
            insert into app.invites (collection_id, email, role, invited_by)
            values (%(collection)s, %(email)s, %(role)s, %(by)s)
            on conflict (collection_id, email) do update
            set role = excluded.role, invited_by = excluded.invited_by, created_at = now(),
                expires_at = now() + make_interval(days => %(days)s),
                accepted_by = null, accepted_at = null
            returning id, email, role, expires_at
            """,
            {
                "collection": collection_id,
                "email": email,
                "role": role,
                "by": user_id,
                "days": INVITE_DAYS,
            },
        ).fetchone()
    return InviteSummary.model_validate(row)


def list_invites(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID
) -> list[InviteSummary]:
    """The Collection's invites still waiting, newest first (its Owner)."""
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        rows = conn.execute(
            """
            select id, email, role, expires_at from app.invites
            where collection_id = %s and accepted_at is null and expires_at > now()
            order by created_at desc
            """,
            (collection_id,),
        ).fetchall()
    return [InviteSummary.model_validate(row) for row in rows]


def revoke_invite(conn: Connection[DictRow], user_id: UUID, invite_id: UUID) -> None:
    """Delete a waiting invite (its Collection's Owner); its link stops working."""
    with conn.transaction():
        row = conn.execute(
            "select collection_id from app.invites where id = %s and accepted_at is null",
            (invite_id,),
        ).fetchone()
        if row is None:
            raise InviteNotFound(invite_id)
        require_owner(conn, user_id, row["collection_id"])
        conn.execute("delete from app.invites where id = %s", (invite_id,))


def accept_invite(conn: Connection[DictRow], user_id: UUID, email: str, invite_id: UUID) -> UUID:
    """Make the User a Member with the invite's Role; returns the Collection's id.

    Only for the invited address. Someone who is already a Member keeps their Role. Accepting
    again (signing in may have accepted it already) returns the Collection while they are still
    a Member of it.
    """
    with conn.transaction():
        row = conn.execute(
            """
            select collection_id, email, role, accepted_by from app.invites
            where id = %s and (accepted_at is not null or expires_at > now())
            for update
            """,
            (invite_id,),
        ).fetchone()
        if row is None:
            raise InviteNotFound(invite_id)
        if not email or row["email"] != email.lower():
            raise WrongAccount(mask(row["email"]))
        if row["accepted_by"] is None:
            conn.execute(
                """
                insert into app.memberships (collection_id, user_id, role) values (%s, %s, %s)
                on conflict (collection_id, user_id) do nothing
                """,
                (row["collection_id"], user_id, row["role"]),
            )
            conn.execute(
                "update app.invites set accepted_by = %s, accepted_at = now() where id = %s",
                (user_id, invite_id),
            )
        member = conn.execute(
            "select 1 from app.memberships where collection_id = %s and user_id = %s",
            (row["collection_id"], user_id),
        ).fetchone()
        if member is None:  # accepted once, and has left or been removed since
            raise InviteNotFound(invite_id)
    collection_id: UUID = row["collection_id"]
    return collection_id


def mask(email: str) -> str:
    """'s•••@example.com': enough for its owner to recognise, not enough to harvest."""
    name, _, domain = email.partition("@")
    return f"{name[:1]}•••@{domain}"
