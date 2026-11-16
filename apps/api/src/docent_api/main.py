"""HTTP entry point for the Docent API."""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api import __version__
from docent_api.auth import AuthUser, current_user
from docent_api.db import get_connection
from docent_api.library import CollectionSummary, ensure_user, list_collections

app = FastAPI(title="Docent API", version=__version__)


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class Me(BaseModel):
    email: str
    collections: list[CollectionSummary]


@app.get("/health", operation_id="getHealth", tags=["system"])
def health() -> Health:
    """Report that the API is running and which version is deployed."""
    return Health(status="ok", version=__version__)


@app.get("/health/database", operation_id="getDatabaseHealth", tags=["system"])
def database_health(conn: Annotated[Connection[DictRow], Depends(get_connection)]) -> Health:
    """Report that the database answers. Pinged on a schedule so the free database never pauses."""
    conn.execute("select 1")
    return Health(status="ok", version=__version__)


@app.get("/me", operation_id="getMe", tags=["library"])
def me(
    user: Annotated[AuthUser, Depends(current_user)],
    conn: Annotated[Connection[DictRow], Depends(get_connection)],
) -> Me:
    """The signed-in User and their Collections. Creates both on first sign-in."""
    ensure_user(conn, user)
    return Me(email=user.email, collections=list_collections(conn, user.id))
