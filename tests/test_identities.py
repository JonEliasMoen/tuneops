from __future__ import annotations

import uuid

import pytest

from music_library.database import connect_readonly
from music_library.identities import (
    GOOGLE_ISSUER,
    IdentityError,
    identity_user_id,
    link_external_identity,
)


def test_link_and_resolve_external_identity(tmp_path):
    path = tmp_path / "library.sqlite3"
    user_id = str(uuid.uuid4())

    linked = link_external_identity(
        user_id,
        GOOGLE_ISSUER,
        "google-subject",
        email="Jon@Example.com",
        display_name="Jon",
        path=path,
    )

    assert linked == user_id
    assert identity_user_id(GOOGLE_ISSUER, "google-subject", path=path) == user_id


def test_identity_metadata_can_change_but_owner_cannot(tmp_path):
    path = tmp_path / "library.sqlite3"
    first_user = str(uuid.uuid4())
    second_user = str(uuid.uuid4())
    link_external_identity(
        first_user,
        GOOGLE_ISSUER,
        "google-subject",
        email="old@example.com",
        path=path,
    )

    with pytest.raises(IdentityError, match="already linked"):
        link_external_identity(
            second_user,
            GOOGLE_ISSUER,
            "google-subject",
            email="new@example.com",
            path=path,
        )

    assert identity_user_id(GOOGLE_ISSUER, "google-subject", path=path) == first_user
    with connect_readonly(path) as connection:
        users = connection.execute("SELECT id FROM app_users ORDER BY id").fetchall()
    assert [row["id"] for row in users] == [first_user]


def test_incomplete_identity_is_rejected(tmp_path):
    with pytest.raises(IdentityError, match="incomplete"):
        identity_user_id("", "subject", path=tmp_path / "library.sqlite3")
