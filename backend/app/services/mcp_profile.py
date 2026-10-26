"""Safe account summary used by the MCP profile tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from music_library.connection import execute_batch
from music_library.database import DATABASE_PATH, connect_readonly


class McpProfileNotFound(RuntimeError):
    pass


def profile_for_user(
    user_id: str,
    *,
    path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    with connect_readonly(path) as connection:
        user_cursor, providers_cursor = execute_batch(
            connection,
            [
                (
                    """
                    SELECT id, display_name, status
                    FROM app_users
                    WHERE id=? AND status='active'
                    """,
                    (str(user_id),),
                ),
                (
                    """
                    SELECT provider, display_label, status
                    FROM provider_connections
                    WHERE user_id=?
                    ORDER BY provider
                    """,
                    (str(user_id),),
                ),
            ],
        )
        user = user_cursor.fetchone()
        providers = providers_cursor.fetchall()
    if user is None:
        raise McpProfileNotFound("The TuneOps user is not active")
    return {
        "user_id": str(user["id"]),
        "display_name": str(user["display_name"] or ""),
        "providers": [
            {
                "provider": str(row["provider"]),
                "label": str(row["display_label"] or ""),
                "status": str(row["status"] or ""),
            }
            for row in providers
        ],
    }
