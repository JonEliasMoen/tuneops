from __future__ import annotations

from functools import partial
import hashlib
import time

from backend.app.mcp.config import McpSettings
from backend.app.mcp.oauth_provider import TuneOpsOAuthProvider
from backend.music_library import database


def settings() -> McpSettings:
    return McpSettings(
        issuer_url="https://tuneops.example/mcp/",
        resource_url="https://tuneops.example/mcp/",
        audience="https://tuneops.example/mcp/",
        jwks_url="https://tuneops.example/mcp/.well-known/jwks.json",
        auth_provider="tuneops",
        oauth_client_id="chatgpt-client",
        oauth_client_secret="secret",
    )


def test_opaque_tokens_are_hashed_and_refresh_rotates(tmp_path, monkeypatch):
    path = tmp_path / "oauth.sqlite3"
    database.initialize(path)
    with database.connect(path) as connection:
        now = "2026-01-01T00:00:00+00:00"
        connection.execute(
            "INSERT INTO app_users(id,display_name,status,created_at,updated_at) "
            "VALUES('user-1','Jon','active',?,?)",
            (now, now),
        )
        authorization_code = "one-time-code"
        connection.execute(
            """INSERT INTO oauth_authorization_codes(
                code_hash,user_id,client_id,redirect_uri,redirect_uri_provided,
                code_challenge,scopes_json,resource,expires_at,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                hashlib.sha256(authorization_code.encode()).hexdigest(), "user-1",
                "chatgpt-client", "https://chatgpt.com/callback", 1, "challenge",
                '["library:read"]', settings().resource_url, int(time.time()) + 600, now,
            ),
        )

    from backend.app.mcp import oauth_provider as module

    monkeypatch.setattr(module, "connect", partial(database.connect, path))
    monkeypatch.setattr(module, "connect_readonly", partial(database.connect_readonly, path))
    provider = TuneOpsOAuthProvider(settings())

    first = provider._issue(
        "user-1", "chatgpt-client", ["library:read"], settings().resource_url,
        code_hash=hashlib.sha256(authorization_code.encode()).hexdigest(),
    )
    assert first.access_token
    assert first.refresh_token
    with database.connect_readonly(path) as connection:
        access = connection.execute("SELECT token_hash FROM oauth_access_tokens").fetchone()
        grant = connection.execute("SELECT refresh_token_hash FROM oauth_token_grants").fetchone()
    assert access["token_hash"] == hashlib.sha256(first.access_token.encode()).hexdigest()
    assert grant["refresh_token_hash"] == hashlib.sha256(first.refresh_token.encode()).hexdigest()
    assert provider._load_access(first.access_token).subject == "user-1"
    loaded = provider._load_refresh("chatgpt-client", first.refresh_token)
    assert loaded is not None and loaded.expires_at > int(time.time())

    with database.connect_readonly(path) as connection:
        grant_id = str(connection.execute("SELECT id FROM oauth_token_grants").fetchone()["id"])
    second = provider._issue(
        "user-1", "chatgpt-client", ["library:read"], settings().resource_url,
        grant_id=grant_id,
        previous_refresh_hash=hashlib.sha256(first.refresh_token.encode()).hexdigest(),
    )
    assert provider._load_refresh("chatgpt-client", first.refresh_token) is None
    assert provider._load_refresh("chatgpt-client", second.refresh_token) is not None
