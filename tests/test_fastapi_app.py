from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_built_frontend_serves_hashed_assets_and_spa_routes(monkeypatch):
    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    assets = list((dist / "assets").glob("index-*.js"))
    if not assets:
        pytest.skip("frontend has not been built")
    monkeypatch.setenv("TUNEOPS_AUTH_REQUIRED", "false")
    client = TestClient(create_app())

    asset = client.get(f"/assets/{assets[0].name}")
    route = client.get("/liked-tracks", headers={"Accept": "text/html"})

    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]
    assert route.status_code == 200
    assert "<div id=\"root\"></div>" in route.text


def test_info_and_unknown_api_route_use_the_json_api_boundary():
    client = TestClient(create_app())

    info = client.get("/api/v1/info")
    missing = client.get("/api/v1/does-not-exist")

    assert info.status_code == 200
    assert info.json()["ui"] == "react"
    assert info.headers["server-timing"].startswith("db;dur=")
    assert missing.status_code == 404
    body = missing.json()["error"]
    assert body["code"] == "not_found"
    assert body["request_id"]


def test_validation_errors_are_sanitized_json_not_spa_html():
    client = TestClient(create_app())

    response = client.get("/api/v1/collections/liked/liked/tracks?limit=501")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["request_id"]


def test_openapi_contract_advertises_react_critical_routes_and_response_fields():
    contract = create_app().openapi()
    paths = contract["paths"]

    for path in [
        "/api/v1/navigation",
        "/api/v1/collections/{kind}/{collection_id}/tracks",
        "/api/v1/tracks/playlist-action",
        "/api/v1/settings",
        "/api/v1/settings/my-mixes",
        "/api/v1/sync/mappings",
        "/api/v1/mixes/discover-tidal",
        "/api/v1/mixes/{folder_name}/import-tidal",
        "/api/v1/pending-tracks/{pending_id}/refresh",
    ]:
        assert path in paths

    schemas = contract["components"]["schemas"]
    assert {"changed", "skipped", "failed", "message"}.issubset(
        schemas["PlaylistActionResponse"]["properties"]
    )
    assert {"items", "total", "offset", "has_more", "stats"}.issubset(
        schemas["TrackPage"]["properties"]
    )
    assert {"id", "state", "message", "error"}.issubset(
        schemas["JobResponse"]["properties"]
    )
