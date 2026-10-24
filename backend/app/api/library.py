from __future__ import annotations

from calendar import month_name
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

import main as engine

from music_library.database import (
    add_pending_track,
    add_tidal_liked_track,
    associate_tidal_tracks_with_watched_mix,
    pending_tracks,
    pending_track,
    delete_pending_track,
    delete_watched_mix,
    lastfm_history_navigation,
    tidal_artist_overview_page,
    save_tidal_event_links,
    resolve_pending_track,
    replace_tidal_tracks_dimension,
    tidal_dimensions_for_tracks,
    tidal_tags_for_tracks,
    tidal_indexed_playlists,
    tidal_event_with_links,
    save_watched_mix,
    set_watched_mix_rating,
    save_setlist_urls,
    watched_mix,
    watched_mixes,
    set_tidal_tracks_dimension_value,
    youtube_video_metadata,
)
from music_library.dimensions import DIMENSION_LABELS, DIMENSION_MAX_VALUES, DIMENSION_VALUES
from music_tools.mixes.service import (
    discover_mixes,
    fetch_youtube_metadata,
    mix_for,
    youtube_thumbnail_url,
    youtube_video_id,
)
from music_tools.youtube_analytics import service as youtube_service

from ..schemas import (
    ArtistOverviewPage,
    CollectionDescriptor,
    DimensionUpdate,
    DimensionUpdateResponse,
    DimensionToggle,
    EventMediaUpdate,
    MixUrlsUpdate,
    NavigationGroup,
    NavigationItem,
    NavigationResponse,
    PlaylistAction,
    PlaylistActionResponse,
    LikeTracksRequest,
    LikeTracksResponse,
    TrackPage,
    WatchedMixAssociation,
    WatchedMixCreate,
    WatchedMixUpdate,
    WatchedMixRatingUpdate,
    TracklistLikeRequest,
    TracklistParseRequest,
    TracklistWatchRequest,
    PendingLikeRequest,
)
from ..services.library import CollectionNotFound, collection_page, descriptor
from ..services.actions import TrackActionError, like_tidal_tracks, mutate_playlist_tracks
from ..services.navigation_cache import (
    get_navigation_snapshot,
    invalidate_navigation_snapshot,
    store_navigation_snapshot,
)
from music_tools.watched_mixes.tracklist import parse_tracklist


router = APIRouter(tags=["library"])
WATCHED_MIX_COVER_ROOT = Path(__file__).resolve().parents[3] / ".watched_mix_covers"


def _path(prefix: str, value: str) -> str:
    return f"/{prefix}/{quote(str(value), safe='')}"


def _web_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _watched_mix_cover_path(video_id: str) -> Path:
    safe_id = "".join(character for character in str(video_id) if character.isalnum() or character in {"-", "_"})
    if not safe_id or safe_id != str(video_id):
        raise HTTPException(status_code=404, detail="Watched mix cover was not found")
    return WATCHED_MIX_COVER_ROOT / f"{safe_id}.jpg"


def _local_file_cache_headers(path: Path) -> dict[str, str]:
    stat = path.stat()
    return {
        "Cache-Control": "public, max-age=86400, must-revalidate",
        "ETag": f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"',
    }


