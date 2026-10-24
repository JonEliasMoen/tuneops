"""Create and verify a local SQLite backup of the configured Turso database.

The remote database is never modified. Turso's official CLI creates a logical
SQL dump, which is restored into a temporary SQLite file. The file is promoted
to the requested destination only after SQLite integrity, foreign-key, schema,
and row-count checks pass.

For an exact count verification, stop TuneOps writers while this command runs.
Use ``--database`` or ``TURSO_DATABASE_NAME`` for the Turso CLI database name.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_BACKUP_DIR = ROOT / "backups" / "database"
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


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

from music_library.connection import (  # noqa: E402
    TursoConnection,
    turso_configuration,
)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _database_name(value: str | None) -> str:
    name = str(value or os.getenv("TURSO_DATABASE_NAME") or "").strip()
    if not name:
        raise ValueError(
            "Provide --database or set TURSO_DATABASE_NAME to the Turso CLI "
            "database name."
        )
    if not DATABASE_NAME_PATTERN.fullmatch(name):
        raise ValueError("The Turso database name contains unsupported characters")
    return name


def _default_output() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_BACKUP_DIR / f"tuneops-turso-{stamp}.sqlite3"


def _dump_command(database: str, *, force_wsl: bool = False) -> list[str]:
    native = shutil.which("turso")
    if native and not force_wsl:
        return [native, "db", "shell", database, ".dump"]
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if wsl:
        # The database name is passed as a positional parameter rather than
        # interpolated into the shell program.
        return [
            wsl,
            "-e",
            "bash",
            "-lc",
            'exec turso db shell "$1" .dump',
            "tuneops-backup",
            database,
        ]
    raise RuntimeError(
        "Turso CLI was not found. Install/login to it, or run this script on "
        "a machine where the `turso` command is available."
    )


def _remote_counts() -> dict[str, int]:
    url, token = turso_configuration()
    schema = TursoConnection(url, token, timeout=60, read_only=True)
    rows = schema.execute(
        """
        SELECT name FROM sqlite_schema
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    tables = [str(row["name"]) for row in rows]
    if not tables:
        return {}
    connection = TursoConnection(url, token, timeout=60, read_only=True)
    cursors = connection.execute_batch([
        (f"SELECT COUNT(*) AS amount FROM {_quote(table)}", ())
        for table in tables
    ])
    return {
        table: int(cursor.fetchone()["amount"])
        for table, cursor in zip(tables, cursors, strict=True)
    }


def _create_dump(database: str, destination: Path, *, force_wsl: bool = False) -> None:
    command = _dump_command(database, force_wsl=force_wsl)
    with destination.open("wb") as stream:
        result = subprocess.run(
            command,
            stdout=stream,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "Turso CLI dump failed"
            + (f": {message[-1_000:]}" if message else "")
        )
    if destination.stat().st_size == 0:
        raise RuntimeError("Turso CLI returned an empty dump")


def _restore_dump(dump_path: Path, database_path: Path) -> None:
    connection = sqlite3.connect(database_path, timeout=60)
    pending = ""
    try:
        with dump_path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                pending += line
                if not sqlite3.complete_statement(pending):
                    continue
                statement = pending.strip()
                pending = ""
                if not statement:
                    continue
                if statement.startswith("."):
                    raise RuntimeError("The Turso dump contains an unsupported shell command")
                connection.execute(statement)
        if pending.strip():
            raise RuntimeError("The Turso dump ended with an incomplete SQL statement")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _local_counts(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path, timeout=30)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_schema
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        return {
            table: int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {_quote(table)}"
                ).fetchone()[0]
            )
            for table in tables
        }
    finally:
        connection.close()


def _verify_sqlite(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path, timeout=30)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"SQLite foreign-key check found {len(foreign_key_errors)} violation(s)"
            )
    finally:
        connection.close()
    return _local_counts(database_path)


def _verify_counts(
    before: dict[str, int], backup: dict[str, int], after: dict[str, int]
) -> None:
    if before != after:
        changed = sorted(
            table for table in set(before) | set(after)
            if before.get(table) != after.get(table)
        )
        raise RuntimeError(
            "Turso changed while the backup was running; stop writers and retry. "
            f"Changed tables: {', '.join(changed)}"
        )
    if backup != after:
        mismatches = sorted(
            table for table in set(backup) | set(after)
            if backup.get(table) != after.get(table)
        )
        raise RuntimeError(
            "Backup row-count verification failed for: " + ", ".join(mismatches)
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def backup(
    database: str,
    output: Path,
    *,
    force_wsl: bool = False,
) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    dump_file: Path | None = None
    restored_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.stem}-",
            suffix=".sql.partial",
            dir=output.parent,
            delete=False,
        ) as stream:
            dump_file = Path(stream.name)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.stem}-",
            suffix=".sqlite3.partial",
            dir=output.parent,
            delete=False,
        ) as stream:
            restored_file = Path(stream.name)

        before = _remote_counts()
        _create_dump(database, dump_file, force_wsl=force_wsl)
        _restore_dump(dump_file, restored_file)
        local = _verify_sqlite(restored_file)
        after = _remote_counts()
        _verify_counts(before, local, after)
        restored_file.replace(output)
        restored_file = None
        try:
            output.chmod(0o600)
        except OSError:
            pass
        return {
            "path": output,
            "tables": len(local),
            "rows": sum(local.values()),
            "bytes": output.stat().st_size,
            "sha256": _sha256(output),
        }
    finally:
        for temporary in (dump_file, restored_file):
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        help="Turso CLI database name (or set TURSO_DATABASE_NAME)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="new .sqlite3 backup path; defaults to backups/database with a timestamp",
    )
    parser.add_argument(
        "--wsl",
        action="store_true",
        help="use the Turso CLI installed inside WSL even if a native CLI exists",
    )
    args = parser.parse_args(argv)
    try:
        database = _database_name(args.database)
        result = backup(database, args.output or _default_output(), force_wsl=args.wsl)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Backup created: {result['path']}")
    print(
        f"Verified: {result['tables']:,} tables, {result['rows']:,} rows, "
        f"{result['bytes']:,} bytes"
    )
    print(f"SHA-256: {result['sha256']}")
    print(
        "Provider credentials in this backup remain encrypted; preserve "
        "TUNEOPS_CREDENTIAL_KEY separately."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
