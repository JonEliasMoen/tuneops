"""Inspect or copy the local TuneOps SQLite database to configured Turso.

The migration is resumable at table boundaries. A table is imported only when
its remote count is zero; a matching non-zero count is treated as already
completed, and every other mismatch stops the migration rather than merging
unknown data.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

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

from music_library.connection import TursoConnection, turso_configuration  # noqa: E402
from music_library.database import DATABASE_PATH, SCHEMA  # noqa: E402
from music_library.credentials import load_credentials  # noqa: E402


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def local_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def remote_connection():
    url, token = turso_configuration()
    connection = TursoConnection(url, token, timeout=60)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def local_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY rowid
            """
        )
    ]


def remote_tables() -> set[str]:
    with remote_connection() as connection:
        return {
            str(row["name"])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_schema
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }


def _count(connection: Any, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS amount FROM {_quote(table)}").fetchone()["amount"])


def counts() -> list[tuple[str, int, int | None]]:
    with local_connection() as local:
        tables = local_tables(local)
        local_counts = {table: _count(local, table) for table in tables}
    existing = remote_tables()
    result: list[tuple[str, int, int | None]] = []
    with remote_connection() as remote:
        for table in tables:
            remote_count = _count(remote, table) if table in existing else None
            result.append((table, local_counts[table], remote_count))
    return result


def print_counts(rows: Iterable[tuple[str, int, int | None]]) -> None:
    for table, local_count, remote_count in rows:
        remote_value = "missing" if remote_count is None else f"{remote_count:,}"
        print(f"{table}: local={local_count:,} remote={remote_value}")


def verify_remote_credentials() -> None:
    for provider in ("spotify", "tidal", "youtube"):
        payload = load_credentials(provider)
        if not payload:
            raise RuntimeError(f"{provider}: encrypted credential is missing")
        print(f"{provider}: encrypted credential decrypts successfully")


def ensure_remote_schema() -> None:
    with remote_connection() as connection:
        connection.executescript(SCHEMA)


def clear_remote_tables(tables: list[str]) -> None:
    # SCHEMA declares parents before their children, so reverse creation order
    # is a valid dependency-safe deletion order for the TuneOps schema.
    with remote_connection() as connection:
        for table in reversed(tables):
            connection.execute(f"DELETE FROM {_quote(table)}")
    print("Remote TuneOps rows cleared; schema retained.", flush=True)


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
    ]


def _insert_batch(
    remote: TursoConnection,
    table: str,
    columns: list[str],
    rows: list[sqlite3.Row],
) -> None:
    placeholders = "(" + ",".join("?" for _ in columns) + ")"
    sql = (
        f"INSERT INTO {_quote(table)} "
        f"({','.join(_quote(column) for column in columns)}) VALUES "
        + ",".join(placeholders for _ in rows)
    )
    parameters = [value for row in rows for value in tuple(row)]
    remote.execute(sql, parameters)


def migrate(batch_size: int = 250, *, replace: bool = False) -> None:
    with local_connection() as local:
        integrity = str(local.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"Local SQLite integrity check failed: {integrity}")
        tables = local_tables(local)

        ensure_remote_schema()
        if replace:
            clear_remote_tables(tables)
        existing = remote_tables()
        for table in tables:
            local_count = _count(local, table)
            with remote_connection() as remote:
                remote_count = _count(remote, table) if table in existing else 0
                if remote_count == local_count:
                    print(f"{table}: already complete ({local_count:,})")
                    continue
                if remote_count != 0:
                    raise RuntimeError(
                        f"{table}: refusing to merge local={local_count:,} "
                        f"with remote={remote_count:,}"
                    )
                columns = _columns(local, table)
                cursor = local.execute(
                    f"SELECT {','.join(_quote(column) for column in columns)} "
                    f"FROM {_quote(table)}"
                )
                copied = 0
                while batch := cursor.fetchmany(batch_size):
                    _insert_batch(remote, table, columns, batch)
                    copied += len(batch)
                    if copied == local_count or copied % 5_000 < batch_size:
                        print(f"{table}: copied {copied:,}/{local_count:,}", flush=True)

    mismatches = [row for row in counts() if row[1] != row[2]]
    if mismatches:
        print_counts(mismatches)
        raise RuntimeError("Turso row-count verification failed")
    verify_remote_credentials()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "migrate", "verify"))
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="clear known TuneOps rows in the configured Turso database first",
    )
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 1_000:
        parser.error("--batch-size must be between 1 and 1000")
    try:
        if args.mode == "inspect":
            print_counts(counts())
        elif args.mode == "migrate":
            migrate(args.batch_size, replace=args.replace)
            print("Migration complete: every application table count matches.")
        else:
            rows = counts()
            print_counts(rows)
            if any(local != remote for _, local, remote in rows):
                raise RuntimeError("Turso row-count verification failed")
            verify_remote_credentials()
            print("Verification complete: every application table count matches.")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