def _cache_watched_mix_cover(video_id: str) -> Path | None:
    path = _watched_mix_cover_path(video_id)
    if path.is_file():
        return path
    try:
        request = Request(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", headers={"User-Agent": "MusicSync/1.0"})
        with urlopen(request, timeout=10) as response:
            content = response.read(5 * 1024 * 1024)
            content_type = str(response.headers.get("Content-Type") or "")
        if not content or not content_type.startswith("image/"):
            return None
        WATCHED_MIX_COVER_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        return path
    except Exception:
        engine.LOGGER.warning("watched_mix.cover_cache_failed video_id=%s", video_id, exc_info=True)
        return None


@router.get("/navigation", response_model=NavigationResponse)
def navigation() -> NavigationResponse:
    cached = get_navigation_snapshot()
    if cached is not None:
        return NavigationResponse.model_validate(cached)
    tools = [
        NavigationItem(id="playlist-sync", label="Playlist sync", path="/", kind="tool", icon="⇄"),
        NavigationItem(id="liked", label="Liked tracks", path="/liked-tracks", kind="tool", icon="♥"),
        NavigationItem(id="search", label="Global search", path="/search", kind="tool", icon="⌕"),
        NavigationItem(id="artists", label="Artists", path="/artists", kind="tool", icon="♬"),
        NavigationItem(id="settings", label="Settings", path="/settings", kind="tool", icon="⚙"),
    ]
    indexed = tidal_indexed_playlists()
    groups: list[NavigationGroup] = []
    for kind, label, prefix in (
        ("playlist", "Playlists", "playlists"),
        ("event", "Events", "events"),
        ("source", "Sources", "sources"),
    ):
        groups.append(
            NavigationGroup(
                id=f"{kind}s",
                label=label,
                items=[
                    NavigationItem(
                        id=str(item["id"]),
                        label=str(item.get("name") or item["id"]),
                        path=_path(prefix, str(item["id"])),
                        kind=kind,
                        icon="♫",
                    )
                    for item in indexed
                    if str(item.get("collection_type") or "playlist") == kind
                ],
            )
        )
    settings = engine.load_runtime_settings()
    history_limit = max(1, min(100, int(settings.get("history_top_tracks", 20) or 20)))
    history_username = str(settings.get("lastfm_username", "") or "")
    history = lastfm_history_navigation(history_username, history_limit)
    history_rows = history["months"]
    history_years: dict[str, list[dict[str, str]]] = {
        str(row.get("year") or ""): [{
            "id": f"{row.get('year')}-overall",
            "label": "Overall",
            "path": _path("history", f"{row.get('year')}-overall"),
            "kind": "history_year_overall",
            "icon": "★",
        }]
        for row in history["years"]
        if str(row.get("year") or "")
    }
    for row in history_rows:
        year = str(row.get("year") or "")
        month = str(row.get("month") or "")
        if year and month:
            history_years.setdefault(year, [{
                "id": f"{year}-overall", "label": "Overall",
                "path": _path("history", f"{year}-overall"),
                "kind": "history_year_overall", "icon": "★",
            }]).append({
                "id": f"{year}-{month}",
                "label": month_name[int(month)],
                "path": _path("history", f"{year}-{month}"),
                "kind": "history_month",
                "icon": "◷",
            })
    groups.append(
        NavigationGroup(
            id="history",
            label="History",
            items=[
                NavigationItem(
                    id="overall",
                    label="Overall",
                    path="/history/overall",
                    kind="history_overall",
                    icon="★",
                ),
                *[
                NavigationItem(
                    id=year,
                    label=year,
                    path="",
                    kind="history_year",
                    icon="◷",
                    children=months,
                )
                for year, months in history_years.items()
                ],
            ],
        )
    )
    groups.append(
        NavigationGroup(
            id="my-mixes",
            label="My mixes",
            items=[
                NavigationItem(
                    id="overview",
                    label="Overview",
                    path="/mixes",
                    kind="mix_overview",
                    icon="▦",
                ),
                *[
                NavigationItem(
                    id=mix.folder_name,
                    label=mix.folder_name,
                    path=_path("mixes", mix.folder_name),
                    kind="setlist",
                    icon="♪",
                )
                for mix in discover_mixes()
                ],
            ],
        )
    )
    watched_items = [
        NavigationItem(id="add", label="Add mix", path="/watched-mixes", kind="watched_mix_add", icon="+"),
        NavigationItem(id="pending", label="Pending tracks", path="/watched-mixes/pending", kind="pending", icon="▷"),
    ]
    watched_items.extend(
        NavigationItem(
            id=str(item["video_id"]),
            label=str(item.get("title") or item["video_id"]),
            path=_path("watched-mixes", str(item["video_id"])),
            kind="watched_mix",
            icon="▶",
        )
        for item in watched_mixes()
    )
    groups.append(NavigationGroup(id="watched-mixes", label="Watched mixes", items=watched_items))
    response = NavigationResponse(tools=tools, groups=groups)
    store_navigation_snapshot(response.model_dump(mode="json"))
    return response


@router.get("/artists", response_model=ArtistOverviewPage)
def artist_overview(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    q: str = Query(default=""),
    sort_field: str = Query(default="name"),
    sort_direction: str = Query(default="asc"),
) -> ArtistOverviewPage:
    username = str(engine.load_runtime_settings().get("lastfm_username", "") or "")
    rows, total = tidal_artist_overview_page(
        username,
        limit=limit,
        offset=offset,
        query=q,
        sort_field=sort_field,
        sort_direction=sort_direction,
    )
    return ArtistOverviewPage(
        items=rows,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(rows) < total,
    )


@router.get("/collections/{kind}/{collection_id}", response_model=CollectionDescriptor)
def collection(kind: str, collection_id: str) -> CollectionDescriptor:
    try:
        return CollectionDescriptor.model_validate(descriptor(kind, collection_id))
    except CollectionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/events/{playlist_id}/media")
def event_media(playlist_id: str) -> dict[str, str]:
    """Read locally stored event links; never fetch Concert Archives here."""
    event = tidal_event_with_links(playlist_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event was not found")
    youtube_url = str(event.get("youtube_url") or "")
    return {
        "event_name": str(event["event_name"]),
        "youtube_url": youtube_url,
        "concert_archives_url": str(event.get("concert_archives_url") or ""),
        "thumbnail_url": youtube_thumbnail_url(youtube_url),
        "updated_at": str(event.get("updated_at") or ""),
    }


@router.put("/events/{playlist_id}/media")
def save_event_media(playlist_id: str, body: EventMediaUpdate) -> dict[str, str]:
    """Save user-provided event references without fetching either site."""
    youtube_url = _web_url(body.youtube_url)
    concert_url = _web_url(body.concert_archives_url)
    if body.youtube_url.strip() and not youtube_url:
        raise HTTPException(status_code=422, detail="YouTube must be a valid http(s) URL")
    if body.concert_archives_url.strip() and not concert_url:
        raise HTTPException(status_code=422, detail="Concert Archives must be a valid http(s) URL")
    if youtube_url and not youtube_video_id(youtube_url):
        raise HTTPException(status_code=422, detail="Enter a valid YouTube video URL")
    event = save_tidal_event_links(playlist_id, youtube_url, concert_url)
    if event is None:
        raise HTTPException(status_code=404, detail="Event was not found")
    return {
        "event_name": str(event["event_name"]),
        "youtube_url": str(event.get("youtube_url") or ""),
        "concert_archives_url": str(event.get("concert_archives_url") or ""),
        "thumbnail_url": youtube_thumbnail_url(str(event.get("youtube_url") or "")),
        "updated_at": str(event.get("updated_at") or ""),
    }


@router.get("/collections/{kind}/{collection_id}/tracks", response_model=TrackPage)
def tracks(
    kind: str,
    collection_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    sort_field: str = "",
    sort_direction: str = "",
    q: str = "",
    artist: list[str] = Query(default=[]),
    key: list[str] = Query(default=[]),
    rating: list[str] = Query(default=[]),
    tag: list[str] = Query(default=[]),
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    collection_type: list[str] = Query(default=[]),
) -> TrackPage:
    try:
        payload = collection_page(
            kind,
            collection_id,
            offset=offset,
            limit=limit,
            sort_field=sort_field,
            sort_direction=sort_direction,
            query=q,
            artists=artist,
            keys=key,
            ratings=rating,
            tags=tag,
            bpm_min=bpm_min,
            bpm_max=bpm_max,
            collection_types=collection_type,
        )
    except CollectionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TrackPage.model_validate(payload)


@router.get("/collections/{kind}/{collection_id}/virtualdj-metadata")
def virtualdj_metadata(kind: str, collection_id: str) -> Response:
    """Download TuneOps metadata for the local VirtualDJ companion.

    The export deliberately contains provider IDs rather than fuzzy identity
    fields. VirtualDJ's TIDAL extension stores those IDs as ``td<id>`` in its
    database, so the companion never has to guess based on title or artist.
    """
    try:
        page = collection_page(kind, collection_id, offset=0, limit=1_000_000)
    except CollectionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    track_ids = [str(row.get("id") or "") for row in page["items"]]
    free_tags = tidal_tags_for_tracks(track_ids)
    tracks: list[dict[str, object]] = []
    for row in page["items"]:
        track_id = str(row.get("id") or "")
        dimensions = {
            str(dimension): [str(value) for value in values]
            for dimension, values in (row.get("dimensions") or {}).items()
            if values
        }
        values = dimensions.get("rating") or []
        try:
            rating = int(values[0])
        except (IndexError, TypeError, ValueError):
            rating = None
        if rating is not None and not 1 <= rating <= 5:
            rating = None
        tracks.append({
            "tidal_track_id": track_id,
            "rating": rating,
            "title": str(row.get("title") or ""),
            "artist": str(row.get("artist") or ""),
            "album": str(row.get("album") or ""),
            "year": str(row.get("year") or ""),
            "dimensions": dimensions,
            "tags": free_tags.get(track_id, []),
        })
    collection = page["collection"]
    payload = {
        "schema_version": 2,
        "type": "tuneops.virtualdj-metadata",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection": {
            "type": collection["type"],
            "id": collection["id"],
            "name": collection["name"],
        },
        "tracks": tracks,
    }
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", collection["name"]).strip("-.") or "collection"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-virtualdj-metadata.json"'},
    )


