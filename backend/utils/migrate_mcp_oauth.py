"""Explicit schema-v2 to schema-v3 migration for TuneOps-managed MCP OAuth."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT / ".env")

from backend.music_library.database import connect, connect_readonly


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS oauth_authorization_transactions (
 state_hash TEXT PRIMARY KEY, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
 redirect_uri_provided INTEGER NOT NULL, code_challenge TEXT NOT NULL,
 scopes_json TEXT NOT NULL, resource TEXT, client_state TEXT,
 google_nonce TEXT NOT NULL, google_code_verifier TEXT NOT NULL,
 expires_at INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
 code_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_id TEXT NOT NULL,
 redirect_uri TEXT NOT NULL, redirect_uri_provided INTEGER NOT NULL,
 code_challenge TEXT NOT NULL, scopes_json TEXT NOT NULL, resource TEXT,
 expires_at INTEGER NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS oauth_token_grants (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_id TEXT NOT NULL,
 scopes_json TEXT NOT NULL, resource TEXT, refresh_token_hash TEXT NOT NULL UNIQUE,
 refresh_expires_at INTEGER NOT NULL, revoked_at TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS oauth_access_tokens (
 token_hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL, expires_at INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY (grant_id) REFERENCES oauth_token_grants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS oauth_access_tokens_by_grant
 ON oauth_access_tokens(grant_id);
"""


def schema_version() -> int:
    with connect_readonly() as connection:
        row = connection.execute(
            "SELECT schema_version FROM app_schema_meta WHERE singleton=1"
        ).fetchone()
    if row is None:
        raise RuntimeError("TuneOps schema metadata is missing")
    return int(row["schema_version"])


def migrate() -> None:
    version = schema_version()
    if version == 3:
        return
    if version != 2:
        raise RuntimeError(f"Expected schema version 2; found {version}")
    with connect() as connection:
        connection.executescript(MIGRATION_SQL)
        connection.execute(
            "UPDATE app_schema_meta SET schema_version=3, updated_at=? WHERE singleton=1",
            (datetime.now(timezone.utc).isoformat(),),
        )
    if schema_version() != 3:
        raise RuntimeError("MCP OAuth migration verification failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    current = schema_version()
    print(f"Configured database schema version: {current}")
    if not args.apply:
        print("Dry run only. Rerun with --apply after stopping TuneOps and taking a backup.")
        return
    migrate()
    print("MCP OAuth schema migration complete: version 3.")


if __name__ == "__main__":
    main()
