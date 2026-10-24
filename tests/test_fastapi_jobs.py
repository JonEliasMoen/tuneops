from __future__ import annotations

import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app import jobs as job_registry
from backend.app.api import jobs


class ImmediateJobs:
    def __init__(self):
        self.kind = ""
        self.result = None

    def submit(self, kind, function):
        self.kind = kind
        self.result = function(lambda _message: None)
        return SimpleNamespace(
            id="job-id",
            kind=kind,
            state="succeeded",
            phase="",
            current=0,
            total=None,
            message="",
            result=self.result,
            error="",
            created_at="2026-09-24T00:00:00+00:00",
            started_at=None,
            finished_at=None,
        )

    @staticmethod
    def snapshot(job):
        return vars(job)


def test_liked_refresh_reuses_backend_session_and_bounded_maintenance(monkeypatch):
    registry = ImmediateJobs()
    session = object()
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs, "descriptor", lambda *_: {"name": "Liked tracks"})
    monkeypatch.setattr(jobs.engine, "tidal_client", lambda interactive=False: session)
    monkeypatch.setattr(jobs.engine, "load_runtime_settings", lambda: {"liked_tracks_cache_max_pages": 3})
    monkeypatch.setattr(
        jobs.engine,
        "maintain_tidal_liked_tracks",
        lambda tidal, settings, progress: {"session": tidal is session, "pages": settings["liked_tracks_cache_max_pages"]},
    )

    response = jobs.refresh_collection("liked", "liked", force=False)

    assert response.state == "succeeded"
    assert registry.kind == "collection-refresh:liked:liked"
    assert registry.result == {"session": True, "pages": 3}


def test_lastfm_status_reports_configuration_without_exposing_the_api_key(monkeypatch):
    monkeypatch.setattr(jobs.engine, "load_runtime_settings", lambda: {"lastfm_username": "Aruzhu"})
    monkeypatch.setattr(jobs, "lastfm_import_summary", lambda username: {"cached": 7, "username_seen": username})
    monkeypatch.setenv("LASTFM_API_KEY", "private-lastfm-key")

    result = jobs.lastfm_status()

    assert result == {"username": "Aruzhu", "api_key_configured": True, "cached": 7, "username_seen": "Aruzhu"}
    assert "private-lastfm-key" not in str(result)


def test_lastfm_import_job_uses_configured_username_delay_and_secret_only_in_process(monkeypatch):
    registry = ImmediateJobs()
    captured: dict[str, object] = {}
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs.engine, "load_runtime_settings", lambda: {"lastfm_username": "Aruzhu", "lastfm_import_delay_seconds": 0.2})
    monkeypatch.setenv("LASTFM_API_KEY", "private-lastfm-key")
    monkeypatch.setattr(
        jobs,
        "import_scrobbles",
        lambda username, api_key, delay_seconds, progress: captured.update(username=username, api_key=api_key, delay=delay_seconds) or {"imported": 3},
    )

    response = jobs.run_lastfm_import()

    assert response.state == "succeeded"
    assert registry.kind == "lastfm-import"
    assert registry.result == {"imported": 3}
    assert captured == {"username": "Aruzhu", "api_key": "private-lastfm-key", "delay": 0.2}


def test_sqlite_only_collection_rejects_provider_refresh():
    with pytest.raises(HTTPException) as raised:
        jobs.refresh_collection("artist", "artist-id", force=False)
    assert raised.value.status_code == 400


def test_indexed_collection_refresh_preserves_the_explicit_force_flag(monkeypatch):
    registry = ImmediateJobs()
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs, "descriptor", lambda *_: {"name": "Indexed event"})
    monkeypatch.setattr(
        jobs.engine,
        "refresh_tidal_playlist_cache",
        lambda playlist_id, force=False: calls.append((playlist_id, force)) or {"refreshed": force},
    )

    response = jobs.refresh_collection("event", "event-id", force=True)

    assert response.state == "succeeded"
    assert registry.kind == "collection-refresh:event:event-id"
    assert calls == [("event-id", True)]
    assert registry.result == {"refreshed": True}


def test_pending_refresh_does_not_open_tidal_when_queue_is_empty(monkeypatch):
    registry = ImmediateJobs()
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs.engine, "load_runtime_settings", lambda: {})
    monkeypatch.setattr(jobs, "pending_tracks", lambda: [])
    monkeypatch.setattr(
        jobs.engine,
        "tidal_client",
        lambda **_kwargs: pytest.fail("an empty pending queue must not call TIDAL"),
    )

    response = jobs.refresh_pending_tracks()

    assert response.state == "succeeded"
    assert registry.kind == "pending-track-refresh"
    assert registry.result == {"searched": 0}


