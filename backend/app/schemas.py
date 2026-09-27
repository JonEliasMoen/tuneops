"""Shared HTTP schemas for the MusicSync local API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


CollectionType = Literal[
    "liked", "playlist", "event", "source", "setlist", "watched_mix", "artist", "search", "history"
]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class ProviderStatus(BaseModel):
    connected: bool
    label: str = ""


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    database_ready: bool
    providers: dict[str, ProviderStatus]
    lastfm_api_key_configured: bool


class NavigationItem(BaseModel):
    id: str
    label: str
    path: str
    kind: str
    icon: str = ""
    children: list[dict[str, Any]] = Field(default_factory=list)


class NavigationGroup(BaseModel):
    id: str
    label: str
    items: list[NavigationItem] = Field(default_factory=list)


class NavigationResponse(BaseModel):
    tools: list[NavigationItem]
    groups: list[NavigationGroup]


class CollectionDescriptor(BaseModel):
    type: CollectionType
    id: str = ""
    name: str
    collection_type: str = ""


class ArtistCount(BaseModel):
    id: str
    name: str
    count: int


class CollectionStats(BaseModel):
    top_artists: list[ArtistCount] = Field(default_factory=list)
    artist_options: list[dict[str, str]] = Field(default_factory=list)
    bpm_min: float | None = None
    bpm_max: float | None = None
    vibe: str = ""
    vibe_count: int = 0


class TrackPage(BaseModel):
    collection: CollectionDescriptor
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int
    has_more: bool
    stats: CollectionStats


class DimensionUpdate(BaseModel):
    track_ids: list[str] = Field(min_length=1)
    dimension: str
    values: list[str]


class DimensionUpdateResponse(BaseModel):
    updated: dict[str, dict[str, list[str]]]


class DimensionToggle(BaseModel):
    track_ids: list[str] = Field(min_length=1)
    dimension: str
    value: str
    enable: bool


class PlaylistAction(BaseModel):
    action: Literal["add", "remove", "move"]
    track_ids: list[str] = Field(min_length=1, max_length=500)
    playlist_id: str = Field(min_length=1)
    source_playlist_id: str | None = None


class PlaylistActionResponse(BaseModel):
    action: Literal["add", "remove", "move"]
    changed: int
    skipped: int
    failed: int = 0
    message: str


class LikeTracksRequest(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=500)


class LikeTracksResponse(BaseModel):
    changed: int
    skipped: int
    failed: int = 0
    message: str


class WatchedMixAssociation(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=500)
    video_id: str = Field(min_length=1)


class AutoTagRequest(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=100)


class PublicSettings(BaseModel):
    dark_mode: bool = True
    tags_collapsed_by_default: bool = True
    ollama_model: str = "qwen3:4b"
    ollama_url: str = "http://127.0.0.1:11434"
    lastfm_username: str = ""
    history_top_tracks: int = Field(default=20, ge=1, le=100)
    spotify_search_delay_seconds: float = 0.75
    quick_views: list[dict[str, Any]] = Field(default_factory=list)
    lastfm_api_key_configured: bool = False


class SettingsPatch(BaseModel):
    dark_mode: bool | None = None
    tags_collapsed_by_default: bool | None = None
    ollama_model: str | None = None
    ollama_url: str | None = None
    lastfm_username: str | None = None
    history_top_tracks: int | None = Field(default=None, ge=1, le=100)
    spotify_search_delay_seconds: float | None = Field(default=None, ge=0, le=30)
    quick_views: list[dict[str, Any]] | None = None


class SyncMappings(BaseModel):
    playlists: list[dict[str, Any]]


class JobResponse(BaseModel):
    id: str
    kind: str
    state: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    phase: str = ""
    current: int = 0
    total: int | None = None
    message: str = ""
    result: Any | None = None
    error: str = ""
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class WatchedMixCreate(BaseModel):
    youtube_url: str


class WatchedMixUpdate(BaseModel):
    title: str = ""
    channel_name: str = ""
    upload_date: str = ""


class EventMediaUpdate(BaseModel):
    youtube_url: str = ""
    concert_archives_url: str = ""


class MixUrlsUpdate(BaseModel):
    youtube_url: str = ""
    tidal_url: str = ""


class MixTidalImportRequest(BaseModel):
    tidal_url: str = Field(min_length=1)


class TracklistParseRequest(BaseModel):
    text: str
    order: Literal["artist_title", "title_artist"] = "artist_title"


class TracklistSearchRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(max_length=500)


class TracklistLikeRequest(BaseModel):
    candidate: dict[str, Any]


class TracklistWatchRequest(BaseModel):
    artist: str
    title: str = Field(min_length=1)
    timestamp: str = ""
    raw_line: str = ""


class PendingLikeRequest(BaseModel):
    track_id: str = Field(min_length=1)
