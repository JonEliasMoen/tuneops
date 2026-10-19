"""Inspect, import, and locally verify encrypted provider credentials.

This command never edits or removes the legacy credential files. It performs no
provider network calls and never prints credential values.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


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
# Auth migration intentionally precedes the Turso data migration. Override the
# backend for this process only, even if normal app traffic already targets
# Turso in the environment.
os.environ["TUNEOPS_DATABASE_BACKEND"] = "sqlite"

from music_library.credentials import (  # noqa: E402
    connection_metadata,
    current_user_id,
    load_credentials,
    load_or_import_file_credentials,
)
from music_library.database import DATABASE_PATH  # noqa: E402


SOURCES = {
    "spotify": ROOT / ".spotify_cache",
    "tidal": ROOT / ".tidal_session.json",
    "youtube": ROOT / ".youtube_oauth.json",
}


def _has_token(provider: str, payload: dict[str, Any]) -> bool:
    if provider == "tidal":
        return bool(payload.get("access_token") and payload.get("token_type"))
    return bool(payload.get("access_token") or payload.get("refresh_token"))


def inspect_provider(provider: str) -> dict[str, Any]:
    metadata = None
    if DATABASE_PATH.exists():
        connection = sqlite3.connect(
            f"file:{DATABASE_PATH.resolve().as_posix()}?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            has_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_connections'"
            ).fetchone()
            if has_table:
                metadata_row = connection.execute(
                    """
                    SELECT status, expires_at, credential_version
                    FROM provider_connections
                    WHERE user_id=? AND provider=?
                    """,
                    (current_user_id(), provider),
                ).fetchone()
                metadata = dict(metadata_row) if metadata_row else None
        finally:
            connection.close()
    return {
        "provider": provider,
        "legacy_file": SOURCES[provider].exists(),
        "database": metadata is not None,
        "status": str((metadata or {}).get("status") or "file only"),
        "expires_at": (metadata or {}).get("expires_at"),
        "credential_version": (metadata or {}).get("credential_version"),
    }


def migrate_provider(provider: str) -> str:
    if connection_metadata(provider) is not None:
        return "already in database"
    source = SOURCES[provider]
    if not source.exists():
        return "legacy file missing"
    payload = load_or_import_file_credentials(provider, source)
    if not payload or not _has_token(provider, payload):
        raise RuntimeError(f"{provider}: imported credential structure is invalid")
    return "imported and verified"


def verify_provider(provider: str) -> str:
    payload = load_credentials(provider)
    if payload is None:
        return "not in database"
    if not _has_token(provider, payload):
        raise RuntimeError(f"{provider}: stored credential structure is invalid")
    return "encrypted credential decrypts and is structurally valid"


def _print_inspection(row: dict[str, Any]) -> None:
    expiry = row["expires_at"] or "unknown"
    version = row["credential_version"] or "-"
    print(
        f"{row['provider']}: legacy_file={row['legacy_file']} "
        f"database={row['database']} status={row['status']} "
        f"expiry={expiry} version={version}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "migrate", "verify"))
    parser.add_argument("--user", help="Stable internal user UUID")
    args = parser.parse_args(argv)
    if args.user:
        os.environ["TUNEOPS_LOCAL_USER_ID"] = args.user

    # This phase deliberately targets the local SQLite file. Turso migration is
    # a separate, later operation with its own backup and count verification.
    current_user_id()  # fail early without revealing any credential data
    print(f"database: {DATABASE_PATH.name}")

    if args.mode == "inspect":
        for provider in SOURCES:
            _print_inspection(inspect_provider(provider))
        return 0

    operation = migrate_provider if args.mode == "migrate" else verify_provider
    failed = False
    for provider in SOURCES:
        try:
            print(f"{provider}: {operation(provider)}")
        except Exception as exc:
            failed = True
            print(f"{provider}: ERROR: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
