"""FastAPI application serving the local MusicSync API and React build."""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import main as engine
from music_library.telemetry import begin_database_metrics, end_database_metrics

from . import auth
from .api.router import api_router
from .jobs import JOBS
from .mcp.config import (
    McpConfigurationError,
    SUPPORTED_SCOPES,
    load_settings as load_mcp_settings,
)
from .mcp.server import create_mcp_http_app, create_mcp_server


LOGGER = logging.getLogger("musicsync")
ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine.configure_logging()
    LOGGER.info("fastapi.start root=%s frontend_dist=%s", ROOT, FRONTEND_DIST)
    mcp_server = getattr(_app.state, "mcp_server", None)
    try:
        if mcp_server is None:
            yield
        else:
            async with mcp_server.session_manager.run():
                yield
    finally:
        JOBS.shutdown()
        LOGGER.info("fastapi.stop")


def _error(request: Request, status: int, code: str, message: str, details=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="MusicSync local API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    try:
        mcp_settings = load_mcp_settings()
    except McpConfigurationError:
        mcp_settings = None
    if mcp_settings is not None:
        mcp_server = create_mcp_server(mcp_settings)
        app.state.mcp_server = mcp_server
        app.state.mcp_settings = mcp_settings
        app.mount("/mcp", create_mcp_http_app(mcp_server, mcp_settings), name="mcp")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        database_metrics, metrics_token = begin_database_metrics()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            # A deployment replaces content-hashed Vite assets. The SPA shell
            # must therefore be revalidated on every document load, otherwise
            # an old cached index can reference asset hashes that no longer
            # exist on the current Vercel deployment.
            content_type = response.headers.get("content-type", "")
            if content_type.lower().startswith("text/html"):
                response.headers["Cache-Control"] = "no-store"
            if not os.getenv("VERCEL"):
                response.headers["Server-Timing"] = (
                    f"db;dur={database_metrics.database_ms:.1f}"
                )
            if request.url.path != "/api/v1/health":
                content_length = response.headers.get("content-length", "")
                response_bytes = int(content_length) if content_length.isdigit() else -1
                LOGGER.info(
                    "http.complete request_id=%s method=%s path=%s status=%d "
                    "duration_ms=%d db_connections=%d db_statements=%d "
                    "db_pipelines=%d db_ms=%d db_rows=%d response_bytes=%d",
                    request_id,
                    request.method,
                    request.url.path,
                    response.status_code,
                    round((time.perf_counter() - started) * 1000),
                    database_metrics.connections,
                    database_metrics.statements,
                    database_metrics.pipeline_calls,
                    round(database_metrics.database_ms),
                    database_metrics.rows_decoded,
                    response_bytes,
                )
            return response
        finally:
            end_database_metrics(metrics_token)

    @app.middleware("http")
    async def require_google_login(request: Request, call_next):
        if not auth.required():
            return await call_next(request)
        path = request.url.path
        public = (
            path.startswith("/api/v1/auth/")
            or path.startswith("/assets/")
            or path == "/favicon.ico"
            or path == "/login"
            or (
                mcp_settings is not None
                and (
                    path.startswith("/mcp")
                    or path.startswith("/.well-known/oauth-protected-resource/")
                )
            )
        )
        if public:
            return await call_next(request)
        user = auth.session_user(request)
        if user:
            request.state.user = user
            return await call_next(request)
        if path.startswith("/api/"):
            return _error(request, 401, "authentication_required", "Sign in with Google first.")
        return RedirectResponse(f"/login?return_to={path}", status_code=303)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        return _error(request, exc.status_code, "request_failed", detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error(request, 422, "validation_error", "Check the submitted values.", exc.errors())

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        LOGGER.exception(
            "http.failed request_id=%s method=%s path=%s",
            getattr(request.state, "request_id", "-"),
            request.method,
            request.url.path,
        )
        return _error(request, 500, "internal_error", "MusicSync could not complete the request.")

    app.include_router(api_router)

    if mcp_settings is not None:
        resource_metadata = {
            "resource": mcp_settings.resource_url,
            "authorization_servers": [mcp_settings.issuer_url],
            "scopes_supported": list(SUPPORTED_SCOPES),
            "bearer_methods_supported": ["header"],
        }

        @app.get(
            "/.well-known/oauth-protected-resource/mcp",
            include_in_schema=False,
        )
        @app.get(
            "/.well-known/oauth-protected-resource/mcp/",
            include_in_schema=False,
        )
        async def mcp_resource_metadata() -> dict[str, object]:
            return resource_metadata

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page(error: str = "", return_to: str = "/"):
        if auth.required() and not auth.configured():
            return HTMLResponse(
                auth.login_html(auth.configuration_error(), return_to), status_code=503
            )
        message = "Google sign-in failed. Please try again." if error else ""
        return HTMLResponse(auth.login_html(message, return_to))

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def unknown_api(path: str, request: Request):
        return _error(request, 404, "not_found", "API route was not found.")

    # FastAPI's frontend registration is understood by Vercel's Python build
    # system, which bundles/promotes the complete hashed Vite asset directory.
    # API and login routes above retain precedence; SPA navigation falls back
    # to index.html. check_dir=False keeps API-only test environments importable
    # before the frontend build has run.
    app.frontend(
        "/",
        directory=FRONTEND_DIST,
        fallback="index.html",
        check_dir=False,
    )

    return app


app = create_app()
