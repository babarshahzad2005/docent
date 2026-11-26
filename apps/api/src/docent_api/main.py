"""HTTP entry point for the Docent API."""

from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import Connection
from psycopg.errors import ForeignKeyViolation
from psycopg.rows import DictRow
from pydantic import BaseModel, Field, field_validator

from docent_api import __version__
from docent_api.answers import (
    ConversationNotFound,
    answer,
    list_conversations,
    load_conversation,
    start_turn,
    start_visitor_turn,
    to_sse,
)
from docent_api.api_keys import (
    ApiKeyNotFound,
    ApiKeySummary,
    BadKeyName,
    NewApiKey,
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import (
    BadName,
    CollectionNotFound,
    FixedCollection,
    NotOwner,
    create_collection,
    delete_collection,
    rename_collection,
)
from docent_api.db import get_connection
from docent_api.documents import (
    DocumentNotFound,
    DocumentSummary,
    DuplicateDocument,
    NotAllowed,
    NotAMemberOf,
    NotMovable,
    NotRetryable,
    UploadRejected,
    delete_document,
    finish_upload,
    list_documents,
    move_document,
    retry_document,
    set_effective_date,
    start_upload,
)
from docent_api.ingestion import run_batch
from docent_api.invites import (
    AlreadyMember,
    BadEmail,
    InviteNotFound,
    InviteRole,
    InviteSummary,
    WrongAccount,
    accept_invite,
    invite,
    list_invites,
    revoke_invite,
)
from docent_api.library import CollectionSummary, ensure_user, list_collections
from docent_api.limits import RateLimited, client_address
from docent_api.members import (
    MemberRole,
    MemberSummary,
    NotAMember,
    NotShared,
    OwnerCantLeave,
    change_role,
    list_members,
    remove_member,
    transfer_ownership,
)
from docent_api.providers.registry import answer_generator, embedder
from docent_api.public import (
    PublicCollection,
    PublicCollectionNotFound,
    PublicState,
    demo_collection,
    public_collection,
    set_public,
)
from docent_api.retrieval import PassageNotFound, passage_in_context
from docent_api.scheduler import is_valid_trigger
from docent_api.settings import get_settings
from docent_api.storage import FileStore, StorageError, get_file_store

app = FastAPI(title="Docent API", version=__version__)
# A Visitor's browser asks Public Collections directly (#94). Nothing here relies on cookies:
# signed-in calls carry a bearer token the browser never sends by itself.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().web_origins.split(",") if o.strip()],
    allow_origin_regex=get_settings().web_origin_pattern or None,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After"],
)

User = Annotated[AuthUser, Depends(current_user)]
Db = Annotated[Connection[DictRow], Depends(get_connection)]
Files = Annotated[FileStore, Depends(get_file_store)]

# Leaves room inside Vercel's 5-minute function limit for a last provider call (30 s timeout
# between chunks) and everything around the batch.
INGESTION_BATCH_SECONDS = 200.0

_NOT_FOUND = "That document doesn't exist."
# GLOSSARY: Role. A Viewer can only ask; the refusal says who can, and how to become one.
_CANT_EDIT = (
    "Only this collection’s owner and editors can add documents. "
    "Ask its owner to make you an editor."
)
_CANT_CHANGE = (
    "Only this collection’s owner and editors can change its documents. "
    "Ask its owner to make you an editor."
)


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class Me(BaseModel):
    email: str
    collections: list[CollectionSummary]


class NewDocument(BaseModel):
    collection_id: UUID
    name: str
    size_bytes: int
    sha256: str
    """The file's SHA-256 in hex, to notice the same file uploaded twice."""
    allow_duplicate: bool = False
    """Keep both when the Collection already has a Document with the same content."""
    replaces: UUID | None = None
    """Replace this Document with the file: it keeps answering until the new one is indexed."""


class UploadTarget(BaseModel):
    """Where the browser uploads the file, with Supabase's `uploadToSignedUrl`."""

    bucket: str
    path: str
    token: str


class StartedUpload(BaseModel):
    document: DocumentSummary
    upload: UploadTarget


class VisitorQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, question: str) -> str:
        question = question.strip()
        if not question:
            raise ValueError("Ask a question.")
        return question


class Question(VisitorQuestion):
    conversation_id: UUID | None = None
    """Continue this Conversation; a new one starts when omitted."""
    scope: list[UUID] | None = None
    """The Collections to answer from; all of the User's when omitted."""


class CitationOut(BaseModel):
    number: int
    chunk_id: UUID | None
    """The passage it cites, while it still exists; None once its Document is deleted."""
    document_id: UUID | None
    document_name: str
    heading_path: list[str]
    page: int | None
    passage: str | None
    """What it said when the answer was given; None once the User has lost access to it."""
    access_lost: bool = False
    """The User can no longer read its Collection: its passage is hidden (PRD decision log)."""


class ConflictVersion(BaseModel):
    """One Document's side when Documents disagree."""

    number: int
    value: str
    document_name: str
    effective_date: date | None


class RemovedClaim(BaseModel):
    text: str
    reason: str
    original: str


class MessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal["streaming", "complete", "interrupted", "failed"]
    scope: list[UUID]
    """The Collections the question was answered from."""
    outcome: Literal["answered", "declined", "unverified", "no_documents"] | None
    """How a finished answer ended; for a Decline, its Citations are the closest passages."""
    verified: bool
    """The answer's Citations were checked against their passages (ADR 0007)."""
    removed: list[RemovedClaim]
    """Claims removed from the answer because their Citations couldn't be verified."""
    conflict: list[ConflictVersion] | None = None
    """When the answer's Documents disagree: each version, newest first (#48)."""
    created_at: datetime
    citations: list[CitationOut]


class PassageOut(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    heading_path: list[str]
    page: int | None
    content: str
    before: str | None
    """The passage just before, in the same Document and section, for context."""
    after: str | None
    replaced: bool = False
    """The Document has been Replaced since: this is the passage as it was (ADR 0004)."""


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    updated_at: datetime


class ConversationOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    messages: list[MessageOut]


class IngestionRun(BaseModel):
    indexed: int
    failed: int
    remaining: int
    ran: bool


@app.get("/health", operation_id="getHealth", tags=["system"])
def health() -> Health:
    """Report that the API is running and which version is deployed."""
    return Health(status="ok", version=__version__)


@app.get("/health/database", operation_id="getDatabaseHealth", tags=["system"])
def database_health(conn: Db) -> Health:
    """Report that the database answers. Pinged on a schedule so the free database never pauses."""
    conn.execute("select 1")
    return Health(status="ok", version=__version__)


@app.get("/me", operation_id="getMe", tags=["library"])
def me(user: User, conn: Db) -> Me:
    """The signed-in User and their Collections. Creates both on first sign-in."""
    ensure_user(conn, user)
    return Me(email=user.email, collections=list_collections(conn, user.id))


class PublicSetting(BaseModel):
    public: bool
    expires_in_days: Literal[1, 7, 30] | None = None
    """Stop being public after this many days; never, when omitted."""


class CollectionName(BaseModel):
    name: str = Field(max_length=500)
    """1 to 120 characters once spaces are tidied."""


_COLLECTION_NOT_FOUND = (
    "That collection doesn’t exist, or you no longer have access to it. Reload the page."
)
_FIXED = "Your Personal Collection and the Demo Collection can’t be renamed or deleted."
_NOT_OWNER = "Only the collection’s owner can do that. Ask them if it needs doing."


@app.post(
    "/collections",
    operation_id="createCollection",
    tags=["library"],
    status_code=status.HTTP_201_CREATED,
    responses={400: {"description": "The name is empty or too long"}},
)
def new_collection(body: CollectionName, user: User, conn: Db) -> CollectionSummary:
    """Create an empty Collection, owned by the signed-in User."""
    ensure_user(conn, user)
    try:
        return create_collection(conn, user.id, body.name)
    except BadName as bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(bad)) from None


