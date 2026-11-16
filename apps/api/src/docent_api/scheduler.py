"""The database's scheduler, which keeps ingestion going when nobody has Docent open (ADR 0008).

Every minute, a pg_cron job checks for waiting Documents and, only if there are some, calls the
API's scheduled-ingestion endpoint through pg_net. The job authenticates with a token kept in
Supabase Vault; the API stores only the token's hash, so neither the token nor a way to forge it
appears in code, settings, or the job's definition.

    uv run docent-setup-scheduler --api-url https://<api host>

Run it again to rotate the token or change the API address.
"""

import argparse
import hashlib
import hmac
import secrets

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow

from docent_api.ingestion import ACTIVE_STATUSES, STALE_UPLOAD_HOURS
from docent_api.settings import get_settings

TOKEN_NAME = "ingestion_scheduler"
_VAULT_NAME = "docent_ingestion_trigger"
_JOB_NAME = "docent-ingestion"
# The API's batch runs about 200 s; let the request outlive it.
_REQUEST_TIMEOUT_MS = 290_000


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_valid_trigger(conn: Connection[DictRow], token: str) -> bool:
    """Whether `token` is the scheduler's current token. Compares in constant time."""
    row = conn.execute(
        "select token_hash from app.trigger_tokens where name = %s", (TOKEN_NAME,)
    ).fetchone()
    return row is not None and hmac.compare_digest(row["token_hash"], hash_token(token))


def set_trigger_token(conn: Connection[DictRow], token: str) -> None:
    conn.execute(
        """
        insert into app.trigger_tokens (name, token_hash) values (%s, %s)
        on conflict (name) do update set token_hash = excluded.token_hash, created_at = now()
        """,
        (TOKEN_NAME, hash_token(token)),
    )


def job_command(api_url: str) -> str:
    """The SQL the job runs each minute: call the API only when there is work waiting."""
    url = f"{api_url.rstrip('/')}/ingestion/scheduled".replace("'", "''")
    active = ", ".join(f"'{status}'" for status in ACTIVE_STATUSES)
    return f"""
        select net.http_post(
            url := '{url}',
            headers := jsonb_build_object(
                'Authorization',
                'Bearer ' || (
                    select decrypted_secret from vault.decrypted_secrets
                    where name = '{_VAULT_NAME}'
                )
            ),
            timeout_milliseconds := {_REQUEST_TIMEOUT_MS}
        )
        where exists (
            select 1 from app.documents
            where (status in ({active}) and (locked_until is null or locked_until < now()))
               or (status = 'uploading'
                   and created_at < now() - interval '{STALE_UPLOAD_HOURS} hours')
        )
    """


def set_up(conn: Connection[DictRow], api_url: str) -> None:
    token = secrets.token_urlsafe(32)
    with conn.transaction():
        conn.execute("create extension if not exists pg_cron")
        conn.execute("create extension if not exists pg_net")
        existing = conn.execute(
            "select id from vault.secrets where name = %s", (_VAULT_NAME,)
        ).fetchone()
        if existing:
            conn.execute("select vault.update_secret(%s, %s)", (existing["id"], token))
        else:
            conn.execute(
                "select vault.create_secret(%s, %s, %s)",
                (token, _VAULT_NAME, "Lets the scheduler start Docent ingestion batches"),
            )
        set_trigger_token(conn, token)
        conn.execute("select cron.schedule(%s, '* * * * *', %s)", (_JOB_NAME, job_command(api_url)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Schedule ingestion batches every minute.")
    parser.add_argument("--api-url", required=True, help="the deployed API, e.g. https://…")
    args = parser.parse_args()
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("Set DATABASE_URL first.")
    with psycopg.connect(
        database_url, prepare_threshold=None, row_factory=psycopg.rows.dict_row
    ) as conn:
        set_up(conn, args.api_url)
    print(f"Scheduled '{_JOB_NAME}' every minute, calling {args.api_url}; token rotated.")
