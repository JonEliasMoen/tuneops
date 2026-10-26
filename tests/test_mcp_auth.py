from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.app.mcp.auth import TuneOpsTokenVerifier, tuneops_user_id
from backend.app.mcp.config import McpSettings


def settings() -> McpSettings:
    return McpSettings(
        issuer_url="https://auth.example.com",
        resource_url="https://tuneops.example/mcp/",
        audience="https://api.example.com/tuneops",
        jwks_url="https://auth.example.com/.well-known/jwks.json",
    )


def signed_token(*, issuer: str = "https://auth.example.com", subject: str = "mcp-user"):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": issuer,
            "sub": subject,
            "aud": "https://api.example.com/tuneops",
            "iat": now,
            "exp": now + 300,
            "scope": "profile:read library:read",
            "azp": "chatgpt-client",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    return token, private_key.public_key()


def test_valid_linked_token_resolves_internal_user():
    token, public_key = signed_token()
    verifier = TuneOpsTokenVerifier(
        settings(),
        jwks_client=SimpleNamespace(
            get_signing_key_from_jwt=lambda value: SimpleNamespace(key=public_key)
        ),
        identity_resolver=lambda issuer, subject: (
            "internal-user" if (issuer, subject) == (settings().issuer_url, "mcp-user") else None
        ),
    )

    access_token = asyncio.run(verifier.verify_token(token))

    assert access_token is not None
    assert access_token.subject == "mcp-user"
    assert access_token.client_id == "chatgpt-client"
    assert access_token.scopes == ["profile:read", "library:read"]
    assert tuneops_user_id(access_token) == "internal-user"


def test_unlinked_identity_is_rejected():
    token, public_key = signed_token()
    verifier = TuneOpsTokenVerifier(
        settings(),
        jwks_client=SimpleNamespace(
            get_signing_key_from_jwt=lambda value: SimpleNamespace(key=public_key)
        ),
        identity_resolver=lambda issuer, subject: None,
    )

    assert asyncio.run(verifier.verify_token(token)) is None


def test_wrong_issuer_is_rejected_before_identity_lookup():
    token, public_key = signed_token(issuer="https://attacker.example")
    called = False

    def resolve(issuer: str, subject: str) -> str:
        nonlocal called
        called = True
        return "internal-user"

    verifier = TuneOpsTokenVerifier(
        settings(),
        jwks_client=SimpleNamespace(
            get_signing_key_from_jwt=lambda value: SimpleNamespace(key=public_key)
        ),
        identity_resolver=resolve,
    )

    assert asyncio.run(verifier.verify_token(token)) is None
    assert called is False
