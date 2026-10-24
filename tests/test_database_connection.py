from __future__ import annotations

from music_library import connection, database


def test_database_backend_is_explicit(monkeypatch):
    monkeypatch.delenv("TUNEOPS_DATABASE_BACKEND", raising=False)
    assert connection.database_backend() == "sqlite"
    monkeypatch.setenv("TUNEOPS_DATABASE_BACKEND", "turso")
    assert connection.database_backend() == "turso"


def test_remote_database_does_not_require_a_local_sqlite_file(tmp_path, monkeypatch):
    remote_placeholder = tmp_path / "does-not-exist.sqlite3"
    monkeypatch.setattr(database, "DATABASE_PATH", remote_placeholder)
    monkeypatch.setattr(database, "database_backend", lambda: "turso")

    assert database._database_available(remote_placeholder)
    assert not database._database_available(tmp_path / "different.sqlite3")


def test_turso_configuration_accepts_vercel_integration_names(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("tuneopsdb_TURSO_DATABASE_URL", "libsql://example.invalid")
    monkeypatch.setenv("tuneopsdb_TURSO_AUTH_TOKEN", "secret-token")
    assert connection.turso_configuration() == (
        "libsql://example.invalid",
        "secret-token",
    )


def test_remote_row_is_sqlite_row_compatible():
    row = connection.RemoteRow(("id", "name"), (7, "TuneOps"))
    assert row["id"] == 7
    assert row[0] == 7
    assert row[-1] == "TuneOps"
    assert dict(row) == {"id": 7, "name": "TuneOps"}


def test_split_script_keeps_complete_statements():
    assert connection._split_script(
        "CREATE TABLE example(id INTEGER);\n"
        "INSERT INTO example VALUES(1);\n"
    ) == [
        "CREATE TABLE example(id INTEGER);",
        "INSERT INTO example VALUES(1);",
    ]


def test_turso_connection_uses_one_transactional_stream(monkeypatch):
    calls: list[dict] = []

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Session:
        def __init__(self):
            self.headers = {}

        def post(self, url, *, json, timeout):
            calls.append(json)
            results = []
            for request in json["requests"]:
                if request["type"] == "close":
                    results.append({"type": "ok", "response": {"type": "close"}})
                    continue
                sql = request["stmt"]["sql"]
                raw = {
                    "cols": [{"name": "value"}],
                    "rows": [[request["stmt"]["args"][0]]],
                    "affected_row_count": 0,
                } if sql == "SELECT ? AS value" else {
                    "cols": [], "rows": [], "affected_row_count": 0,
                }
                results.append({
                    "type": "ok",
                    "response": {"type": "execute", "result": raw},
                })
            return Response({
                "baton": None if json["requests"][-1]["type"] == "close" else "next",
                "base_url": None,
                "results": results,
            })

        def close(self):
            return None

    monkeypatch.setattr(connection.requests, "Session", Session)
    monkeypatch.setattr(connection, "_enable_system_trust_store", lambda: None)
    database = connection.TursoConnection("libsql://example.invalid", "token")
    row = database.execute("SELECT ? AS value", (42,)).fetchone()
    database.commit()

    assert row is not None and row["value"] == 42
    assert calls[0]["baton"] is None
    assert [item["stmt"]["sql"] for item in calls[0]["requests"]] == [
        "PRAGMA foreign_keys = ON",
        "BEGIN",
    ]
    assert calls[1]["baton"] == "next"
    assert calls[-1]["requests"] == [{"type": "close"}]


def test_turso_read_only_connection_uses_one_http_pipeline(monkeypatch):
    calls: list[dict] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "baton": None,
                "base_url": None,
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "type": "execute",
                            "result": {
                                "cols": [{"name": "value"}],
                                "rows": [[{"type": "integer", "value": "42"}]],
                                "affected_row_count": 0,
                            },
                        },
                    },
                    {"type": "ok", "response": {"type": "close"}},
                ],
            }

    class Session:
        def __init__(self):
            self.headers = {}
            self.closed = False

        def post(self, url, *, json, timeout):
            calls.append(json)
            return Response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(connection.requests, "Session", Session)
    monkeypatch.setattr(connection, "_enable_system_trust_store", lambda: None)

    database = connection.TursoConnection(
        "libsql://example.invalid", "token", read_only=True,
    )
    row = database.execute("SELECT ? AS value", (42,)).fetchone()
    database.commit()

    assert row is not None and row["value"] == 42
    assert len(calls) == 1
    assert calls[0]["baton"] is None
    assert calls[0]["requests"][0]["stmt"]["sql"] == "SELECT ? AS value"
    assert calls[0]["requests"][1] == {"type": "close"}


def test_turso_read_only_batch_uses_one_http_pipeline(monkeypatch):
    calls: list[dict] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            requests = calls[-1]["requests"]
            results = []
            for request in requests:
                if request["type"] == "close":
                    results.append({"type": "ok", "response": {"type": "close"}})
                else:
                    results.append({
                        "type": "ok",
                        "response": {
                            "type": "execute",
                            "result": {
                                "cols": [{"name": "value"}],
                                "rows": [[request["stmt"]["args"][0]]],
                                "affected_row_count": 0,
                            },
                        },
                    })
            return {"baton": None, "base_url": None, "results": results}

    class Session:
        def __init__(self):
            self.headers = {}

        def post(self, url, *, json, timeout):
            calls.append(json)
            return Response()

        def close(self):
            return None

    monkeypatch.setattr(connection.requests, "Session", Session)
    monkeypatch.setattr(connection, "_enable_system_trust_store", lambda: None)
    database = connection.TursoConnection(
        "libsql://example.invalid", "token", read_only=True,
    )

    cursors = connection.execute_batch(database, [
        ("SELECT ? AS value", (1,)),
        ("SELECT ? AS value", (2,)),
    ])

    assert [cursor.fetchone()["value"] for cursor in cursors] == [1, 2]
    assert len(calls) == 1
    assert [request["type"] for request in calls[0]["requests"]] == [
        "execute", "execute", "close",
    ]
