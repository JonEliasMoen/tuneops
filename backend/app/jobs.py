"""Job registry with shared persistence for stateless hosted instances."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from music_library.database import DATABASE_PATH, connect, connect_readonly, initialize


LOGGER = logging.getLogger("musicsync")


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip() or "The operation failed."
    # This is a local Python installation problem, not a TIDAL account or
    # library failure.  Keep the technical exception in the server log, but do
    # not make the UI surface a multi-line OpenSSL traceback.
    if "CERTIFICATE_VERIFY_FAILED" in message or "SSLCertVerificationError" in message:
        return (
            "TIDAL could not be reached because this Python installation could not "
            "verify the local TLS certificate chain. Cached library data is still "
            "available; repair the local Python certificate setup, then retry."
        )
    message = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[redacted]", message)
    message = re.sub(r"(?i)(api[_-]?key|token|secret)=([^\s&]+)", r"\1=[redacted]", message)
    return message[:500]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    kind: str
    state: str = "queued"
    phase: str = ""
    current: int = 0
    total: int | None = None
    message: str = ""
    result: Any = None
    error: str = ""
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None


class JobRegistry:
    def __init__(
        self,
        workers: int = 2,
        *,
        persist: bool | None = None,
        synchronous: bool | None = None,
        database_path=DATABASE_PATH,
    ) -> None:
        self._synchronous = bool(os.getenv("VERCEL")) if synchronous is None else synchronous
        self._executor = (
            None
            if self._synchronous
            else ThreadPoolExecutor(max_workers=workers, thread_name_prefix="musicsync-job")
        )
        self._jobs: dict[str, Job] = {}
        self._active_kinds: dict[str, str] = {}
        self._lock = threading.RLock()
        self._database_path = database_path
        self._persist_enabled = (
            bool(os.getenv("VERCEL"))
            or os.getenv("TUNEOPS_PERSIST_JOBS", "").strip().casefold()
            in {"1", "true", "yes", "on"}
            if persist is None
            else persist
        )

    def _persist(self, job: Job) -> None:
        if not self._persist_enabled:
            return
        initialize(self._database_path)
        payload = json.dumps(job.result, ensure_ascii=False, default=str) if job.result is not None else None
        updated_at = _now()
        with connect(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO app_jobs (
                    id, kind, state, phase, current, total, message,
                    result_json, error, created_at, started_at, finished_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    state=excluded.state,
                    phase=excluded.phase,
                    current=excluded.current,
                    total=excluded.total,
                    message=excluded.message,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    updated_at=excluded.updated_at
                """,
                (
                    job.id, job.kind, job.state, job.phase, job.current, job.total,
                    job.message, payload, job.error, job.created_at, job.started_at,
                    job.finished_at, updated_at,
                ),
            )

    def _load(self, job_id: str) -> Job | None:
        if not self._persist_enabled:
            return None
        initialize(self._database_path)
        with connect_readonly(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, kind, state, phase, current, total, message,
                       result_json, error, created_at, started_at, finished_at
                FROM app_jobs WHERE id=?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        result_json = row["result_json"]
        return Job(
            id=str(row["id"]),
            kind=str(row["kind"]),
            state=str(row["state"]),
            phase=str(row["phase"] or ""),
            current=int(row["current"] or 0),
            total=int(row["total"]) if row["total"] is not None else None,
            message=str(row["message"] or ""),
            result=json.loads(result_json) if result_json else None,
            error=str(row["error"] or ""),
            created_at=str(row["created_at"]),
            started_at=str(row["started_at"]) if row["started_at"] else None,
            finished_at=str(row["finished_at"]) if row["finished_at"] else None,
        )

    def submit(self, kind: str, function: Callable[[Callable[[str], None]], Any]) -> Job:
        with self._lock:
            active_id = self._active_kinds.get(kind)
            if active_id and self._jobs.get(active_id, Job("", "")).state in {"queued", "running"}:
                return self._jobs[active_id]
            job = Job(id=uuid.uuid4().hex, kind=kind, created_at=_now())
            self._jobs[job.id] = job
            self._active_kinds[kind] = job.id
            self._persist(job)
        if self._synchronous:
            # A normal Python thread is not durable after a Vercel function
            # returns. Keep the request alive until the persisted job reaches
            # a terminal state; local development retains background workers.
            self._run(job.id, function)
        else:
            assert self._executor is not None
            self._executor.submit(self._run, job.id, function)
        return job

    def _run(self, job_id: str, function: Callable[[Callable[[str], None]], Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = "running"
            job.started_at = _now()
            self._persist(job)
        LOGGER.info("job.start id=%s kind=%s", job_id, job.kind)
        last_progress_persisted = time.monotonic()

        def progress(message: str) -> None:
            nonlocal last_progress_persisted
            with self._lock:
                job.message = str(message)
                job.current += 1
                now = time.monotonic()
                if now - last_progress_persisted >= 1.0:
                    self._persist(job)
                    last_progress_persisted = now
            LOGGER.info("job.progress id=%s kind=%s message=%r", job_id, job.kind, message)

        try:
            result = function(progress)
        except Exception as exc:
            with self._lock:
                job.state = "failed"
                job.error = _safe_error(exc)
                job.finished_at = _now()
                self._active_kinds.pop(job.kind, None)
                self._persist(job)
            LOGGER.exception("job.failed id=%s kind=%s", job_id, job.kind)
            return
        with self._lock:
            job.state = "succeeded"
            job.result = result
            job.finished_at = _now()
            self._active_kinds.pop(job.kind, None)
            self._persist(job)
        LOGGER.info("job.complete id=%s kind=%s", job_id, job.kind)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return asdict(job)
        job = self._load(job_id)
        return asdict(job) if job else None

    def snapshot(self, job: Job) -> dict[str, Any]:
        with self._lock:
            return asdict(job)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=False)


JOBS = JobRegistry()