def test_single_pending_refresh_updates_only_the_requested_track(monkeypatch):
    registry = ImmediateJobs()
    record = {"id": 42, "artist": "Artist", "title": "Track"}
    updated: dict[str, object] = {}
    session = object()
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs, "pending_track", lambda pending_id: record if pending_id == 42 else None)
    monkeypatch.setattr(jobs.engine, "load_runtime_settings", lambda: {})
    monkeypatch.setattr(jobs.engine, "tidal_client", lambda interactive=False: session)
    monkeypatch.setattr(jobs, "find_tidal_matches", lambda _engine, actual_session, row: [{"id": "tidal-id", "score": 9}] if actual_session is session and row is record else [])
    monkeypatch.setattr(jobs, "update_pending_track_candidates", lambda pending_id, candidates, status: updated.update(id=pending_id, candidates=candidates, status=status))

    response = jobs.refresh_one_pending_track(42)

    assert response.state == "succeeded"
    assert registry.kind == "pending-track-refresh:42"
    assert updated == {"id": 42, "candidates": [{"id": "tidal-id", "score": 9}], "status": "matched"}
    assert registry.result == {"id": 42, "status": "matched", "candidates": 1}


def test_manual_mix_import_runs_only_as_an_explicit_background_job(monkeypatch):
    registry = ImmediateJobs()
    imported: dict[str, object] = {}
    mix = SimpleNamespace(folder_name="darkprog")
    playlist = SimpleNamespace(name="Dark Progressive")
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs, "mix_for", lambda name: mix if name == "darkprog" else None)
    monkeypatch.setattr(
        jobs,
        "import_tidal_setlist",
        lambda engine, source_mix, url: (
            imported.update(engine=engine, mix=source_mix, url=url) or playlist,
            [{"id": "1"}, {"id": "2"}],
        ),
    )

    response = jobs.import_mix_tidal_setlist(
        "darkprog", jobs.MixTidalImportRequest(tidal_url="https://tidal.com/playlist/example")
    )

    assert response.state == "succeeded"
    assert registry.kind == "mix-tidal-import:darkprog"
    assert imported["mix"] is mix
    assert imported["url"] == "https://tidal.com/playlist/example"
    assert registry.result == {"playlist_name": "Dark Progressive", "tracks": 2}


def test_mix_discovery_runs_as_an_explicit_job_and_invalidates_navigation(monkeypatch):
    registry = ImmediateJobs()
    invalidations: list[bool] = []
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(
        jobs,
        "discover_tidal_mixes",
        lambda actual_engine, progress: {
            "scanned": 9,
            "candidates": 3,
            "imported": 2,
            "results": [],
        },
    )
    monkeypatch.setattr(jobs, "invalidate_navigation_snapshot", lambda: invalidations.append(True))

    response = jobs.discover_tidal_mix_setlists()

    assert response.state == "succeeded"
    assert registry.kind == "mix-tidal-discovery"
    assert registry.result["imported"] == 2
    assert invalidations == [True]


def test_watched_mix_tracklist_search_loads_delay_settings_before_job_runs(monkeypatch):
    registry = ImmediateJobs()
    session = object()
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs, "watched_mix", lambda video_id: {"video_id": video_id})
    monkeypatch.setattr(
        jobs.engine,
        "load_runtime_settings",
        lambda: {"tidal_search_delay_seconds": 0},
    )
    monkeypatch.setattr(jobs.engine, "tidal_client", lambda interactive=False: session)
    monkeypatch.setattr(
        jobs,
        "find_tidal_matches",
        lambda _engine, actual_session, row: (
            [{"id": "tidal-id", "score": 9}] if actual_session is session else []
        ),
    )
    request = jobs.TracklistSearchRequest.model_validate({
        "rows": [{
            "row_id": "row-1", "raw": "Artist - Track", "time": "00:00",
            "artist": "Artist", "title": "Track", "remix": "", "status": "parsed",
            "matches": [], "selected_id": "",
        }]
    })

    response = jobs.search_watched_mix_tracklist("video-id", request)

    assert response.state == "succeeded"
    assert registry.kind == "watched-tracklist-search:video-id"
    assert registry.result["searched"] == 1
    assert registry.result["rows"][0]["status"] == "matched"


def test_job_errors_redact_secret_query_values():
    error = RuntimeError(
        "403 for https://example.test/path?method=x&api_key=super-secret&token=also-secret"
    )
    safe = job_registry._safe_error(error)
    assert "super-secret" not in safe
    assert "also-secret" not in safe
    assert "?[redacted]" in safe


def test_job_errors_explain_local_tls_without_exposing_the_raw_exception():
    safe = job_registry._safe_error(
        RuntimeError("SSLCertVerificationError: CERTIFICATE_VERIFY_FAILED")
    )

    assert "TLS certificate chain" in safe
    assert "Cached library data" in safe
    assert "SSLCertVerificationError" not in safe


