"""HTTP entry point for the Docent API."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api import __version__
from docent_api.auth import AuthUser, current_user
from docent_api.db import get_connection
from docent_api.documents import (
    DocumentNotFound,
    DocumentSummary,
    NotAllowed,
    UploadRejected,
    finish_upload,
    list_documents,
    start_upload,
)
from docent_api.ingestion import run_batch
from docent_api.library import CollectionSummary, ensure_user, list_collections
from docent_api.providers.registry import embedder
from docent_api.storage import FileStore, StorageError, get_file_store

app = FastAPI(title="Docent API", version=__version__)

User = Annotated[AuthUser, Depends(current_user)]
Db = Annotated[Connection[DictRow], Depends(get_connection)]
Files = Annotated[FileStore, Depends(get_file_store)]

# Leaves a minute of Vercel's 5-minute function limit for everything around the batch.
INGESTION_BATCH_SECONDS = 240.0


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


class UploadTarget(BaseModel):
    """Where the browser uploads the file, with Supabase's `uploadToSignedUrl`."""

    bucket: str
    path: str
    token: str


class StartedUpload(BaseModel):
    document: DocumentSummary
    upload: UploadTarget


class IngestionRun(BaseModel):
    indexed: int
    failed: int
    remaining: int


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
    responses={400: {"description": "The file breaks an upload rule"}},
)
def new_document(body: NewDocument, user: User, conn: Db, files: Files) -> StartedUpload:
    """Add a Document: returns where to upload its file. Call `finishUpload` afterwards."""
    try:
        document, upload = start_upload(
            conn, files, user.id, body.collection_id, body.name, body.size_bytes
        )
    except UploadRejected as rejected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(rejected)) from None
    except NotAllowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't add documents to this collection."
        ) from None
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document doesn't exist.") from None


@app.post("/ingestion/run", operation_id="runIngestion", tags=["documents"])
def run_ingestion(user: User, conn: Db, files: Files) -> IngestionRun:
    """Process queued Documents for up to four minutes. Safe to call while another run is going."""
    result = run_batch(conn, files, embedder(), INGESTION_BATCH_SECONDS)
    return IngestionRun(indexed=result.indexed, failed=result.failed, remaining=result.remaining)
