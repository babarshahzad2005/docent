"""HTTP entry point for the Docent API."""

import os
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from docent_api import __version__

app = FastAPI(title="Docent API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("WEB_BASE_URL", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class Health(BaseModel):
    status: Literal["ok"]
    version: str


@app.get("/health", operation_id="getHealth", tags=["system"])
def health() -> Health:
    """Report that the API is running and which version is deployed."""
    return Health(status="ok", version=__version__)