def test_provider_auth_failure_becomes_a_sanitized_failed_refresh_job(monkeypatch):
    registry = job_registry.JobRegistry(workers=1)
    monkeypatch.setattr(jobs, "JOBS", registry)
    monkeypatch.setattr(jobs, "descriptor", lambda *_: {"name": "My playlist"})
    monkeypatch.setattr(
        jobs.engine,
        "refresh_tidal_playlist_cache",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("TIDAL session expired: token=private-session-token")
        ),
    )
    try:
        response = jobs.refresh_collection("playlist", "playlist-id", force=False)
        result = None
        for _ in range(100):
            result = registry.get(response.id)
            if result and result["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
    finally:
        registry.shutdown()

    assert result is not None
    assert result["state"] == "failed"
    assert "private-session-token" not in result["error"]
    assert "token=[redacted]" in result["error"]


def test_failed_background_job_is_terminal_and_sanitizes_provider_details():
    registry = job_registry.JobRegistry(workers=1)
    job = job_registry.Job(id="failed-job", kind="provider-refresh", created_at="now")
    registry._jobs[job.id] = job
    registry._active_kinds[job.kind] = job.id
    try:
        registry._run(
            job.id,
            lambda _progress: (_ for _ in ()).throw(
                RuntimeError("403 https://provider.test/request?token=private-token")
            ),
        )
        result = registry.get(job.id)
    finally:
        registry.shutdown()

    assert result is not None
    assert result["state"] == "failed"
    assert result["finished_at"]
    assert "private-token" not in result["error"]
    assert "?[redacted]" in result["error"]


def test_persisted_job_can_be_polled_from_another_registry(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    first = job_registry.JobRegistry(workers=1, persist=True, database_path=path)
    second = job_registry.JobRegistry(workers=1, persist=True, database_path=path)
    try:
        submitted = first.submit("shared-job", lambda progress: {"ok": True})
        result = None
        for _ in range(100):
            result = second.get(submitted.id)
            if result and result["state"] == "succeeded":
                break
            time.sleep(0.01)
    finally:
        first.shutdown()
        second.shutdown()

    assert result is not None
    assert result["state"] == "succeeded"
    assert result["result"] == {"ok": True}


def test_persisted_job_poll_uses_read_only_connection(monkeypatch, tmp_path):
    used_paths = []

    class Cursor:
        @staticmethod
        def fetchone():
            return {
                "id": "remote-job", "kind": "test", "state": "running",
                "phase": "", "current": 2, "total": 5, "message": "Working",
                "result_json": None, "error": "",
                "created_at": "2026-10-22T12:00:00+00:00",
                "started_at": "2026-10-22T12:00:01+00:00", "finished_at": None,
            }

    class Connection:
        @staticmethod
        def execute(_sql, parameters):
            assert parameters == ("remote-job",)
            return Cursor()

    @contextmanager
    def readonly(path):
        used_paths.append(path)
        yield Connection()

    monkeypatch.setattr(job_registry, "initialize", lambda _path: None)
    monkeypatch.setattr(job_registry, "connect_readonly", readonly)
    registry = job_registry.JobRegistry(
        workers=1, persist=True, database_path=tmp_path / "jobs.sqlite3",
    )
    try:
        result = registry.get("remote-job")
    finally:
        registry.shutdown()

    assert used_paths == [tmp_path / "jobs.sqlite3"]
    assert result is not None
    assert result["state"] == "running"
    assert result["message"] == "Working"


def test_synchronous_registry_returns_only_after_job_is_terminal(tmp_path):
    registry = job_registry.JobRegistry(
        persist=True, synchronous=True, database_path=tmp_path / "jobs.sqlite3"
    )
    try:
        submitted = registry.submit("hosted-job", lambda progress: {"done": True})
        result = registry.get(submitted.id)
    finally:
        registry.shutdown()

    assert submitted.state == "succeeded"
    assert result is not None
    assert result["state"] == "succeeded"
    assert result["result"] == {"done": True}


def test_progress_persistence_is_throttled_but_terminal_state_is_saved(monkeypatch):
    registry = job_registry.JobRegistry(workers=1, persist=True)
    job = job_registry.Job(id="throttled", kind="import", created_at="now")
    registry._jobs[job.id] = job
    registry._active_kinds[job.kind] = job.id
    persisted = []
    monkeypatch.setattr(registry, "_persist", lambda current: persisted.append((current.state, current.current)))
    monkeypatch.setattr(job_registry.time, "monotonic", lambda: 10.0)
    try:
        registry._run(
            job.id,
            lambda progress: [progress(f"Step {index}") for index in range(5)],
        )
    finally:
        registry.shutdown()

    assert persisted == [("running", 0), ("succeeded", 5)]
