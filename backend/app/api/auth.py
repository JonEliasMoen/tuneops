from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from .. import auth


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/session")
def auth_session(request: Request) -> dict[str, object]:
    user = auth.session_user(request)
    return {
        "required": auth.required(),
        "configured": auth.configured(),
        "authenticated": bool(user),
        "user": user,
    }


@router.get("/google/login", name="google_auth_login", include_in_schema=False)
def google_auth_login(request: Request, return_to: str = Query(default="/")) -> RedirectResponse:
    try:
        target, transaction = auth.begin_login(request, return_to)
    except auth.AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response = RedirectResponse(target, status_code=307)
    response.set_cookie(
        auth.OAUTH_COOKIE,
        transaction,
        max_age=auth.OAUTH_MAX_AGE,
        httponly=True,
        secure=auth.secure_cookie(request),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback", name="google_auth_callback", include_in_schema=False)
def google_auth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
) -> RedirectResponse:
    if error or not code:
        return RedirectResponse("/login?error=denied", status_code=303)
    try:
        user, return_to = auth.finish_login(request, code, state)
    except auth.AuthError:
        return RedirectResponse("/login?error=failed", status_code=303)
    response = RedirectResponse(return_to, status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.sign(user),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        secure=auth.secure_cookie(request),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(auth.OAUTH_COOKIE, path="/")
    return response


@router.post("/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response
