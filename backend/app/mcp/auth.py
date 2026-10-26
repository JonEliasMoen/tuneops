"""OAuth bearer-token verification for the TuneOps MCP resource server."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio
import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from music_library.identities import identity_user_id

from .config import McpSettings


IdentityResolver = Callable[[str, str], str | None]


def _scopes(claims: dict[str, Any]) -> list[str]:
    value = claims.get("scope", claims.get("scp", []))
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


class TuneOpsTokenVerifier(TokenVerifier):
    """Validate an IdP JWT and attach its linked internal TuneOps user ID."""

    def __init__(
        self,
        settings: McpSettings,
        *,
        jwks_client: Any | None = None,
        identity_resolver: IdentityResolver = identity_user_id,
    ):
        self.settings = settings
        self._jwks = jwks_client or jwt.PyJWKClient(settings.jwks_url, cache_keys=True)
        self._identity_resolver = identity_resolver

    def _verify(self, token: str) -> AccessToken | None:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.audience,
                issuer=self.settings.issuer_url,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
            subject = str(claims.get("sub") or "").strip()
            if not subject:
                return None
            user_id = self._identity_resolver(self.settings.issuer_url, subject)
            if not user_id:
                return None
            granted_scopes = _scopes(claims)
            client_id = str(
                claims.get("client_id") or claims.get("azp") or claims.get("aud") or ""
            )
            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=granted_scopes,
                expires_at=int(claims["exp"]),
                resource=self.settings.resource_url,
                subject=subject,
                claims={"tuneops_user_id": user_id},
            )
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        # JWKS retrieval and Turso identity resolution are synchronous and must
        # not block the ASGI event loop.
        return await anyio.to_thread.run_sync(self._verify, token)


def tuneops_user_id(access_token: AccessToken | None) -> str | None:
    if access_token is None or not isinstance(access_token.claims, dict):
        return None
    value = str(access_token.claims.get("tuneops_user_id") or "").strip()
    return value or None
