"""Google OIDC login and signed browser sessions for the hosted application."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests
from fastapi import Request
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from music_library.credentials import CredentialConfigurationError, current_user_id
from music_library.identities import IdentityError, bootstrap_google_identity


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SESSION_COOKIE = "tuneops_session"
OAUTH_COOKIE = "tuneops_google_oauth"
SESSION_MAX_AGE = 7 * 24 * 60 * 60
OAUTH_MAX_AGE = 10 * 60


class AuthError(RuntimeError):
    pass


def required() -> bool:
    value = os.getenv("TUNEOPS_AUTH_REQUIRED")
    if value is not None:
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(os.getenv("VERCEL"))


def _client_id() -> str:
    return (os.getenv("GOOGLE_SIGNIN_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (
        os.getenv("GOOGLE_SIGNIN_CLIENT_SECRET")
        or os.getenv("GOOGLE_CLIENT_SECRET")
        or ""
    ).strip()


def _session_secret() -> str:
    return os.getenv("TUNEOPS_SESSION_SECRET", "").strip()


def allowed_emails() -> set[str]:
    raw = os.getenv("TUNEOPS_ALLOWED_EMAILS", "")
    return {item.strip().casefold() for item in raw.split(",") if item.strip()}


def _internal_user_configured() -> bool:
    try:
        current_user_id()
    except CredentialConfigurationError:
        return False
    return True


def configured() -> bool:
    return bool(
        _client_id()
        and _client_secret()
        and len(_session_secret()) >= 32
        and allowed_emails()
        and _internal_user_configured()
    )


def configuration_error() -> str:
    missing: list[str] = []
    if not _client_id():
        missing.append("GOOGLE_SIGNIN_CLIENT_ID (or GOOGLE_CLIENT_ID)")
    if not _client_secret():
        missing.append("GOOGLE_SIGNIN_CLIENT_SECRET (or GOOGLE_CLIENT_SECRET)")
    if len(_session_secret()) < 32:
        missing.append("TUNEOPS_SESSION_SECRET (at least 32 characters)")
    if not allowed_emails():
        missing.append("TUNEOPS_ALLOWED_EMAILS")
    if not _internal_user_configured():
        missing.append("TUNEOPS_LOCAL_USER_ID (UUID)")
    return "Missing: " + ", ".join(missing) if missing else ""


def redirect_uri(request: Request) -> str:
    explicit = os.getenv("GOOGLE_SIGNIN_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    return str(request.url_for("google_auth_callback"))


def secure_cookie(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return bool(os.getenv("VERCEL")) or forwarded == "https" or request.url.scheme == "https"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign(payload: dict[str, Any]) -> str:
    secret = _session_secret()
    if not secret:
        raise AuthError("TUNEOPS_SESSION_SECRET is not configured")
    body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def unsign(value: str, *, max_age: int | None = None) -> dict[str, Any] | None:
    try:
        body, supplied = value.split(".", 1)
        expected = _encode(
            hmac.new(_session_secret().encode(), body.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied, expected):
            return None
        payload = json.loads(_decode(body))
        issued_at = int(payload.get("iat") or 0)
        if max_age is not None and (issued_at <= 0 or time.time() - issued_at > max_age):
            return None
        if payload.get("exp") and time.time() >= int(payload["exp"]):
            return None
        return payload if isinstance(payload, dict) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def session_user(request: Request) -> dict[str, Any] | None:
    value = request.cookies.get(SESSION_COOKIE, "")
    payload = unsign(value, max_age=SESSION_MAX_AGE) if value else None
    if not payload or not payload.get("sub"):
        return None
    # Sessions issued before application-identity linking remain usable during
    # the single-user cutover. A fresh login persists the Google link and puts
    # the same stable ID directly in the signed cookie.
    if not payload.get("user_id"):
        try:
            payload["user_id"] = current_user_id()
        except CredentialConfigurationError:
            return None
    return payload


def begin_login(request: Request, return_to: str = "/") -> tuple[str, str]:
    if not configured():
        raise AuthError(configuration_error())
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _encode(hashlib.sha256(verifier.encode()).digest())
    safe_return = return_to if return_to.startswith("/") and not return_to.startswith("//") else "/"
    transaction = sign({
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "return_to": safe_return,
        "iat": int(time.time()),
    })
    target = f"{AUTH_URL}?{urlencode({
        'client_id': _client_id(),
        'redirect_uri': redirect_uri(request),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'nonce': nonce,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'prompt': 'select_account',
    })}"
    return target, transaction


def finish_login(request: Request, code: str, state: str) -> tuple[dict[str, Any], str]:
    transaction = unsign(request.cookies.get(OAUTH_COOKIE, ""), max_age=OAUTH_MAX_AGE)
    if not transaction or not state or not hmac.compare_digest(state, str(transaction.get("state") or "")):
        raise AuthError("Google sign-in state was invalid or expired")
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "code": code,
                "code_verifier": str(transaction["verifier"]),
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(request),
            },
            timeout=20,
        )
        response.raise_for_status()
        token = response.json()
        claims = id_token.verify_oauth2_token(
            token.get("id_token", ""), GoogleRequest(), _client_id()
        )
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise AuthError("Google could not complete sign-in") from exc
    if claims.get("nonce") != transaction.get("nonce"):
        raise AuthError("Google sign-in nonce was invalid")
    email = str(claims.get("email") or "").strip().casefold()
    if claims.get("email_verified") is not True or email not in allowed_emails():
        raise AuthError("This Google account is not allowed to access TuneOps")
    now = int(time.time())
    session = {
        "sub": str(claims.get("sub") or ""),
        "email": email,
        "name": str(claims.get("name") or email),
        "picture": str(claims.get("picture") or ""),
        "iat": now,
        "exp": now + SESSION_MAX_AGE,
    }
    if not session["sub"]:
        raise AuthError("Google did not return a stable account identifier")
    try:
        session["user_id"] = bootstrap_google_identity(claims)
    except IdentityError as exc:
        raise AuthError("This Google account is not linked to an active TuneOps user") from exc
    return session, str(transaction.get("return_to") or "/")


def login_html(message: str = "", return_to: str = "/") -> str:
    detail = f'<p class="error">{message}</p>' if message else ""
    safe_return = return_to if return_to.startswith("/") and not return_to.startswith("//") else "/"
    login_target = "/api/v1/auth/google/login?" + urlencode({"return_to": safe_return})
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TuneOps sign in</title><style>
body{{margin:0;background:#0c1117;color:#e8edf2;font:16px system-ui;display:grid;place-items:center;min-height:100vh}}
main{{width:min(420px,calc(100% - 48px));padding:34px;background:#121a23;border:1px solid #2b3948;border-radius:18px}}
h1{{color:#7ee2ae;margin-top:0}}p{{color:#aebbc7;line-height:1.5}}a{{display:inline-block;margin-top:12px;padding:11px 16px;border-radius:8px;background:#7ee2ae;color:#07110d;text-decoration:none;font-weight:700}}.error{{color:#ff9ca7}}
</style></head><body><main><h1>TuneOps</h1><p>Sign in with the approved Google account.</p>{detail}
<a href="{login_target}">Continue with Google</a></main></body></html>"""