@app.patch(
    "/collections/{collection_id}",
    operation_id="renameCollection",
    tags=["library"],
    responses={
        400: {"description": "The name is empty or too long"},
        403: {"description": "Only the Owner can rename it"},
        404: {"description": "No such Collection, or not a Member"},
        409: {"description": "The Personal or Demo Collection"},
    },
)
def rename(collection_id: UUID, body: CollectionName, user: User, conn: Db) -> CollectionSummary:
    """Rename a Collection (its Owner)."""
    try:
        return rename_collection(conn, user.id, collection_id, body.name)
    except BadName as bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(bad)) from None
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(status.HTTP_409_CONFLICT, _FIXED) from None


@app.put(
    "/collections/{collection_id}/public",
    operation_id="setCollectionPublic",
    tags=["public"],
    responses={
        403: {"description": "Only the Owner can make it public"},
        404: {"description": "No such Collection, or not a Member"},
        409: {"description": "The Personal or Demo Collection"},
    },
)
def make_public(collection_id: UUID, body: PublicSetting, user: User, conn: Db) -> PublicState:
    """Let anyone with the link ask a Collection without signing in, or stop (its Owner)."""
    try:
        return set_public(conn, user.id, collection_id, body.public, body.expires_in_days)
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This collection can’t be made public. Personal collections are always private.",
        ) from None


@app.delete(
    "/collections/{collection_id}",
    operation_id="deleteCollection",
    tags=["library"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "Only the Owner can delete it"},
        409: {"description": "The Personal or Demo Collection"},
    },
)
def remove_collection(collection_id: UUID, user: User, conn: Db, files: Files) -> None:
    """Delete a Collection with all its Documents (its Owner). Repeating the call is harmless,
    so a Collection that is gone, or never visible to the User, answers 204 like `delete`."""
    try:
        delete_collection(conn, files, user.id, collection_id)
    except CollectionNotFound:
        return  # already gone, or never visible to this User
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(status.HTTP_409_CONFLICT, _FIXED) from None


class NewInvite(BaseModel):
    email: str = Field(max_length=500)
    role: InviteRole


_NOT_SHARABLE = (
    "Your Personal Collection is private, and the Demo Collection can\u2019t be shared. "
    "Create a collection to share."
)
_INVITE_GONE = (
    "This invite has expired or was cancelled. Ask the person who invited you for a new one."
)


@app.get(
    "/collections/{collection_id}/invites",
    operation_id="listInvites",
    tags=["sharing"],
    responses={
        403: {"description": "Only the Owner sees invites"},
        404: {"description": "No such Collection, or not a Member"},
    },
)
def invites(collection_id: UUID, user: User, conn: Db) -> list[InviteSummary]:
    """The Collection's invites still waiting (its Owner)."""
    try:
        return list_invites(conn, user.id, collection_id)
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        return []


@app.post(
    "/collections/{collection_id}/invites",
    operation_id="inviteToCollection",
    tags=["sharing"],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Not an email address, or the Owner's own"},
        403: {"description": "Only the Owner invites"},
        404: {"description": "No such Collection, or not a Member"},
        409: {"description": "Already has access, or the Collection can't be shared"},
    },
)
def new_invite(collection_id: UUID, body: NewInvite, user: User, conn: Db) -> InviteSummary:
    """Invite an email address with a Role. Docent sends no email: pass on the invite's link."""
    try:
        return invite(conn, user.id, collection_id, body.email, body.role)
    except BadEmail as bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(bad)) from None
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SHARABLE) from None
    except AlreadyMember as member:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{member} already has access to this collection."
        ) from None


class ApiKeyName(BaseModel):
    name: str = Field(max_length=500)


_NO_KEYS = (
    "Your Personal Collection and the Demo Collection can’t have API keys. "
    "Create a collection to use the API."
)


@app.get(
    "/collections/{collection_id}/api-keys",
    operation_id="listApiKeys",
    tags=["api keys"],
    responses={
        403: {"description": "Only the Owner sees API Keys"},
        404: {"description": "No such Collection, or not a Member"},
    },
)
def api_keys(collection_id: UUID, user: User, conn: Db) -> list[ApiKeySummary]:
    """The Collection's API Keys, without their secrets (its Owner)."""
    try:
        return list_api_keys(conn, user.id, collection_id)
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        return []


