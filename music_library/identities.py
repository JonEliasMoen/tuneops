"""Stable TuneOps application identities shared by web and MCP auth."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from music_library.credentials import current_user_id
from music_library.database import DATABASE_PATH, connect, connect_readonly, initialize


GOOGLE_ISSUER = "https://accounts.google.com"


class IdentityError(RuntimeError):
    """Raised when an external identity cannot resolve to an active user."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_identity(issuer: str, subject: str) -> tuple[str, str]:
    normalized_issuer = str(issuer or "").strip().rstrip("/")
    normalized_subject = str(subject or "").strip()
    if not normalized_issuer or not normalized_subject:
        raise IdentityError("The external identity is incomplete")
    return normalized_issuer, normalized_subject


def identity_user_id(
    issuer: str,
    subject: str,
    *,
    path: Path = DATABASE_PATH,
) -> str | None:
    """Resolve an already-linked external identity without changing state."""
    normalized_issuer, normalized_subject = _normalized_identity(issuer, subject)
    initialize(path)
    with connect_readonly(path) as connection:
        row = connection.execute(
            """
            SELECT users.id
            FROM external_identities AS identities
            JOIN app_users AS users ON users.id=identities.user_id
            WHERE identities.issuer=? AND identities.subject=?
              AND users.status='active'
            """,
            (normalized_issuer, normalized_subject),
        ).fetchone()
    return str(row["id"]) if row else None


def link_external_identity(
    user_id: str,
    issuer: str,
    subject: str,
    *,
    email: str = "",
    display_name: str = "",
    path: Path = DATABASE_PATH,
) -> str:
    """Link an external subject without ever reassigning an existing link."""
    resolved_user_id = str(uuid.UUID(user_id))
    normalized_issuer, normalized_subject = _normalized_identity(issuer, subject)
    normalized_email = str(email or "").strip().casefold()
    normalized_name = str(display_name or "").strip()
    now = _now()
    initialize(path)
    with connect(path) as connection:
        existing = connection.execute(
            """
            SELECT user_id
            FROM external_identities
            WHERE issuer=? AND subject=?
            """,
            (normalized_issuer, normalized_subject),
        ).fetchone()
        if existing is not None and str(existing["user_id"]) != resolved_user_id:
            raise IdentityError("The external identity is already linked to another user")
        connection.execute(
            """
            INSERT INTO app_users(id, display_name, status, created_at, updated_at)
            VALUES(?, ?, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                display_name=CASE
                    WHEN excluded.display_name != '' THEN excluded.display_name
                    ELSE app_users.display_name
                END,
                updated_at=excluded.updated_at
            """,
            (resolved_user_id, normalized_name, now, now),
        )
        connection.execute(
            """
            INSERT INTO external_identities(
                user_id, issuer, subject, email, display_name, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issuer, subject) DO UPDATE SET
                email=excluded.email,
                display_name=excluded.display_name,
                updated_at=excluded.updated_at
            """,
            (
                resolved_user_id,
                normalized_issuer,
                normalized_subject,
                normalized_email,
                normalized_name,
                now,
                now,
            ),
        )
        row = connection.execute(
            """
            SELECT identities.user_id, users.status
            FROM external_identities AS identities
            JOIN app_users AS users ON users.id=identities.user_id
            WHERE identities.issuer=? AND identities.subject=?
            """,
            (normalized_issuer, normalized_subject),
        ).fetchone()
    if row is None or str(row["status"]) != "active":
        raise IdentityError("The TuneOps user is not active")
    linked_user_id = str(row["user_id"])
    return linked_user_id


def bootstrap_google_identity(
    claims: dict[str, Any],
    *,
    path: Path = DATABASE_PATH,
) -> str:
    """Link an allowlisted Google login to the current single-user account."""
    return link_external_identity(
        current_user_id(),
        GOOGLE_ISSUER,
        str(claims.get("sub") or ""),
        email=str(claims.get("email") or ""),
        display_name=str(claims.get("name") or claims.get("email") or ""),
        path=path,
    )
