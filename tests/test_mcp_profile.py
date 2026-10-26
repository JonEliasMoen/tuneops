from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.app.services.mcp_profile import profile_for_user
from music_library.database import connect, initialize


def test_profile_returns_only_safe_provider_metadata(tmp_path):
    path = tmp_path / "library.sqlite3"
    initialize(path)
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO app_users(id, display_name, status, created_at, updated_at)
            VALUES(?, 'Jon', 'active', ?, ?)
            """,
            (user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO provider_connections(
                id, user_id, provider, display_label, status,
                credential_ciphertext, credential_key_id,
                created_at, updated_at
            ) VALUES(?, ?, 'tidal', 'Jon on TIDAL', 'connected',
                     'must-not-leak', 'secret-key-id', ?, ?)
            """,
            (str(uuid.uuid4()), user_id, now, now),
        )

    result = profile_for_user(user_id, path=path)

    assert result == {
        "user_id": user_id,
        "display_name": "Jon",
        "providers": [
            {"provider": "tidal", "label": "Jon on TIDAL", "status": "connected"}
        ],
    }
    assert "must-not-leak" not in repr(result)