@app.post(
    "/collections/{collection_id}/api-keys",
    operation_id="createApiKey",
    tags=["api keys"],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "The name is empty or too long"},
        403: {"description": "Only the Owner creates API Keys"},
        404: {"description": "No such Collection, or not a Member"},
        409: {"description": "The Personal or Demo Collection"},
    },
)
def new_api_key(collection_id: UUID, body: ApiKeyName, user: User, conn: Db) -> NewApiKey:
    """Create an API Key that can only ask this Collection. Its secret is in this response
    only: Docent stores a hash of it and can't show it again."""
    try:
        return create_api_key(conn, user.id, collection_id, body.name)
    except BadKeyName as bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(bad)) from None
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(status.HTTP_409_CONFLICT, _NO_KEYS) from None


@app.delete(
    "/api-keys/{key_id}",
    operation_id="revokeApiKey",
    tags=["api keys"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={403: {"description": "Only the Owner revokes API Keys"}},
)
def revoke_key(key_id: UUID, user: User, conn: Db) -> None:
    """Revoke an API Key; it stops working at once. Repeating the call is harmless."""
    try:
        revoke_api_key(conn, user.id, key_id)
    except (ApiKeyNotFound, CollectionNotFound):
        return
    except (NotOwner, FixedCollection):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None


@app.delete(
    "/invites/{invite_id}",
    operation_id="revokeInvite",
    tags=["sharing"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={403: {"description": "Only the Owner cancels invites"}},
)
def cancel_invite(invite_id: UUID, user: User, conn: Db) -> None:
    """Cancel an invite; its link stops working. Repeating the call is harmless."""
    try:
        revoke_invite(conn, user.id, invite_id)
    except (InviteNotFound, CollectionNotFound):
        return
    except (NotOwner, FixedCollection):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None


@app.post(
    "/invites/{invite_id}/accept",
    operation_id="acceptInvite",
    tags=["sharing"],
    responses={
        403: {"description": "The invite is for another address"},
        404: {"description": "Expired, cancelled, or never existed"},
    },
)
def accept(invite_id: UUID, user: User, conn: Db) -> CollectionSummary:
    """Join the invite's Collection as the invited address; returns the Collection."""
    ensure_user(conn, user)  # a first sign-in may arrive here: the User must exist
    try:
        collection_id = accept_invite(conn, user.id, user.email, invite_id)
    except InviteNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _INVITE_GONE) from None
    except WrongAccount as wrong:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This invite is for {wrong.masked_email}. Sign out, then sign in with that "
            "address to accept it.",
        ) from None
    joined = next((c for c in list_collections(conn, user.id) if c.id == collection_id), None)
    if joined is None:  # removed again in the moment since
        raise HTTPException(status.HTTP_404_NOT_FOUND, _INVITE_GONE)
    return joined


class RoleChange(BaseModel):
    role: MemberRole


class NewOwner(BaseModel):
    user_id: UUID


_NOT_A_MEMBER = "That person doesn\u2019t have access to this collection any more. Reload the page."
_NOT_SHARED = "Your Personal Collection and the Demo Collection have no members to manage."
_OWNER_CANT_LEAVE = (
    "You own this collection. Make someone else the owner first, or delete the collection."
)


@app.get(
    "/collections/{collection_id}/members",
    operation_id="listMembers",
    tags=["sharing"],
    responses={
        404: {"description": "No such Collection, or not a Member"},
        409: {"description": "The Personal or Demo Collection"},
    },
)
def members(collection_id: UUID, user: User, conn: Db) -> list[MemberSummary]:
    """Everyone with access to the Collection and their Roles, Owner first (any Member)."""
    try:
        return list_members(conn, user.id, collection_id)
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotShared:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SHARED) from None


@app.patch(
    "/collections/{collection_id}/members/{member_id}",
    operation_id="changeRole",
    tags=["sharing"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "Only the Owner changes Roles"},
        404: {"description": "No such Collection or Member"},
    },
)
def role(collection_id: UUID, member_id: UUID, body: RoleChange, user: User, conn: Db) -> None:
    """Make a Member an Editor or a Viewer (the Owner)."""
    try:
        change_role(conn, user.id, collection_id, member_id, body.role)
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SHARED) from None
    except NotAMember:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_A_MEMBER) from None


