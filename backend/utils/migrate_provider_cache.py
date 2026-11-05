"""Create and verify the independent provider response cache table."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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

from backend.music_library.connection import database_backend  # noqa: E402
from backend.music_library.database import connect, connect_readonly  # noqa: E402
from backend.music_library.provider_cache import PROVIDER_CACHE_SCHEMA  # noqa: E402


def table_exists() -> bool:
    with connect_readonly() as connection:
        row = connection.execute(
            """
            SELECT 1 FROM sqlite_schema
            WHERE type='table' AND name='provider_response_cache'
            """
        ).fetchone()
    return row is not None


def migrate() -> None:
    with connect() as connection:
        connection.executescript(PROVIDER_CACHE_SCHEMA)
    if not table_exists():
        raise RuntimeError("Provider cache table verification failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    backend = database_backend()
    exists = table_exists()
    print(f"Configured database backend: {backend}")
    print(f"Provider response cache table: {'present' if exists else 'missing'}")
    if not args.apply:
        print("Dry run only. Use --apply to create the independent cache table.")
        return
    migrate()
    print("Provider response cache table is ready.")


if __name__ == "__main__":
    main()
