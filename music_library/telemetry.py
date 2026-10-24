"""Request-local, non-sensitive database cost counters."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class DatabaseMetrics:
    connections: int = 0
    statements: int = 0
    pipeline_calls: int = 0
    database_ms: float = 0.0
    rows_decoded: int = 0


_current: ContextVar[DatabaseMetrics | None] = ContextVar(
    "tuneops_database_metrics", default=None,
)


def begin_database_metrics() -> tuple[DatabaseMetrics, Token]:
    metrics = DatabaseMetrics()
    return metrics, _current.set(metrics)


def end_database_metrics(token: Token) -> None:
    _current.reset(token)


def current_database_metrics() -> DatabaseMetrics | None:
    return _current.get()


def record_connection() -> None:
    if metrics := _current.get():
        metrics.connections += 1


def record_database_call(
    elapsed_ms: float,
    *,
    statements: int = 0,
    pipeline_calls: int = 0,
    rows: int = 0,
) -> None:
    if metrics := _current.get():
        metrics.database_ms += max(0.0, elapsed_ms)
        metrics.statements += max(0, statements)
        metrics.pipeline_calls += max(0, pipeline_calls)
        metrics.rows_decoded += max(0, rows)