@app.delete(
    "/collections/{collection_id}/members/{member_id}",
    operation_id="removeMember",
    tags=["sharing"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "Only the Owner removes others"},
        404: {"description": "No such Collection or Member"},
        409: {"description": "The Owner can't leave; or the Personal or Demo Collection"},
    },
)
def remove(collection_id: UUID, member_id: UUID, user: User, conn: Db) -> None:
    """Remove a Member (the Owner), or leave: pass your own id (anyone but the Owner)."""
    try:
        remove_member(conn, user.id, collection_id, member_id)
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SHARED) from None
    except NotAMember:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_A_MEMBER) from None
    except OwnerCantLeave:
        raise HTTPException(status.HTTP_409_CONFLICT, _OWNER_CANT_LEAVE) from None
    except NotShared:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SHARED) from None


@app.post(
    "/collections/{collection_id}/owner",
    operation_id="transferOwnership",
    tags=["sharing"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "Only the Owner transfers ownership"},
        404: {"description": "No such Collection or Member"},
    },
)
def transfer(collection_id: UUID, body: NewOwner, user: User, conn: Db) -> None:
    """Make another Member the Owner; you stay, as an Editor."""
    try:
        transfer_ownership(conn, user.id, collection_id, body.user_id)
    except CollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_OWNER) from None
    except FixedCollection:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_SHARED) from None
    except NotAMember:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_A_MEMBER) from None


@app.get("/documents", operation_id="listDocuments", tags=["documents"])
def documents(user: User, conn: Db) -> list[DocumentSummary]:
    """Every Document in the signed-in User's Collections, newest first."""
    return list_documents(conn, user.id)


@app.post(
    "/documents",
    operation_id="startUpload",
    tags=["documents"],
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "The file breaks an upload rule"},
        409: {"description": "The Collection already has a Document with this content"},
    },
)
def new_document(body: NewDocument, user: User, conn: Db, files: Files) -> StartedUpload:
    """Add a Document: returns where to upload its file. Call `finishUpload` afterwards."""
    try:
        document, upload = start_upload(
            conn,
            files,
            user.id,
            body.collection_id,
            body.name,
            body.size_bytes,
            sha256=body.sha256,
            allow_duplicate=body.allow_duplicate,
            replaces=body.replaces,
        )
    except UploadRejected as rejected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(rejected)) from None
    except DuplicateDocument as duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, str(duplicate)) from None
    except NotAMemberOf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _CANT_EDIT) from None
    except DocumentNotFound:  # the Document to replace
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document doesn’t exist.") from None
    except ForeignKeyViolation:  # its Collection was deleted while the upload started
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except StorageError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File storage isn\u2019t answering right now. Try again in a minute.",
        ) from None
    return StartedUpload(
        document=document,
        upload=UploadTarget(bucket=upload.bucket, path=upload.path, token=upload.token),
    )


@app.post("/documents/{document_id}/uploaded", operation_id="finishUpload", tags=["documents"])
def uploaded(document_id: UUID, user: User, conn: Db) -> DocumentSummary:
    """The file is stored: queue the Document for ingestion."""
    try:
        return finish_upload(conn, user.id, document_id)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND) from None
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _CANT_EDIT) from None


@app.delete(
    "/documents/{document_id}",
    operation_id="deleteDocument",
    tags=["documents"],
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete(document_id: UUID, user: User, conn: Db, files: Files) -> None:
    """Delete a Document with its file, passages, and vectors. Repeating the call is harmless."""
    try:
        delete_document(conn, files, user.id, document_id)
    except DocumentNotFound:
        return  # already gone
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _CANT_CHANGE) from None


class DocumentChanges(BaseModel):
    # Bounded, because it orders Documents that disagree: a typo like 9999 would win always.
    effective_date: Annotated[date, Field(ge=date(1900, 1, 1), le=date(2100, 12, 31))]
    """The date the Document's content applies from (GLOSSARY: Effective Date)."""


