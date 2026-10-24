"""DB-API-shaped connections for local SQLite and remote Turso/libSQL.

The application repository is intentionally synchronous.  Turso is accessed
through Hrana's HTTP v3 pipeline so the same code works in stateless Vercel
functions and on the local Python 3.14 installation, where the native libSQL
wheel is not currently available.
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from music_library.telemetry import record_connection, record_database_call


LOGGER = logging.getLogger("musicsync")
SLOW_DATABASE_MS = 250.0


def _record_timing(
    elapsed_ms: float,
    *,
    backend: str,
    operation: str,
    statements: int = 0,
    pipeline_calls: int = 0,
) -> None:
    record_database_call(
        elapsed_ms,
        statements=statements,
        pipeline_calls=pipeline_calls,
    )
    if elapsed_ms >= SLOW_DATABASE_MS:
        LOGGER.warning(
            "database.slow backend=%s operation=%s statements=%d duration_ms=%d",
            backend,
            operation,
            statements,
            round(elapsed_ms),
        )


class DatabaseConfigurationError(RuntimeError):
    """Raised when the selected database backend is not configured."""


class TursoDatabaseError(RuntimeError):
    """A sanitized remote database or protocol failure."""


def database_backend() -> str:
    value = os.getenv("TUNEOPS_DATABASE_BACKEND", "sqlite").strip().casefold()
    if value in {"sqlite", "local"}:
        return "sqlite"
    if value in {"turso", "libsql", "remote"}:
        return "turso"
    raise DatabaseConfigurationError(
        "TUNEOPS_DATABASE_BACKEND must be 'sqlite' or 'turso'"
    )


def _environment_value(primary: str, legacy: str) -> str:
    return (os.getenv(primary) or os.getenv(legacy) or "").strip()


def turso_configuration() -> tuple[str, str]:
    url = _environment_value("TURSO_DATABASE_URL", "tuneopsdb_TURSO_DATABASE_URL")
    token = _environment_value("TURSO_AUTH_TOKEN", "tuneopsdb_TURSO_AUTH_TOKEN")
    missing = []
    if not url:
        missing.append("TURSO_DATABASE_URL")
    if not token:
        missing.append("TURSO_AUTH_TOKEN")
    if missing:
        raise DatabaseConfigurationError("Missing: " + ", ".join(missing))
    if not url.startswith(("libsql://", "https://")):
        raise DatabaseConfigurationError(
            "TURSO_DATABASE_URL must use the libsql:// or https:// scheme"
        )
    return url, token


def _enable_system_trust_store() -> None:
    # requests/certifi does not include locally managed Windows root CAs.  Do
    # not disable verification; use the OS trust store when it is available.
    if sys.platform != "win32":
        return
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


def _encode_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "type": "blob",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    raise TypeError(f"Unsupported SQL parameter type: {type(value).__name__}")


def _decode_value(value: Mapping[str, Any]) -> Any:
    kind = value.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "text":
        return str(value["value"])
    if kind == "blob":
        return base64.b64decode(str(value["base64"]) + "====")
    raise TursoDatabaseError("Turso returned an unsupported SQL value")


def _statement(sql: str, parameters: Sequence[Any] | Mapping[str, Any] = ()) -> dict[str, Any]:
    stmt: dict[str, Any] = {"sql": sql, "want_rows": True}
    if isinstance(parameters, Mapping):
        stmt["args"] = []
        stmt["named_args"] = [
            {"name": str(name).lstrip(":@$"), "value": _encode_value(value)}
            for name, value in parameters.items()
        ]
    else:
        stmt["args"] = [_encode_value(value) for value in parameters]
        stmt["named_args"] = []
    return stmt


class RemoteRow(Mapping[str, Any]):
    def __init__(self, columns: Sequence[str], values: Sequence[Any]):
        self._columns = tuple(columns)
        self._sequence = tuple(values)
        self._values = dict(zip(self._columns, self._sequence, strict=False))

    def __getitem__(self, key: str | int | slice) -> Any:
        if isinstance(key, (int, slice)):
            return self._sequence[key]
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class RemoteCursor(Iterable[RemoteRow]):
    def __init__(
        self,
        rows: list[RemoteRow] | None = None,
        *,
        rowcount: int = -1,
        lastrowid: int | None = None,
    ):
        self._rows = rows or []
        self._offset = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def __iter__(self) -> Iterator[RemoteRow]:
        return iter(self._rows)

    def fetchone(self) -> RemoteRow | None:
        if self._offset >= len(self._rows):
            return None
        row = self._rows[self._offset]
        self._offset += 1
        return row

    def fetchall(self) -> list[RemoteRow]:
        rows = self._rows[self._offset :]
        self._offset = len(self._rows)
        return rows


class MeasuredSQLiteCursor(Iterable[Any]):
    """Transparent cursor proxy that counts rows decoded from local SQLite."""

    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def __iter__(self) -> Iterator[Any]:
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def fetchone(self) -> Any:
        started = time.perf_counter()
        row = self._cursor.fetchone()
        record_database_call(
            (time.perf_counter() - started) * 1000,
            rows=1 if row is not None else 0,
        )
        return row

    def fetchall(self) -> list[Any]:
        started = time.perf_counter()
        rows = self._cursor.fetchall()
        record_database_call(
            (time.perf_counter() - started) * 1000,
            rows=len(rows),
        )
        return rows


class MeasuredSQLiteConnection(sqlite3.Connection):
    """SQLite connection subclass exposing the same request counters as Turso."""

    def execute(self, sql: str, parameters: Any = ()) -> MeasuredSQLiteCursor:
        started = time.perf_counter()
        try:
            cursor = super().execute(sql, parameters)
        finally:
            _record_timing(
                (time.perf_counter() - started) * 1000,
                backend="sqlite", operation="execute", statements=1,
            )
        return MeasuredSQLiteCursor(cursor)

    def executemany(self, sql: str, parameter_rows: Iterable[Any]) -> MeasuredSQLiteCursor:
        rows = list(parameter_rows)
        started = time.perf_counter()
        try:
            cursor = super().executemany(sql, rows)
        finally:
            _record_timing(
                (time.perf_counter() - started) * 1000,
                backend="sqlite", operation="executemany",
                statements=len(rows),
            )
        return MeasuredSQLiteCursor(cursor)

    def executescript(self, script: str) -> MeasuredSQLiteCursor:
        started = time.perf_counter()
        try:
            cursor = super().executescript(script)
        finally:
            _record_timing(
                (time.perf_counter() - started) * 1000,
                backend="sqlite", operation="executescript",
                statements=len(_split_script(script)),
            )
        return MeasuredSQLiteCursor(cursor)


def _split_script(script: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                statements.append(statement)
            pending = ""
    if pending.strip():
        raise ValueError("Incomplete SQL statement in schema script")
    return statements


class TursoConnection:
    """Small synchronous DB-API subset backed by a stateful Hrana stream."""

    def __init__(
        self,
        url: str,
        auth_token: str,
        *,
        timeout: float = 20,
        read_only: bool = False,
    ):
        _enable_system_trust_store()
        self._base_url = url.replace("libsql://", "https://", 1).rstrip("/") + "/"
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {auth_token}",
            "User-Agent": "TuneOps/1.0",
        })
        self._timeout = timeout
        self._baton: str | None = None
        self._closed = False
        self._read_only = read_only
        self.total_changes = 0
        if not read_only:
            self._pipeline([
                {"type": "execute", "stmt": _statement("PRAGMA foreign_keys = ON")},
                {"type": "execute", "stmt": _statement("BEGIN")},
            ])

    def _pipeline(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._closed:
            raise TursoDatabaseError("The Turso connection is closed")
        started = time.perf_counter()
        try:
            response = self._session.post(
                urljoin(self._base_url, "v3/pipeline"),
                json={"baton": self._baton, "requests": operations},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TursoDatabaseError("The Turso database request failed") from exc
        finally:
            _record_timing(
                (time.perf_counter() - started) * 1000,
                backend="turso", operation="pipeline",
                statements=sum(operation.get("type") == "execute" for operation in operations),
                pipeline_calls=1,
            )
        self._baton = payload.get("baton")
        if payload.get("base_url"):
            self._base_url = str(payload["base_url"]).rstrip("/") + "/"
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != len(operations):
            raise TursoDatabaseError("Turso returned an invalid pipeline response")
        for result in results:
            if result.get("type") == "error":
                error = result.get("error") or {}
                code = str(error.get("code") or "database_error")
                message = str(error.get("message") or "SQL operation failed")
                raise TursoDatabaseError(f"{code}: {message}")
        return results

    @staticmethod
    def _cursor(result: Mapping[str, Any]) -> RemoteCursor:
        response = result.get("response") or {}
        raw = response.get("result") or {}
        columns = [str(column.get("name") or "") for column in raw.get("cols", [])]
        rows = [
            RemoteRow(columns, [_decode_value(value) for value in values])
            for values in raw.get("rows", [])
        ]
        record_database_call(0, rows=len(rows))
        rowcount = int(raw.get("affected_row_count", -1))
        last = raw.get("last_insert_rowid")
        return RemoteCursor(
            rows,
            rowcount=rowcount,
            lastrowid=int(last) if last is not None else None,
        )

    def execute(
        self, sql: str, parameters: Sequence[Any] | Mapping[str, Any] = ()
    ) -> RemoteCursor:
        operations = [{"type": "execute", "stmt": _statement(sql, parameters)}]
        if self._read_only:
            # A one-shot read does not need a write transaction. Execute and
            # close the Hrana stream in the same HTTP request, reducing a
            # simple SELECT from four network round trips to one.
            operations.append({"type": "close"})
        try:
            result = self._pipeline(operations)[0]
        finally:
            if self._read_only:
                self._closed = True
                self._session.close()
        cursor = self._cursor(result)
        if cursor.rowcount > 0:
            self.total_changes += cursor.rowcount
        return cursor

    def execute_batch(
        self,
        statements: Sequence[
            tuple[str, Sequence[Any] | Mapping[str, Any]]
        ],
    ) -> list[RemoteCursor]:
        """Execute heterogeneous statements in one remote pipeline call."""
        if not statements:
            return []
        operations = [
            {"type": "execute", "stmt": _statement(sql, parameters)}
            for sql, parameters in statements
        ]
        if self._read_only:
            operations.append({"type": "close"})
        try:
            results = self._pipeline(operations)
        finally:
            if self._read_only:
                self._closed = True
                self._session.close()
        return [self._cursor(result) for result in results[:len(statements)]]

    def executemany(
        self, sql: str, parameter_rows: Iterable[Sequence[Any] | Mapping[str, Any]]
    ) -> RemoteCursor:
        if self._read_only:
            raise TursoDatabaseError("A read-only Turso connection supports one SELECT")
        operations = [
            {"type": "execute", "stmt": _statement(sql, parameters)}
            for parameters in parameter_rows
        ]
        if not operations:
            return RemoteCursor(rowcount=0)
        cursors = [self._cursor(result) for result in self._pipeline(operations)]
        affected = sum(max(cursor.rowcount, 0) for cursor in cursors)
        self.total_changes += affected
        lastrowid = next(
            (cursor.lastrowid for cursor in reversed(cursors) if cursor.lastrowid is not None),
            None,
        )
        return RemoteCursor(rowcount=affected, lastrowid=lastrowid)

    def executescript(self, script: str) -> RemoteCursor:
        if self._read_only:
            raise TursoDatabaseError("A read-only Turso connection supports one SELECT")
        statements = _split_script(script)
        operations = [
            {"type": "execute", "stmt": _statement(statement)}
            for statement in statements
        ]
        cursors = [self._cursor(result) for result in self._pipeline(operations)]
        affected = sum(max(cursor.rowcount, 0) for cursor in cursors)
        self.total_changes += affected
        return RemoteCursor(rowcount=affected)

    def commit(self) -> None:
        if self._closed:
            return
        if self._read_only:
            self._closed = True
            self._session.close()
            return
        self._pipeline([{"type": "execute", "stmt": _statement("COMMIT")}])
        self._close_stream()

    def rollback(self) -> None:
        if self._closed:
            return
        if self._read_only:
            self._closed = True
            self._session.close()
            return
        try:
            self._pipeline([{"type": "execute", "stmt": _statement("ROLLBACK")}])
        finally:
            self._close_stream()

    def _close_stream(self) -> None:
        if self._closed:
            return
        try:
            # Closing is cleanup after COMMIT/ROLLBACK. A failed close must not
            # make a successfully committed transaction appear to have failed.
            self._pipeline([{"type": "close"}])
        except TursoDatabaseError:
            pass
        finally:
            self._closed = True
            self._session.close()

    def close(self) -> None:
        if not self._closed:
            self.rollback()


def open_connection(
    path: Path, *, remote: bool, read_only: bool = False,
) -> sqlite3.Connection | TursoConnection:
    record_connection()
    if remote:
        url, token = turso_configuration()
        return TursoConnection(url, token, read_only=read_only)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path,
        timeout=10,
        factory=MeasuredSQLiteConnection,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def execute_batch(
    connection: sqlite3.Connection | TursoConnection,
    statements: Sequence[tuple[str, Sequence[Any] | Mapping[str, Any]]],
) -> list[Any]:
    """Backend-neutral heterogeneous statement batch."""
    if isinstance(connection, TursoConnection):
        return connection.execute_batch(statements)
    return [connection.execute(sql, parameters) for sql, parameters in statements]

