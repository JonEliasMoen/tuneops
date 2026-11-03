"""TuneOps OAuth authorization server backed by Google identity and SQLite/Turso."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.responses import RedirectResponse

from backend.app import auth as web_auth
from backend.music_library.database import connect, connect_readonly
from backend.music_library.identities import GOOGLE_ISSUER, identity_user_id

from .config import LIBRARY_READ, PLAYLISTS_WRITE, PROFILE_READ, McpSettings


ACCESS_TTL = 60 * 60
REFRESH_TTL = 90 * 24 * 60 * 60
CODE_TTL = 10 * 60
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
ALLOWED_SCOPES = (PROFILE_READ, LIBRARY_READ, PLAYLISTS_WRITE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _token() -> str:
    return secrets.token_urlsafe(48)


def _scopes_json(scopes: list[str]) -> str:
    return json.dumps(list(dict.fromkeys(scopes)), separators=(",", ":"))


def _scopes(value: str) -> list[str]:
    result = json.loads(value)
    return [str(item) for item in result] if isinstance(result, list) else []


class TuneOpsOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, settings: McpSettings):
        self.settings = settings

    @property
    def google_callback_url(self) -> str:
        return self.settings.issuer_url.rstrip("/") + "/oauth/google/callback"

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if not secrets.compare_digest(client_id, self.settings.oauth_client_id):
            return None
        import os

        redirects = [
            item.strip()
            for item in os.getenv(
                "TUNEOPS_MCP_REDIRECT_URIS",
                "https://chatgpt.com/connector_platform_oauth_redirect",
            ).split(",")
            if item.strip()
        ]
        return OAuthClientInformationFull(
            client_id=self.settings.oauth_client_id,
            client_secret=self.settings.oauth_client_secret,
            client_name="ChatGPT",
            redirect_uris=[AnyUrl(item) for item in redirects],
            scope=" ".join(ALLOWED_SCOPES),
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("Dynamic client registration is disabled")

    def _begin_authorization(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        requested = params.scopes or list(ALLOWED_SCOPES)
        if any(scope not in ALLOWED_SCOPES for scope in requested):
            raise AuthorizeError("invalid_scope", "An unsupported TuneOps scope was requested")
        resource = params.resource or self.settings.resource_url
        if resource.rstrip("/") != self.settings.resource_url.rstrip("/"):
            raise AuthorizeError("invalid_target", "The requested MCP resource is not TuneOps")
        state = _token()
        nonce = _token()
        verifier = _token()
        challenge = hashlib.sha256(verifier.encode()).digest()
        import base64

        google_challenge = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
        now = int(time.time())
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_authorization_transactions(
                    state_hash, client_id, redirect_uri, redirect_uri_provided,
                    code_challenge, scopes_json, resource, client_state,
                    google_nonce, google_code_verifier, expires_at, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _hash(state), client.client_id, str(params.redirect_uri),
                    int(params.redirect_uri_provided_explicitly), params.code_challenge,
                    _scopes_json(requested), resource, params.state,
                    nonce, verifier, now + CODE_TTL, _now_iso(),
                ),
            )
        query = urlencode(
            {
                "client_id": web_auth._client_id(),
                "redirect_uri": self.google_callback_url,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "nonce": nonce,
                "code_challenge": google_challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
        return f"{GOOGLE_AUTH_URL}?{query}"

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        return await asyncio.to_thread(self._begin_authorization, client, params)

    def _finish_google(self, code: str, state: str) -> str:
        now = int(time.time())
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_authorization_transactions WHERE state_hash=?",
                (_hash(state),),
            ).fetchone()
            if row is None or int(row["expires_at"]) <= now:
                raise AuthorizeError("access_denied", "The sign-in request expired")
            connection.execute(
                "DELETE FROM oauth_authorization_transactions WHERE state_hash=?",
                (_hash(state),),
            )
        try:
            response = requests.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": web_auth._client_id(),
                    "client_secret": web_auth._client_secret(),
                    "code": code,
                    "code_verifier": str(row["google_code_verifier"]),
                    "grant_type": "authorization_code",
                    "redirect_uri": self.google_callback_url,
                },
                timeout=20,
            )
            response.raise_for_status()
            claims = id_token.verify_oauth2_token(
                response.json().get("id_token", ""), GoogleRequest(), web_auth._client_id()
            )
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise AuthorizeError("access_denied", "Google sign-in failed") from exc
        email = str(claims.get("email") or "").strip().casefold()
        if (
            claims.get("nonce") != row["google_nonce"]
            or claims.get("email_verified") is not True
            or email not in web_auth.allowed_emails()
        ):
            raise AuthorizeError("access_denied", "This Google account is not allowed")
        subject = str(claims.get("sub") or "")
        user_id = identity_user_id(GOOGLE_ISSUER, subject)
        if not user_id:
            raise AuthorizeError("access_denied", "This Google identity is not linked")
        authorization_code = _token()
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_authorization_codes(
                    code_hash, user_id, client_id, redirect_uri,
                    redirect_uri_provided, code_challenge, scopes_json,
                    resource, expires_at, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _hash(authorization_code), user_id, row["client_id"],
                    row["redirect_uri"], row["redirect_uri_provided"],
                    row["code_challenge"], row["scopes_json"], row["resource"],
                    now + CODE_TTL, _now_iso(),
                ),
            )
        parameters = {"code": authorization_code}
        if row["client_state"]:
            parameters["state"] = str(row["client_state"])
        return str(row["redirect_uri"]) + "?" + urlencode(parameters)

    async def google_callback(self, request: Request):
        error = request.query_params.get("error")
        if error:
            return RedirectResponse("/login?error=oauth_denied", status_code=303)
        try:
            target = await asyncio.to_thread(
                self._finish_google,
                request.query_params.get("code", ""),
                request.query_params.get("state", ""),
            )
        except AuthorizeError:
            return RedirectResponse("/login?error=oauth_failed", status_code=303)
        return RedirectResponse(target, status_code=303)

    def _load_code(self, client_id: str, raw_code: str) -> AuthorizationCode | None:
        with connect_readonly() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_authorization_codes WHERE code_hash=? AND client_id=?",
                (_hash(raw_code), client_id),
            ).fetchone()
        if row is None or int(row["expires_at"]) <= int(time.time()):
            return None
        return AuthorizationCode(
            code=raw_code, scopes=_scopes(row["scopes_json"]),
            expires_at=float(row["expires_at"]), client_id=client_id,
            code_challenge=row["code_challenge"], redirect_uri=AnyUrl(row["redirect_uri"]),
            redirect_uri_provided_explicitly=bool(row["redirect_uri_provided"]),
            resource=row["resource"], subject=row["user_id"],
        )

    async def load_authorization_code(self, client, authorization_code):
        return await asyncio.to_thread(self._load_code, client.client_id, authorization_code)

    def _issue(self, user_id: str, client_id: str, scopes: list[str], resource: str | None,
               *, code_hash: str | None = None, grant_id: str | None = None,
               previous_refresh_hash: str | None = None) -> OAuthToken:
        now = int(time.time())
        access, refresh = _token(), _token()
        grant_id = grant_id or str(uuid.uuid4())
        timestamp = _now_iso()
        with connect() as connection:
            if code_hash:
                deleted = connection.execute(
                    "DELETE FROM oauth_authorization_codes WHERE code_hash=?", (code_hash,)
                )
                if deleted.rowcount == 0:
                    raise TokenError("invalid_grant", "Authorization code was already used")
                connection.execute(
                    """INSERT INTO oauth_token_grants(
                        id,user_id,client_id,scopes_json,resource,refresh_token_hash,
                        refresh_expires_at,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (grant_id,user_id,client_id,_scopes_json(scopes),resource,_hash(refresh),
                     now + REFRESH_TTL,timestamp,timestamp),
                )
            else:
                rotated = connection.execute(
                    """UPDATE oauth_token_grants SET refresh_token_hash=?,
                        refresh_expires_at=?,updated_at=? WHERE id=? AND revoked_at IS NULL
                        AND refresh_token_hash=?""",
                    (_hash(refresh), now + REFRESH_TTL, timestamp, grant_id,
                     previous_refresh_hash),
                )
                if rotated.rowcount == 0:
                    raise TokenError("invalid_grant", "Refresh token was already used")
                connection.execute(
                    "DELETE FROM oauth_access_tokens WHERE grant_id=?", (grant_id,)
                )
            connection.execute(
                "INSERT INTO oauth_access_tokens(token_hash,grant_id,expires_at,created_at) VALUES(?,?,?,?)",
                (_hash(access), grant_id, now + ACCESS_TTL, timestamp),
            )
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL,
                          refresh_token=refresh, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        return await asyncio.to_thread(
            self._issue, authorization_code.subject, client.client_id,
            authorization_code.scopes, authorization_code.resource,
            code_hash=_hash(authorization_code.code),
        )

    def _load_refresh(self, client_id: str, token: str) -> RefreshToken | None:
        with connect_readonly() as connection:
            row = connection.execute(
                """SELECT * FROM oauth_token_grants
                   WHERE refresh_token_hash=? AND client_id=? AND revoked_at IS NULL""",
                (_hash(token), client_id),
            ).fetchone()
        if row is None or int(row["refresh_expires_at"]) <= int(time.time()):
            return None
        return RefreshToken(token=token, client_id=client_id,
                            scopes=_scopes(row["scopes_json"]),
                            expires_at=int(row["refresh_expires_at"]),
                            resource=row["resource"], subject=row["user_id"])

    async def load_refresh_token(self, client, refresh_token):
        return await asyncio.to_thread(self._load_refresh, client.client_id, refresh_token)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        requested = scopes or refresh_token.scopes
        if any(scope not in refresh_token.scopes for scope in requested):
            raise TokenError("invalid_scope", "Refresh cannot expand granted scopes")
        with connect_readonly() as connection:
            row = connection.execute(
                "SELECT id FROM oauth_token_grants WHERE refresh_token_hash=?",
                (_hash(refresh_token.token),),
            ).fetchone()
        if row is None:
            raise TokenError("invalid_grant", "Refresh token was already used")
        return await asyncio.to_thread(
            self._issue, refresh_token.subject, client.client_id, requested,
            refresh_token.resource, grant_id=str(row["id"]),
            previous_refresh_hash=_hash(refresh_token.token),
        )

    def _load_access(self, token: str) -> AccessToken | None:
        with connect_readonly() as connection:
            row = connection.execute(
                """SELECT g.user_id,g.client_id,g.scopes_json,g.resource,a.expires_at
                   FROM oauth_access_tokens a JOIN oauth_token_grants g ON g.id=a.grant_id
                   JOIN app_users u ON u.id=g.user_id
                   WHERE a.token_hash=? AND g.revoked_at IS NULL AND u.status='active'""",
                (_hash(token),),
            ).fetchone()
        if row is None or int(row["expires_at"]) <= int(time.time()):
            return None
        return AccessToken(token=token, client_id=row["client_id"],
                           scopes=_scopes(row["scopes_json"]),
                           expires_at=int(row["expires_at"]), resource=row["resource"],
                           subject=row["user_id"], claims={"tuneops_user_id": row["user_id"]})

    async def load_access_token(self, token):
        return await asyncio.to_thread(self._load_access, token)

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)

    async def revoke_token(self, token):
        def revoke() -> None:
            with connect() as connection:
                if isinstance(token, RefreshToken):
                    connection.execute(
                        "UPDATE oauth_token_grants SET revoked_at=?,updated_at=? WHERE refresh_token_hash=?",
                        (_now_iso(), _now_iso(), _hash(token.token)),
                    )
                else:
                    connection.execute(
                        """UPDATE oauth_token_grants SET revoked_at=?,updated_at=? WHERE id IN
                           (SELECT grant_id FROM oauth_access_tokens WHERE token_hash=?)""",
                        (_now_iso(), _now_iso(), _hash(token.token)),
                    )
        await asyncio.to_thread(revoke)