@app.patch("/documents/{document_id}", operation_id="updateDocument", tags=["documents"])
def update(document_id: UUID, changes: DocumentChanges, user: User, conn: Db) -> DocumentSummary:
    """Change a Document's Effective Date (Owners and Editors)."""
    try:
        return set_effective_date(conn, user.id, document_id, changes.effective_date)
    except DocumentNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That document doesn\u2019t exist."
        ) from None
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _CANT_CHANGE) from None


class Destination(BaseModel):
    collection_id: UUID
    """The Collection to move the Document to."""


@app.post(
    "/documents/{document_id}/move",
    operation_id="moveDocument",
    tags=["documents"],
    responses={
        403: {"description": "Not an Owner or Editor of both Collections"},
        404: {"description": "No such Document or Collection, or not a Member"},
        409: {"description": "Not settled yet, or the destination has the same content"},
    },
)
def move(document_id: UUID, body: Destination, user: User, conn: Db) -> DocumentSummary:
    """Move a Document, with its passages, to another Collection (Owner or Editor of both)."""
    try:
        return move_document(conn, user.id, document_id, body.collection_id)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND) from None
    except NotAMemberOf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _COLLECTION_NOT_FOUND) from None
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _CANT_MOVE) from None
    except (NotMovable, DuplicateDocument) as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None


_CANT_MOVE = (
    "You can move documents only between collections where you\u2019re an owner or editor, "
    "and never into or out of the Demo Collection."
)


@app.post("/documents/{document_id}/retry", operation_id="retryDocument", tags=["documents"])
def retry(document_id: UUID, user: User, conn: Db) -> DocumentSummary:
    """Queue a failed Document again, when retrying could help."""
    try:
        return retry_document(conn, user.id, document_id)
    except DocumentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND) from None
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _CANT_CHANGE) from None
    except NotRetryable:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Retrying won\u2019t help with this document. Fix the file and upload it again.",
        ) from None


@app.post("/ingestion/run", operation_id="runIngestion", tags=["documents"])
def run_ingestion(user: User, conn: Db, files: Files) -> IngestionRun:
    """Process queued Documents for a few minutes. Returns at once if a batch is already running,
    so calling it again can't multiply the work."""
    return _run_batch(conn, files)


_scheduler_bearer = HTTPBearer(auto_error=False)


@app.post("/ingestion/scheduled", include_in_schema=False)
def scheduled_ingestion(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_scheduler_bearer)],
    conn: Db,
    files: Files,
) -> IngestionRun:
    """Called every minute by the database's scheduler, and by nothing else (see scheduler.py)."""
    if credentials is None or not is_valid_trigger(conn, credentials.credentials):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not the scheduler.")
    return _run_batch(conn, files)


def _run_batch(conn: Connection[DictRow], files: FileStore) -> IngestionRun:
    result = run_batch(conn, files, embedder(), INGESTION_BATCH_SECONDS)
    return IngestionRun(
        indexed=result.indexed, failed=result.failed, remaining=result.remaining, ran=result.ran
    )


_SSE_DESCRIPTION = """Server-sent events, in order:

- `start`: `{conversation_id, message_id, sources: [{number, document_id, document_name,
  heading_path, page}]}`, the passages the answer may cite, numbered as in `[n]`;
  `conversation_id` and `message_id` are null for a Visitor, whose answers aren't saved
- `delta`: `{text}`, the next piece of the answer
- `done`: `{message_id, outcome: "answered" | "declined", cited: [n, ...]}`
- `error`: `{message, partial}`, the answer stopped; `partial` if some text was sent
"""


@app.post(
    "/answers",
    operation_id="askQuestion",
    tags=["answers"],
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": _SSE_DESCRIPTION},
        404: {"description": "No such Conversation"},
    },
)
async def ask(body: Question, user: User) -> StreamingResponse:
    """Answer a question from the User's Documents, streamed, citing passages as [n]."""
    try:
        turn = await start_turn(user.id, body.question, body.conversation_id, body.scope)
    except ConversationNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That conversation doesn\u2019t exist."
        ) from None

    async def events() -> AsyncIterator[str]:
        generator = answer_generator()
        async for event in answer(turn, embedder(), generator, rewriter=generator):
            yield to_sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Keep proxies from buffering, so each piece reaches the reader as it is written.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.get("/conversations", operation_id="listConversations", tags=["answers"])
