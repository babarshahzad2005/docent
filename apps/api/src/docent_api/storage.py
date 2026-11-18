"""Original files, kept in a private Supabase Storage bucket (ADR 0006).

Browsers upload straight to storage with a one-time signed URL that the API issues after
checking permissions, so large files never pass through the API (Vercel caps request bodies).
Only the API, holding the secret key, can read or delete files.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx2

from docent_api.settings import get_settings

BUCKET = "documents"
BUCKET_SETTINGS = {"public": False, "file_size_limit": 20 * 1024 * 1024}
_TIMEOUT = httpx2.Timeout(60.0, connect=5.0)


class StorageError(Exception):
    """Storage refused or failed a request."""


class FileMissing(StorageError):
    """The file isn't in storage (never uploaded, or already deleted)."""


@dataclass(frozen=True)
class SignedUpload:
    """What a browser needs to upload one file: `supabase.storage.from(bucket)
    .uploadToSignedUrl(path, token, file)`."""

    bucket: str
    path: str
    token: str


class FileStore(Protocol):
    def signed_upload(self, path: str) -> SignedUpload: ...

    def download(self, path: str) -> bytes: ...

    def upload(self, path: str, data: bytes) -> None: ...

    def delete(self, paths: Sequence[str]) -> None: ...


class SupabaseFileStore:
    def __init__(
        self, supabase_url: str, secret_key: str, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self._base = f"{supabase_url.rstrip('/')}/storage/v1"
        self._headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}
        self._transport = transport

    def _client(self) -> httpx2.Client:
        return httpx2.Client(headers=self._headers, timeout=_TIMEOUT, transport=self._transport)

    def signed_upload(self, path: str) -> SignedUpload:
        with self._client() as client:
            response = self._send(client, "POST", f"/object/upload/sign/{BUCKET}/{path}")
        try:
            url = response.json()["url"]
            token = parse_qs(urlparse(url).query)["token"][0]
        except (ValueError, KeyError, IndexError) as error:
            raise StorageError("unexpected signed upload response") from error
        return SignedUpload(bucket=BUCKET, path=path, token=token)

    def download(self, path: str) -> bytes:
        with self._client() as client:
            return self._send(client, "GET", f"/object/{BUCKET}/{path}").content

    def upload(self, path: str, data: bytes) -> None:
        """Store a file directly (the server's own uploads, such as the Demo Collection)."""
        with self._client() as client:
            try:
                response = client.post(
                    f"{self._base}/object/{BUCKET}/{path}",
                    content=data,
                    headers={"x-upsert": "true", "content-type": "application/octet-stream"},
                )
            except httpx2.HTTPError as error:
                raise StorageError(f"storage unreachable: {error!r}") from error
        if response.status_code >= 400:
            raise StorageError(f"storage answered {response.status_code}: {response.text[:200]}")

    def delete(self, paths: Sequence[str]) -> None:
        if not paths:
            return
        with self._client() as client:
            self._send(client, "DELETE", f"/object/{BUCKET}", json={"prefixes": list(paths)})

    def ensure_bucket(self) -> bool:
        """Create the private bucket if it doesn't exist. Returns True if it was created."""
        with self._client() as client:
            existing = client.get(f"{self._base}/bucket/{BUCKET}")
            if existing.status_code == 200:
                self._send(client, "PUT", f"/bucket/{BUCKET}", json=BUCKET_SETTINGS)
                return False
            self._send(client, "POST", "/bucket", json={"id": BUCKET, **BUCKET_SETTINGS})
            return True

    def _send(
        self, client: httpx2.Client, method: str, url: str, json: object = None
    ) -> httpx2.Response:
        try:
            response = client.request(method, self._base + url, json=json)
        except httpx2.HTTPError as error:
            raise StorageError(f"storage unreachable: {error!r}") from error
        # Storage reports a missing object as 400 or 404 with "not_found" in the body.
        if response.status_code in (400, 404) and "not_found" in response.text.lower():
            raise FileMissing(url)
        if response.status_code >= 400:
            raise StorageError(f"storage answered {response.status_code}: {response.text[:200]}")
        return response


@lru_cache
def get_file_store() -> FileStore:
    settings = get_settings()
    return SupabaseFileStore(settings.supabase_url, settings.supabase_secret_key)


def main() -> None:
    """Create or update the private `documents` bucket: `uv run docent-setup-storage`."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise SystemExit("Set SUPABASE_URL and SUPABASE_SECRET_KEY first.")
    created = SupabaseFileStore(settings.supabase_url, settings.supabase_secret_key).ensure_bucket()
    print(f"Bucket '{BUCKET}' {'created' if created else 'already exists; settings checked'}.")
