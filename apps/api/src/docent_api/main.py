"""HTTP entry point for the Docent API."""

from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel, Field, field_validator

from docent_api import __version__
from docent_api.answers import (
    ConversationNotFound,
    answer,
    list_conversations,
    load_conversation,
    start_turn,
    to_sse,
)
from docent_api.auth import AuthUser, current_user
from docent_api.db import get_connection
from docent_api.documents import (
    DocumentNotFound,
    DocumentSummary,
    DuplicateDocument,
    NotAllowed,
    NotRetryable,
    UploadRejected,
    delete_document,
    finish_upload,
    list_documents,
    retry_document,
    set_effective_date,
    start_upload,
)
from docent_api.ingestion import run_batch
from docent_api.library import CollectionSummary, ensure_user, list_collections
from docent_api.providers.registry import answer_generator, embedder
from docent_api.retrieval import PassageNotFound, passage_in_context
from docent_api.scheduler import is_valid_trigger
from docent_api.storage import FileStore, StorageError, get_file_store

app = FastAPI(title="Docent API", version=__version__)

User = Annotated[AuthUser, Depends(current_user)]
Db = Annotated[Connection[DictRow], Depends(get_connection)]
Files = Annotated[FileStore, Depends(get_file_store)]

# Leaves room inside Vercel's 5-minute function limit for a last provider call (30 s timeout
# between chunks) and everything around the batch.
INGESTION_BATCH_SECONDS = 200.0

_NOT_FOUND = "That document doesn't exist."
_CANT_EDIT = "You can't add documents to this collection."
_CANT_CHANGE = "You can't change documents in this collection."


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


class UploadTarget(BaseModel):
    """Where the browser uploads the file, with Supabase's `uploadToSignedUrl`."""

    bucket: str
    path: str
    token: str


class StartedUpload(BaseModel):
    document: DocumentSummary
    upload: UploadTarget


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, question: str) -> str:
        question = question.strip()
        if not question:
            raise ValueError("Ask a question.")
        return question

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
    passage: str


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
        )
    except UploadRejected as rejected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(rejected)) from None
    except DuplicateDocument as duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, str(duplicate)) from None
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _CANT_EDIT) from None
    except StorageError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File storage isn't answering right now. Try again in a minute.",
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
    effective_date: date
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
            "Retrying won't help with this document. Fix the file and upload it again.",
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
  heading_path, page}]}`, the passages the answer may cite, numbered as in `[n]`
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