def conversations(
    user: User, conn: Db, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[ConversationSummary]:
    """The User's Conversations, most recently active first."""
    return [ConversationSummary.model_validate(c) for c in list_conversations(conn, user.id, limit)]


@app.get("/conversations/{conversation_id}", operation_id="getConversation", tags=["answers"])
def conversation(conversation_id: UUID, user: User, conn: Db) -> ConversationOut:
    """A saved Conversation with its answers and their Citations."""
    try:
        return ConversationOut.model_validate(load_conversation(conn, user.id, conversation_id))
    except ConversationNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That conversation doesn\u2019t exist."
        ) from None


@app.get("/passages/{chunk_id}", operation_id="getPassage", tags=["answers"])
def passage(chunk_id: UUID, user: User, conn: Db) -> PassageOut:
    """A passage the User can read, with its neighbours, for showing a Citation in context."""
    try:
        return PassageOut.model_validate(passage_in_context(conn, user.id, chunk_id))
    except PassageNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That passage isn\u2019t available any more."
        ) from None


# --- Public Collections: no sign-in (GLOSSARY: Visitor) --------------------------------------

_UNAVAILABLE = "This collection isn’t available. Its owner may have stopped sharing it."


# Declared before "/public/{collection_id}", which would otherwise take "demo" as an id.
@app.get(
    "/public/demo",
    operation_id="getDemoCollection",
    tags=["public"],
    responses={404: {"description": "The Demo Collection isn't seeded yet"}},
)
def public_demo(conn: Db) -> PublicCollection:
    """The Demo Collection, which anyone can ask without signing in."""
    try:
        return demo_collection(conn)
    except PublicCollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The demo isn’t set up yet.") from None


@app.get(
    "/public/{collection_id}",
    operation_id="getPublicCollection",
    tags=["public"],
    responses={404: {"description": "No such Collection, or it isn't public now"}},
)
def public_info(collection_id: UUID, conn: Db) -> PublicCollection:
    """A Public Collection's name, for a Visitor."""
    try:
        return public_collection(conn, collection_id)
    except PublicCollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _UNAVAILABLE) from None


@app.post(
    "/public/{collection_id}/answers",
    operation_id="askPublicCollection",
    tags=["public"],
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": _SSE_DESCRIPTION},
        404: {"description": "No such Collection, or it isn't public now"},
        429: {"description": "Too many questions; `Retry-After` says when to ask again"},
    },
)
async def ask_public(
    collection_id: UUID, body: VisitorQuestion, request: Request
) -> StreamingResponse:
    """Answer a Visitor's question from a Public Collection, streamed like `POST /answers`.

    Nothing is saved but the Answer Log entry; each question stands alone. Rate-limited per
    network address and across all Visitors (limits.py); only questions to a Collection that
    is public count.
    """
    try:
        turn = await start_visitor_turn(collection_id, body.question, client_address(request))
    except PublicCollectionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _UNAVAILABLE) from None
    except RateLimited as limited:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            limited.message,
            headers={"Retry-After": str(limited.retry_after)},
        ) from None

    async def events() -> AsyncIterator[str]:
        async for event in answer(turn, embedder(), answer_generator()):
            yield to_sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.get(
    "/public/{collection_id}/passages/{chunk_id}",
    operation_id="getPublicPassage",
    tags=["public"],
    responses={404: {"description": "Not in this Collection, or it isn't public now"}},
)
def public_passage(collection_id: UUID, chunk_id: UUID, conn: Db) -> PassageOut:
    """A passage of a Public Collection with its neighbours, for a Visitor's Citation."""
    try:
        return PassageOut.model_validate(
            passage_in_context(conn, None, chunk_id, public_collection=collection_id)
        )
    except PassageNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That passage isn’t available any more."
        ) from None
