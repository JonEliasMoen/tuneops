from pathlib import Path
import sqlite3

import pytest

import backup_turso


DUMP = """PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES parent(id));
INSERT INTO parent VALUES(1,'TuneOps');
INSERT INTO child VALUES(10,1);
CREATE INDEX child_parent_idx ON child(parent_id);
COMMIT;
"""


def test_restore_dump_and_verify_sqlite(tmp_path: Path):
    dump = tmp_path / "backup.sql"
    database = tmp_path / "backup.sqlite3"
    dump.write_text(DUMP, encoding="utf-8")

    backup_turso._restore_dump(dump, database)

    assert backup_turso._verify_sqlite(database) == {"child": 1, "parent": 1}
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT parent.name FROM child JOIN parent ON parent.id=child.parent_id"
        ).fetchone()[0] == "TuneOps"
        indexes = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='index' AND name='child_parent_idx'"
        ).fetchall()
    assert indexes == [("child_parent_idx",)]


def test_count_verification_rejects_concurrent_remote_changes():
    with pytest.raises(RuntimeError, match="changed while the backup was running"):
        backup_turso._verify_counts(
            {"tracks": 2}, {"tracks": 2}, {"tracks": 3}
        )


def test_count_verification_rejects_incomplete_backup():
    with pytest.raises(RuntimeError, match="row-count verification failed"):
        backup_turso._verify_counts(
            {"tracks": 2}, {"tracks": 1}, {"tracks": 2}
        )


def test_database_name_is_explicit_and_safe(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_NAME", raising=False)
    with pytest.raises(ValueError, match="Provide --database"):
        backup_turso._database_name(None)
    with pytest.raises(ValueError, match="unsupported characters"):
        backup_turso._database_name("name; rm")
    assert backup_turso._database_name("tuneops-db") == "tuneops-db"


def test_backup_refuses_to_overwrite_existing_file(tmp_path: Path):
    target = tmp_path / "existing.sqlite3"
    target.write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        backup_turso.backup("tuneops", target)

    assert target.read_bytes() == b"existing"
