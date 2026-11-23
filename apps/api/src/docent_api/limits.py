"""Rate limits, kept in Postgres (FLOWS, Publish: Visitors are rate-limited per IP).

A Visitor's questions are counted per hour under a keyed hash of their network address, and
all Visitors' together per day, so a public link can't use up the free model quota that
signed-in Users share. Counting is one upsert per bucket: concurrent requests each add one,
and none is lost.

Network addresses are never stored (PRD decision log, 2026-11-15): only an HMAC of the
address, keyed by a server secret that isn't in the database, so the stored values can't be
reversed by trying every address. An IPv6 visitor is counted by their /64 network, since
one device can use any address in it.
"""

import hashlib
import hmac
import ipaddress
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from fastapi import Request
from psycopg import Connection
from psycopg.rows import DictRow

from docent_api.settings import get_settings

Period = Literal["hour", "day"]

# Rows this old can't be in any current window.
_KEEP = "2 days"


@dataclass
class RateLimited(Exception):
    """Over a limit; `retry_after` seconds until its window ends."""

    retry_after: int
    message: str


def client_address(request: Request) -> str:
    """The visitor's network address.

    On Vercel, `x-real-ip` is set by Vercel's own network, replacing anything the visitor
    sent, so it can be trusted there; elsewhere (local development) the socket's address is.
    """
    if os.environ.get("VERCEL"):
        forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@lru_cache
def _hash_key() -> bytes:
    settings = get_settings()
    if settings.visitor_hash_key:
        return settings.visitor_hash_key.encode()
    if settings.supabase_secret_key:
        # Derived from a secret the API already holds, so no new one needs setting up.
        return hmac.new(
            settings.supabase_secret_key.encode(), b"docent visitor address", hashlib.sha256
        ).digest()
    return secrets.token_bytes(32)  # local development: fresh each run, which is fine


def visitor_bucket(address: str) -> str:
    """The bucket a Visitor is counted in: a keyed hash, never the address itself."""
    try:
        ip = ipaddress.ip_address(address)
        if ip.version == 6:
            address = str(ipaddress.ip_network(f"{ip}/64", strict=False))
    except ValueError:
        pass  # not an address (no socket); hashed as it is
    digest = hmac.new(_hash_key(), address.encode(), hashlib.sha256).hexdigest()
    return f"visitor:{digest}"


def count(conn: Connection[DictRow], bucket: str, period: Period) -> tuple[int, int]:
    """Add one to `bucket` in the current window; its total so far, and the seconds until the
    window ends."""
    row = conn.execute(
        """
        insert into app.rate_limits (bucket, window_start)
        values (%(bucket)s, date_trunc(%(period)s, now(), 'UTC'))
        on conflict (bucket, window_start) do update set hits = app.rate_limits.hits + 1
        returning hits,
            ceil(extract(epoch from
                date_trunc(%(period)s, now(), 'UTC') + ('1 ' || %(period)s)::interval - now()
            ))::integer as retry_after
        """,
        {"bucket": bucket, "period": period},
    ).fetchone()
    assert row is not None
    return row["hits"], max(row["retry_after"], 1)


def check_visitor(conn: Connection[DictRow], address: str) -> None:
    """Count a Visitor's question, or raise RateLimited if they, or all Visitors today, have
    asked enough. A question counts once this returns, whatever happens to its answer; a
    refused one doesn't count (its transaction is rolled back)."""
    settings = get_settings()
    with conn.transaction():
        conn.execute(
            "delete from app.rate_limits where window_start < now() - %s::interval", (_KEEP,)
        )
        hits, retry_after = count(conn, visitor_bucket(address), "hour")
        if hits > settings.visitor_questions_per_hour:
            raise RateLimited(retry_after, _wait_message(retry_after))
        hits, retry_after = count(conn, "visitors:all", "day")
        if hits > settings.visitor_questions_per_day:
            raise RateLimited(
                retry_after,
                "Docent has answered as many public questions as it can today. Try again tomorrow.",
            )


def _wait_message(seconds: int) -> str:
    minutes = max(1, -(-seconds // 60))
    when = "a minute" if minutes == 1 else f"{minutes} minutes"
    return f"You’ve asked a lot of questions in a short time. Try again in {when}."
