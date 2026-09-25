"""Small in-process job registry for this single-user local application."""

from __future__ import annotations

import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable


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
    def __init__(self, workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="musicsync-job")
        self._jobs: dict[str, Job] = {}
        self._active_kinds: dict[str, str] = {}
        self._lock = threading.RLock()

    def submit(self, kind: str, function: Callable[[Callable[[str], None]], Any]) -> Job:
        with self._lock:
            active_id = self._active_kinds.get(kind)
            if active_id and self._jobs.get(active_id, Job("", "")).state in {"queued", "running"}:
                return self._jobs[active_id]
            job = Job(id=uuid.uuid4().hex, kind=kind, created_at=_now())
            self._jobs[job.id] = job
            self._active_kinds[kind] = job.id
        self._executor.submit(self._run, job.id, function)
        return job

    def _run(self, job_id: str, function: Callable[[Callable[[str], None]], Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = "running"
            job.started_at = _now()
        LOGGER.info("job.start id=%s kind=%s", job_id, job.kind)

        def progress(message: str) -> None:
            with self._lock:
                job.message = str(message)
                job.current += 1
            LOGGER.info("job.progress id=%s kind=%s message=%r", job_id, job.kind, message)

        try:
            result = function(progress)
        except Exception as exc:
            with self._lock:
                job.state = "failed"
                job.error = _safe_error(exc)
                job.finished_at = _now()
                self._active_kinds.pop(job.kind, None)
            LOGGER.exception("job.failed id=%s kind=%s", job_id, job.kind)
            return
        with self._lock:
            job.state = "succeeded"
            job.result = result
            job.finished_at = _now()
            self._active_kinds.pop(job.kind, None)
        LOGGER.info("job.complete id=%s kind=%s", job_id, job.kind)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return asdict(job) if job else None

    def snapshot(self, job: Job) -> dict[str, Any]:
        with self._lock:
            return asdict(job)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)


JOBS = JobRegistry()