@router.get("/dimensions")
def dimensions() -> dict[str, object]:
    return {
        "values": DIMENSION_VALUES,
        "labels": DIMENSION_LABELS,
        "max_values": DIMENSION_MAX_VALUES,
    }


@router.put("/tracks/dimensions", response_model=DimensionUpdateResponse)
def update_dimensions(body: DimensionUpdate) -> DimensionUpdateResponse:
    if body.dimension not in DIMENSION_VALUES:
        raise HTTPException(status_code=422, detail="Unknown dimension")
    allowed = set(DIMENSION_VALUES[body.dimension])
    if any(value not in allowed for value in body.values):
        raise HTTPException(status_code=422, detail="Invalid dimension value")
    maximum = DIMENSION_MAX_VALUES.get(body.dimension)
    if maximum and len(dict.fromkeys(body.values)) > maximum:
        raise HTTPException(status_code=422, detail=f"This dimension allows at most {maximum} value(s)")
    stored = replace_tidal_tracks_dimension(
        body.track_ids, body.dimension, body.values,
    )
    return DimensionUpdateResponse(updated=stored)


@router.post("/tracks/dimensions/toggle", response_model=DimensionUpdateResponse)
def toggle_dimensions(body: DimensionToggle) -> DimensionUpdateResponse:
    if body.dimension not in DIMENSION_VALUES or body.value not in DIMENSION_VALUES[body.dimension]:
        raise HTTPException(status_code=422, detail="Invalid dimension value")
    stored = set_tidal_tracks_dimension_value(
        body.track_ids, body.dimension, body.value, body.enable,
    )
    return DimensionUpdateResponse(updated=stored)


