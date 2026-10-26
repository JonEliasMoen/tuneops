"""OAuth bearer-token verification for the TuneOps MCP resource server."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

import anyio
import jwt
import requests
from mcp.server.auth.provider import AccessToken, TokenVerifier

from music_library.identities import identity_user_id

from .config import McpSettings


IdentityResolver = Callable[[str, str], str | None]
TokenInfoLoader = Callable[[str], dict[str, Any]]


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


def _google_token_info(token: str) -> dict[str, Any]:
    response = requests.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"access_token": token},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Google token info was not an object")
    return payload


class GoogleTokenVerifier(TokenVerifier):
    """Validate a Google access token used by ChatGPT's OAuth connection."""

    def __init__(
        self,
        settings: McpSettings,
        *,
        token_info_loader: TokenInfoLoader = _google_token_info,
        identity_resolver: IdentityResolver = identity_user_id,
    ):
        self.settings = settings
        self._token_info_loader = token_info_loader
        self._identity_resolver = identity_resolver

    def _verify(self, token: str) -> AccessToken | None:
        try:
            claims = self._token_info_loader(token)
            token_client = str(
                claims.get("aud")
                or claims.get("audience")
                or claims.get("azp")
                or claims.get("issued_to")
                or ""
            ).strip()
            if token_client != self.settings.oauth_client_id:
                return None

            subject = str(claims.get("sub") or claims.get("user_id") or "").strip()
            if not subject:
                return None
            granted_scopes = _scopes(claims)
            if "openid" not in granted_scopes:
                return None

            expires_in = int(claims.get("expires_in") or 0)
            expires_at = int(claims.get("exp") or 0)
            if expires_at <= 0 and expires_in > 0:
                expires_at = int(time.time()) + expires_in
            if expires_at <= int(time.time()):
                return None

            user_id = self._identity_resolver(self.settings.issuer_url, subject)
            if not user_id:
                return None
            return AccessToken(
                token=token,
                client_id=token_client,
                scopes=granted_scopes,
                expires_at=expires_at,
                resource=self.settings.resource_url,
                subject=subject,
                claims={"tuneops_user_id": user_id},
            )
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        # Google verification and Turso identity resolution are synchronous.
        return await anyio.to_thread.run_sync(self._verify, token)


def token_verifier_for(settings: McpSettings) -> TokenVerifier:
    if settings.auth_provider == "google":
        return GoogleTokenVerifier(settings)
    return TuneOpsTokenVerifier(settings)


def tuneops_user_id(access_token: AccessToken | None) -> str | None:
    if access_token is None or not isinstance(access_token.claims, dict):
        return None
    value = str(access_token.claims.get("tuneops_user_id") or "").strip()
    return value or None
