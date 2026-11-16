"""HTTP entry point for the Docent API."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from docent_api import __version__

app = FastAPI(title="Docent API", version=__version__)


class Health(BaseModel):
    status: Literal["ok"]
    version: str


@app.get("/health", operation_id="getHealth", tags=["system"])
def health() -> Health:
    """Report that the API is running and which version is deployed."""
    return Health(status="ok", version=__version__)