@router.get("/playlist-options")
def playlist_options() -> list[dict[str, str]]:
    return [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "collection_type": str(item.get("collection_type") or "playlist"),
        }
        for item in tidal_indexed_playlists()
    ]


@router.post("/tracks/playlist-action", response_model=PlaylistActionResponse)
def playlist_action(body: PlaylistAction) -> PlaylistActionResponse:
    try:
        result = mutate_playlist_tracks(
            body.action,
            body.track_ids,
            body.playlist_id,
            body.source_playlist_id,
        )
    except TrackActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PlaylistActionResponse.model_validate(result)


@router.post("/tracks/like", response_model=LikeTracksResponse)
def like_tracks(body: LikeTracksRequest) -> LikeTracksResponse:
    try:
        result = like_tidal_tracks(body.track_ids)
    except TrackActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LikeTracksResponse.model_validate(result)


@router.post("/tracks/associate-watched-mix")
def associate_watched_mix(body: WatchedMixAssociation) -> dict[str, object]:
    if not watched_mix(body.video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    track_ids = list(dict.fromkeys(body.track_ids))
    added = associate_tidal_tracks_with_watched_mix(body.video_id, track_ids)
    return {"added": added, "selected": len(track_ids)}


@router.get("/watched-mixes")
def watched_mix_list() -> list[dict[str, object]]:
    return [
        {**item, "cover_url": f"/api/v1/watched-mixes/{quote(str(item.get('video_id') or ''), safe='')}/cover"}
        for item in watched_mixes()
    ]


@router.post("/watched-mixes", status_code=201)
def create_watched_mix(body: WatchedMixCreate) -> dict[str, object]:
    video_id = youtube_video_id(body.youtube_url)
    if not video_id:
        raise HTTPException(status_code=422, detail="Enter a valid YouTube video URL")
    metadata = fetch_youtube_metadata(body.youtube_url)
    saved = save_watched_mix(
        video_id,
        body.youtube_url,
        title=metadata.title,
        channel_name=metadata.channel_name,
        upload_date=metadata.upload_date,
    )
    _cache_watched_mix_cover(video_id)
    invalidate_navigation_snapshot()
    return {**saved, "cover_url": f"/api/v1/watched-mixes/{quote(video_id, safe='')}/cover"}


@router.get("/watched-mixes/{video_id}")
def watched_mix_detail(video_id: str) -> dict[str, object]:
    record = watched_mix(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    # The YouTube ID is the durable identity for a watched mix. Build the
    # canonical URL from it so old/short/tracking-heavy stored URLs cannot stop
    # live metadata or thumbnail loading.
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    metadata = fetch_youtube_metadata(canonical_url)
    return {
        **record,
        "youtube_url": canonical_url,
        "thumbnail_url": f"/api/v1/watched-mixes/{quote(video_id, safe='')}/cover",
        "cover_url": f"/api/v1/watched-mixes/{quote(video_id, safe='')}/cover",
        "live_title": metadata.title,
        "live_channel_name": metadata.channel_name,
        "live_view_count": metadata.view_count,
        "live_upload_date": metadata.upload_date,
        "live_metadata_error": metadata.error,
    }


@router.get("/watched-mixes/{video_id}/cover", response_class=FileResponse)
def watched_mix_cover(video_id: str) -> FileResponse:
    if not watched_mix(video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    path = _cache_watched_mix_cover(video_id)
    if path is None:
        raise HTTPException(status_code=404, detail="YouTube cover is unavailable")
    return FileResponse(path, media_type="image/jpeg", headers=_local_file_cache_headers(path))


@router.patch("/watched-mixes/{video_id}")
def update_watched_mix(video_id: str, body: WatchedMixUpdate) -> dict[str, object]:
    record = watched_mix(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    saved = save_watched_mix(
        video_id,
        str(record["youtube_url"]),
        title=body.title,
        channel_name=body.channel_name,
        upload_date=body.upload_date,
    )
    invalidate_navigation_snapshot()
    return saved


@router.put("/watched-mixes/{video_id}/rating")
def update_watched_mix_rating(
    video_id: str, body: WatchedMixRatingUpdate
) -> dict[str, object]:
    try:
        return set_watched_mix_rating(video_id, body.rating)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/watched-mixes/{video_id}", status_code=204)
def remove_watched_mix(video_id: str) -> None:
    if not delete_watched_mix(video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    try:
        _watched_mix_cover_path(video_id).unlink(missing_ok=True)
    except OSError:
        engine.LOGGER.warning("watched_mix.cover_delete_failed video_id=%s", video_id, exc_info=True)
    invalidate_navigation_snapshot()


@router.post("/watched-mixes/{video_id}/tracklist/parse")
def parse_watched_mix_tracklist(video_id: str, body: TracklistParseRequest) -> dict[str, object]:
    if not watched_mix(video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    rows = parse_tracklist(body.text, body.order)
    searchable = sum(row.get("status") not in {"invalid", "unresolved"} for row in rows)
    return {"rows": rows, "searchable": searchable}


@router.post("/watched-mixes/{video_id}/tracklist/like")
def like_watched_mix_track(video_id: str, body: TracklistLikeRequest) -> dict[str, object]:
    if not watched_mix(video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    candidate = dict(body.candidate)
    track_id = str(candidate.get("id") or "").strip()
    if not track_id:
        raise HTTPException(status_code=422, detail="Choose a valid TIDAL candidate")
    try:
        session = engine.tidal_client(interactive=False)
        engine._call(
            "tidal",
            "favorite_track_from_watched_mix",
            lambda: session.user.favorites.add_track(track_id),
            track_id=track_id,
            watched_mix=video_id,
        )
        cached = add_tidal_liked_track(str(session.user.id), candidate)
        associated = associate_tidal_tracks_with_watched_mix(video_id, [track_id])
    except Exception as exc:
        engine.LOGGER.exception("api.watched_mix like_failed track_id=%s", track_id)
        raise HTTPException(status_code=409, detail="TIDAL could not like the selected track") from exc
    return {"track_id": track_id, "cached": cached, "associated": bool(associated)}


@router.post("/watched-mixes/{video_id}/tracklist/watch")
def watch_watched_mix_track(video_id: str, body: TracklistWatchRequest) -> dict[str, object]:
    if not watched_mix(video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    pending, added = add_pending_track(
        video_id,
        body.artist,
        body.title,
        mix_position=body.timestamp,
        raw_line=body.raw_line,
    )
    return {"pending": pending, "added": added}


@router.get("/pending-tracks")
def pending_track_list() -> list[dict[str, object]]:
    return pending_tracks()


@router.post("/pending-tracks/{pending_id}/like")
def like_pending_track(pending_id: int, body: PendingLikeRequest) -> dict[str, object]:
    record = pending_track(pending_id)
    if not record:
        raise HTTPException(status_code=404, detail="Pending track was not found")
    candidate = next(
        (item for item in record.get("candidates", []) if str(item.get("id") or "") == body.track_id),
        None,
    )
    if not candidate:
        raise HTTPException(status_code=422, detail="Choose a valid cached TIDAL candidate")
    try:
        session = engine.tidal_client(interactive=False)
        engine._call(
            "tidal",
            "favorite_pending_track",
            lambda: session.user.favorites.add_track(body.track_id),
            track_id=body.track_id,
            watched_mix=record.get("video_id", ""),
        )
        add_tidal_liked_track(str(session.user.id), candidate)
        associate_tidal_tracks_with_watched_mix(str(record["video_id"]), [body.track_id])
        resolve_pending_track(pending_id)
    except Exception as exc:
        engine.LOGGER.exception("api.pending_track like_failed pending_id=%s", pending_id)
        raise HTTPException(status_code=409, detail="TIDAL could not like the pending track") from exc
    return {"resolved": pending_id, "track_id": body.track_id}


@router.delete("/pending-tracks/{pending_id}", status_code=204)
def remove_pending_track(pending_id: int) -> None:
    if not pending_track(pending_id):
        raise HTTPException(status_code=404, detail="Pending track was not found")
    delete_pending_track(pending_id)


@router.get("/mixes")
def mixes() -> list[dict[str, object]]:
    video_metadata = youtube_video_metadata()
    return [
        {
            "folder_name": mix.folder_name,
            "youtube_url": mix.youtube_url,
            "youtube_analytics_url": (
                f"https://studio.youtube.com/video/{youtube_video_id(mix.youtube_url)}/analytics/tab-overview/period-default"
                if youtube_video_id(mix.youtube_url) else ""
            ),
            "tidal_url": mix.tidal_url,
            "tidal_playlist_id": mix.tidal_playlist_id,
            "tidal_playlist_name": mix.tidal_playlist_name,
            "track_count": mix.track_count,
            "updated_at": mix.updated_at,
            "youtube_title": str(video_metadata.get(youtube_video_id(mix.youtube_url) or "", {}).get("title") or ""),
            "youtube_upload_date": str(video_metadata.get(youtube_video_id(mix.youtube_url) or "", {}).get("upload_date") or ""),
            "youtube_duration_seconds": (
                youtube_service.cached_video_duration_seconds(youtube_video_id(mix.youtube_url))
            ),
            "youtube_views": getattr(mix, "youtube_views", None),
            "youtube_thumbnail_impressions": getattr(mix, "youtube_thumbnail_impressions", None),
            "youtube_thumbnail_ctr": getattr(mix, "youtube_thumbnail_ctr", None),
            "youtube_watch_minutes": getattr(mix, "youtube_watch_minutes", None),
            "youtube_average_view_duration": getattr(mix, "youtube_average_view_duration", None),
            "youtube_average_view_percentage": getattr(mix, "youtube_average_view_percentage", None),
            "youtube_likes": getattr(mix, "youtube_likes", None),
            "youtube_comments": getattr(mix, "youtube_comments", None),
            "youtube_subscribers_gained": getattr(mix, "youtube_subscribers_gained", None),
            "youtube_analytics_fetched_at": getattr(mix, "youtube_analytics_fetched_at", ""),
            "cover_url": youtube_thumbnail_url(mix.youtube_url),
        }
        for mix in discover_mixes()
    ]


@router.get("/mixes/{folder_name}")
def mix_detail(folder_name: str) -> dict[str, object]:
    mix = mix_for(folder_name)
    if mix is None:
        raise HTTPException(status_code=404, detail="Mix was not found")
    metadata = fetch_youtube_metadata(mix.youtube_url) if mix.youtube_url else None
    video_id = youtube_video_id(mix.youtube_url)
    return {
        "folder_name": mix.folder_name,
        "youtube_url": mix.youtube_url,
        "youtube_analytics_url": (
            f"https://studio.youtube.com/video/{youtube_video_id(mix.youtube_url)}/analytics/tab-overview/period-default"
            if youtube_video_id(mix.youtube_url) else ""
        ),
        "tidal_url": mix.tidal_url,
        "tidal_playlist_name": mix.tidal_playlist_name,
        "cover_url": youtube_thumbnail_url(mix.youtube_url),
        "youtube_title": metadata.title if metadata else "",
        "youtube_channel": metadata.channel_name if metadata else "",
        "youtube_views": (
            mix.youtube_views
            if mix.youtube_views is not None
            else metadata.view_count if metadata and metadata.view_count is not None else None
        ),
        "youtube_upload_date": metadata.upload_date if metadata else "",
        "youtube_metadata_error": metadata.error if metadata else "",
        "youtube_duration_seconds": (
            youtube_service.cached_video_duration_seconds(video_id)
        ),
        "youtube_thumbnail_impressions": mix.youtube_thumbnail_impressions,
        "youtube_thumbnail_ctr": mix.youtube_thumbnail_ctr,
        "youtube_watch_minutes": mix.youtube_watch_minutes,
        "youtube_average_view_duration": mix.youtube_average_view_duration,
        "youtube_average_view_percentage": mix.youtube_average_view_percentage,
        "youtube_likes": mix.youtube_likes,
        "youtube_comments": mix.youtube_comments,
        "youtube_subscribers_gained": mix.youtube_subscribers_gained,
        "youtube_analytics_fetched_at": mix.youtube_analytics_fetched_at,
    }


@router.put("/mixes/{folder_name}/urls")
def save_mix_urls(folder_name: str, body: MixUrlsUpdate) -> dict[str, object]:
    if mix_for(folder_name) is None:
        raise HTTPException(status_code=404, detail="Mix was not found")
    if body.youtube_url.strip() and not youtube_video_id(body.youtube_url):
        raise HTTPException(status_code=422, detail="Enter a valid YouTube video URL")
    save_setlist_urls(folder_name, body.youtube_url, body.tidal_url)
    invalidate_navigation_snapshot()
    return mix_detail(folder_name)
