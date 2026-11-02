from __future__ import annotations

from music_library import database as library_database
from music_library.database import connect, initialize


def test_persisted_schema_version_skips_migrations_after_a_cold_start(
    tmp_path, monkeypatch,
):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM app_schema_meta WHERE singleton=1"
        ).fetchone()[0]
    assert version == library_database.SCHEMA_VERSION

    key = "sqlite:" + str(database.resolve())
    library_database._INITIALIZED_DATABASES.discard(key)

    def unexpected_migration(_path):
        raise AssertionError("A current schema must not replay migrations")

    monkeypatch.setattr(library_database, "_initialize_connection", unexpected_migration)
    initialize(database)


def test_repeated_initialize_is_process_local_constant_cost(tmp_path, monkeypatch):
    database = tmp_path / "library.sqlite3"
    initialize(database)

    def unexpected_schema_read(_path):
        raise AssertionError("A warm process must not re-read schema state")

    monkeypatch.setattr(library_database, "_stored_schema_version", unexpected_schema_read)
    initialize(database)
