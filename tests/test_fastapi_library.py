from __future__ import annotations

import json
from types import SimpleNamespace

from backend.app.services import library
from backend.app.api import library as library_api
from backend.app.schemas import EventMediaUpdate
from backend.app.schemas import MixUrlsUpdate, WatchedMixRatingUpdate, WatchedMixUpdate


def _row(track_id: str, title: str, timestamp: float | None, bpm: str = ""):
    return {
        "id": track_id,
        "title": title,
        "artist": "Artist",
        "artists": [],
        "remix": "",
        "album": "",
        "bpm": bpm,
        "key": "",
        "year": "",
        "_date_added_sort": timestamp,
        "dimensions": {},
    }


def test_collection_sort_is_global_and_keeps_missing_dates_last(monkeypatch):
    rows = [
        _row("old", "Old", 10),
        _row("missing", "Missing", None),
        _row("new", "New", 30),
        _row("middle", "Middle", 20),
    ]
    monkeypatch.setattr(library, "descriptor", lambda *_: {"type": "liked", "id": "liked", "name": "Liked", "collection_type": ""})
    monkeypatch.setattr(library, "_base_rows", lambda *_: rows)
    monkeypatch.setattr(library, "_attach_related", lambda *_: None)

    page = library.collection_page("liked", "liked", offset=0, limit=2, sort_field="date_added", sort_direction="desc")

    assert page["total"] == 4
    assert [item["id"] for item in page["items"]] == ["new", "middle"]
    assert page["has_more"] is True
    second = library.collection_page("liked", "liked", offset=2, limit=2, sort_field="date_added", sort_direction="desc")
    assert [item["id"] for item in second["items"]] == ["old", "missing"]


def test_collection_filters_before_pagination(monkeypatch):
    rows = [_row(str(index), f"Track {index}", float(index), bpm=str(100 + index)) for index in range(20)]
    monkeypatch.setattr(library, "descriptor", lambda *_: {"type": "search", "id": "library", "name": "Search", "collection_type": ""})
    monkeypatch.setattr(library, "_base_rows", lambda *_: rows)
    monkeypatch.setattr(library, "_attach_related", lambda *_: None)

    page = library.collection_page("search", "library", offset=0, limit=3, query="track 1", bpm_min=110)

    assert page["total"] == 10
    assert [item["id"] for item in page["items"]] == ["10", "11", "12"]


def test_virtualdj_export_contains_all_track_dimensions_and_free_tags(monkeypatch):
    monkeypatch.setattr(library_api, "collection_page", lambda *_args, **_kwargs: {
        "collection": {"type": "playlist", "id": "playlist-id", "name": "My Playlist"},
        "items": [
            {"id": "12", "title": "Rated", "artist": "Artist", "album": "Album", "year": "2024", "dimensions": {"rating": ["5"], "energy": ["4"], "vibe": ["Dark", "Hypnotic"]}},
            {"id": "34", "title": "Unrated", "artist": "Artist", "dimensions": {}},
        ],
    })
    monkeypatch.setattr(library_api, "tidal_tags_for_tracks", lambda _ids: {
        "12": ["Warehouse"], "34": ["Needs review"],
    })

    response = library_api.virtualdj_metadata("playlist", "playlist-id")
    payload = json.loads(response.body)

    assert payload["schema_version"] == 2
    assert payload["type"] == "tuneops.virtualdj-metadata"
    assert payload["tracks"] == [
        {
            "tidal_track_id": "12", "rating": 5, "title": "Rated",
            "artist": "Artist", "album": "Album", "year": "2024",
            "dimensions": {"rating": ["5"], "energy": ["4"], "vibe": ["Dark", "Hypnotic"]},
            "tags": ["Warehouse"],
        },
        {
            "tidal_track_id": "34", "rating": None, "title": "Unrated",
            "artist": "Artist", "album": "", "year": "", "dimensions": {},
            "tags": ["Needs review"],
        },
    ]
    assert response.headers["content-disposition"] == 'attachment; filename="My-Playlist-virtualdj-metadata.json"'


def test_numeric_sort_keeps_missing_play_counts_last_in_both_directions():
    rows = [
        {**_row("missing", "Missing", None), "play_count": None},
        {**_row("low", "Low", None), "play_count": 2},
        {**_row("high", "High", None), "play_count": 20},
    ]

    assert [row["id"] for row in library._sort(rows, "play_count", "asc")] == ["low", "high", "missing"]
    assert [row["id"] for row in library._sort(rows, "play_count", "desc")] == ["high", "low", "missing"]


def test_global_collection_type_filter_uses_indexed_memberships_not_liked_state():
    row = {
        **_row("track", "Track", 1),
        "playlists": [{"id": "playlist", "name": "Playlist"}],
        "events": [],
        "sources": [],
        "mixes": [{"id": "mix", "name": "My mix"}],
        "djmi": [],
        "liked": True,
    }
    base_filters = {"query": "", "artists": [], "keys": [], "ratings": [], "tags": [], "bpm_min": None, "bpm_max": None}

    assert library._matches(row, {**base_filters, "collection_types": ["playlist"]})
    assert library._matches(row, {**base_filters, "collection_types": ["mix"]})
    assert not library._matches(row, {**base_filters, "collection_types": ["event"]})


def test_collection_length_sort_uses_duration_not_display_text(monkeypatch):
    rows = [
        {**_row("nine", "Nine", 1), "length": "9:59"},
        {**_row("ten", "Ten", 2), "length": "10:00"},
        {**_row("short", "Short", 3), "length": "3:04"},
    ]
    monkeypatch.setattr(library, "descriptor", lambda *_: {"type": "liked", "id": "liked", "name": "Liked", "collection_type": ""})
    monkeypatch.setattr(library, "_base_rows", lambda *_: rows)
    monkeypatch.setattr(library, "_attach_related", lambda *_: None)

    page = library.collection_page("liked", "liked", offset=0, limit=10, sort_field="length", sort_direction="asc")

    assert [item["id"] for item in page["items"]] == ["short", "nine", "ten"]


def test_history_collection_preserves_monthly_instead_of_all_time_play_count(monkeypatch):
    row = _row("track", "Track", None)
    row.update(play_count=7, last_played=1_790_000_000)
    monkeypatch.setattr(library, "tidal_playlists_for_tracks", lambda *_: {})
    monkeypatch.setattr(library, "tidal_setlists_for_tracks", lambda *_: {})
    monkeypatch.setattr(library, "tidal_watched_mixes_for_tracks", lambda *_: {})
    monkeypatch.setattr(library, "tidal_artists_for_tracks", lambda *_: {})
    monkeypatch.setattr(library, "tidal_dimensions_for_tracks", lambda *_: {})
    monkeypatch.setattr(library, "lastfm_track_stats", lambda *_: {"track": {"play_count": 999, "last_played": 1_800_000_000}})
    monkeypatch.setattr(library.engine, "load_runtime_settings", lambda: {"lastfm_username": "user"})

    library._attach_related([row], {"type": "history", "id": "2026-09", "name": "September 2026"})

    assert row["play_count"] == 7
    assert row["last_played"] != ""


def test_navigation_builds_history_from_configured_lastfm_cache(monkeypatch):
    monkeypatch.setattr(library_api.engine, "load_runtime_settings", lambda: {"lastfm_username": "Aruzhu", "history_top_tracks": 20})
    monkeypatch.setattr(library_api, "tidal_indexed_playlists", lambda: [])
    monkeypatch.setattr(library_api, "discover_mixes", lambda: [])
    monkeypatch.setattr(library_api, "watched_mixes", lambda: [])
    monkeypatch.setattr(library_api, "lastfm_history_navigation", lambda username, limit: {
        "years": [{"year": "2026", "track_count": 40, "play_count": 120}],
        "months": [
            {"year": "2026", "month": "09", "track_count": 25, "play_count": 80},
        ],
    })

    result = library_api.navigation()

    history = next(group for group in result.groups if group.id == "history")
    assert history.items[0].label == "Overall"
    assert history.items[0].path == "/history/overall"
    assert history.items[1].label == "2026"
    assert history.items[1].children[0]["path"] == "/history/2026-overall"
    assert history.items[1].children[1]["path"] == "/history/2026-09"
    assert next(item for item in result.tools if item.id == "artists").path == "/artists"


def test_artist_overview_uses_configured_lastfm_user(monkeypatch):
    captured = {}
    monkeypatch.setattr(library_api.engine, "load_runtime_settings", lambda: {"lastfm_username": "Aruzhu"})
    monkeypatch.setattr(
        library_api,
        "tidal_artist_overview_page",
        lambda username, **kwargs: captured.update(username=username, **kwargs) or ([{
            "id": "artist", "name": "Artist", "indexed_tracks": 4, "lastfm_plays": 12,
        }], 1),
    )

    result = library_api.artist_overview(
        offset=0, limit=200, q="art",
        sort_field="lastfm_plays", sort_direction="desc",
    )

    assert result.total == 1
    assert result.items[0].lastfm_plays == 12
    assert captured["username"] == "Aruzhu"
    assert captured["query"] == "art"


def test_navigation_puts_overview_first_in_my_mixes(monkeypatch):
    monkeypatch.setattr(library_api.engine, "load_runtime_settings", lambda: {})
    monkeypatch.setattr(library_api, "tidal_indexed_playlists", lambda: [])
    monkeypatch.setattr(
        library_api, "lastfm_history_navigation",
        lambda *_: {"years": [], "months": []},
    )
    monkeypatch.setattr(library_api, "watched_mixes", lambda: [])
    monkeypatch.setattr(
        library_api,
        "discover_mixes",
        lambda: [SimpleNamespace(folder_name="darkprog")],
    )

    result = library_api.navigation()

    my_mixes = next(group for group in result.groups if group.id == "my-mixes")
    assert [(item.label, item.path) for item in my_mixes.items] == [
        ("Overview", "/mixes"),
        ("darkprog", "/mixes/darkprog"),
    ]


def test_history_overall_uses_the_configured_yearly_top_tracks(monkeypatch):
    monkeypatch.setattr(library.engine, "load_runtime_settings", lambda: {"lastfm_username": "Aruzhu", "history_top_tracks": 20})
    monkeypatch.setattr(library, "lastfm_year_top_tracks", lambda username, year, limit: [{
        "id": "top", "title": "Top track", "artist": "Artist", "play_count": 12, "last_played": 1_790_000_000,
    }])

    rows = library._base_rows("history", "2026-overall")

    assert rows[0]["id"] == "top"
    assert rows[0]["play_count"] == 12


def test_history_root_overall_uses_all_cached_scrobbles(monkeypatch):
    monkeypatch.setattr(library.engine, "load_runtime_settings", lambda: {"lastfm_username": "Aruzhu", "history_top_tracks": 20})
    monkeypatch.setattr(library, "lastfm_all_time_top_tracks", lambda username, limit: [{
        "id": "forever", "title": "All-time track", "artist": "Artist", "play_count": 88, "last_played": 1_790_000_000,
    }])

    rows = library._base_rows("history", "overall")

    assert rows[0]["id"] == "forever"
    assert rows[0]["play_count"] == 88


def test_event_media_reads_stored_links_without_fetching_concert_archives(monkeypatch):
    monkeypatch.setattr(
        library_api,
        "descriptor",
        lambda *_: {"type": "event", "id": "event-id", "name": "ARTBAT Oslo", "collection_type": "event"},
    )
    monkeypatch.setattr(
        library_api,
        "event_links",
        lambda *_: {
            "youtube_url": "https://youtube.com/watch?v=abc",
            "concert_archives_url": "https://concertarchives.org/example",
            "updated_at": "2026-09-24T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(library_api, "youtube_thumbnail_url", lambda url: f"thumb:{url}")

    result = library_api.event_media("event-id")

    assert result["event_name"] == "ARTBAT Oslo"
    assert result["thumbnail_url"] == "thumb:https://youtube.com/watch?v=abc"
    assert result["concert_archives_url"] == "https://concertarchives.org/example"


def test_event_media_save_validates_and_persists_only_user_links(monkeypatch):
    saved: dict[str, str] = {}
    monkeypatch.setattr(
        library_api,
        "descriptor",
        lambda *_: {"type": "event", "id": "event-id", "name": "ARTBAT Oslo", "collection_type": "event"},
    )
    monkeypatch.setattr(
        library_api,
        "save_event_links",
        lambda playlist_id, youtube, concert: saved.update(id=playlist_id, youtube=youtube, concert=concert),
    )
    monkeypatch.setattr(
        library_api,
        "event_links",
        lambda *_: {"youtube_url": saved["youtube"], "concert_archives_url": saved["concert"], "updated_at": "now"},
    )
    monkeypatch.setattr(library_api, "youtube_video_id", lambda _url: "abc")
    monkeypatch.setattr(library_api, "youtube_thumbnail_url", lambda _url: "thumb")

    result = library_api.save_event_media(
        "event-id",
        EventMediaUpdate(youtube_url="https://youtube.com/watch?v=abc", concert_archives_url="https://concertarchives.org/example"),
    )

    assert saved == {
        "id": "event-id",
        "youtube": "https://youtube.com/watch?v=abc",
        "concert": "https://concertarchives.org/example",
    }
    assert result["thumbnail_url"] == "thumb"


def test_mix_url_editor_reuses_existing_setlist_storage(monkeypatch):
    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(library_api, "mix_for", lambda _name: object())
    monkeypatch.setattr(library_api, "youtube_video_id", lambda _url: "video-id")
    monkeypatch.setattr(library_api, "save_setlist_youtube_url", lambda name, url: saved.append(("youtube", name, url)))
    monkeypatch.setattr(library_api, "save_setlist_tidal_url", lambda name, url: saved.append(("tidal", name, url)))
    monkeypatch.setattr(library_api, "mix_detail", lambda name: {"folder_name": name})

    result = library_api.save_mix_urls("darkprog", MixUrlsUpdate(youtube_url="https://youtu.be/abc123", tidal_url="https://tidal.com/playlist/abc"))

    assert saved == [("youtube", "darkprog", "https://youtu.be/abc123"), ("tidal", "darkprog", "https://tidal.com/playlist/abc")]
    assert result == {"folder_name": "darkprog"}


def test_mix_overview_exposes_cached_counts_and_local_availability(monkeypatch):
    monkeypatch.setattr(
        library_api,
        "discover_mixes",
        lambda: [SimpleNamespace(
            folder_name="darkprog",
            youtube_url="https://youtu.be/abc123",
            tidal_url="https://tidal.com/playlist/id",
            tidal_playlist_id="id",
            tidal_playlist_name="DJ Set Darkprog",
            track_count=12,
            updated_at="2026-10-02T12:30:00",
            positions="[00:00] Intro\n[58:30] Last track",
            audio_path=object(),
            cover_path=None,
        )],
    )
    monkeypatch.setattr(library_api, "youtube_thumbnail_url", lambda _url: "thumbnail")
    monkeypatch.setattr(library_api, "youtube_video_metadata", lambda: {
        "abc123": {"title": "Dark Progressive Mix", "upload_date": "2026-01-05"},
    })

    result = library_api.mixes()

    assert result[0] == {
        "folder_name": "darkprog",
        "youtube_url": "https://youtu.be/abc123",
        "youtube_analytics_url": "https://studio.youtube.com/video/abc123/analytics/tab-overview/period-default",
        "tidal_url": "https://tidal.com/playlist/id",
        "tidal_playlist_id": "id",
        "tidal_playlist_name": "DJ Set Darkprog",
        "track_count": 12,
        "updated_at": "2026-10-02T12:30:00",
        "youtube_title": "Dark Progressive Mix",
        "youtube_upload_date": "2026-01-05",
        "youtube_duration_seconds": 3510,
        "youtube_views": None,
        "youtube_thumbnail_impressions": None,
        "youtube_thumbnail_ctr": None,
        "youtube_watch_minutes": None,
        "youtube_average_view_duration": None,
        "youtube_average_view_percentage": None,
        "youtube_likes": None,
        "youtube_comments": None,
        "youtube_subscribers_gained": None,
        "youtube_analytics_fetched_at": "",
        "has_cover": False,
        "cover_url": "thumbnail",
    }


def test_mix_detail_exposes_cached_owner_analytics(monkeypatch):
    monkeypatch.setattr(
        library_api,
        "mix_for",
        lambda _name: SimpleNamespace(
            folder_name="darkprog", youtube_url="https://youtu.be/abc123",
            tidal_url="", tidal_playlist_name="", cover_path=None,
            positions="[00:00] Intro\n[59:00] Last",
            youtube_views=123, youtube_thumbnail_impressions=1000,
            youtube_thumbnail_ctr=4.25, youtube_watch_minutes=600,
            youtube_average_view_duration=240,
            youtube_average_view_percentage=42.5, youtube_likes=8,
            youtube_comments=2, youtube_subscribers_gained=3,
            youtube_analytics_fetched_at="2026-10-13T12:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        library_api,
        "fetch_youtube_metadata",
        lambda _url: SimpleNamespace(
            title="Dark Progressive", channel_name="Sonic165",
            view_count=120, upload_date="2026-01-05", error="",
        ),
    )
    monkeypatch.setattr(library_api, "youtube_thumbnail_url", lambda _url: "thumbnail")
    monkeypatch.setattr(library_api.youtube_service, "cached_video_duration_seconds", lambda _id: 3600)

    result = library_api.mix_detail("darkprog")

    assert result["youtube_views"] == 123
    assert result["youtube_duration_seconds"] == 3600
    assert result["youtube_average_view_percentage"] == 42.5
    assert result["youtube_thumbnail_ctr"] == 4.25
    assert result["youtube_analytics_fetched_at"] == "2026-10-13T12:00:00+00:00"


def test_watched_mix_edit_reuses_existing_record_and_delete_is_explicit(monkeypatch):
    record = {
        "video_id": "video-id",
        "youtube_url": "https://youtube.com/watch?v=video-id",
        "title": "Old title",
        "channel_name": "Old channel",
        "upload_date": "2020-01-01",
    }
    saved: dict[str, str] = {}
    monkeypatch.setattr(library_api, "watched_mix", lambda _id: record)
    monkeypatch.setattr(
        library_api,
        "save_watched_mix",
        lambda video_id, youtube_url, title, channel_name, upload_date: saved.update(
            video_id=video_id, youtube_url=youtube_url, title=title, channel_name=channel_name, upload_date=upload_date
        ) or saved,
    )
    monkeypatch.setattr(library_api, "delete_watched_mix", lambda _id: True)

    updated = library_api.update_watched_mix(
        "video-id", WatchedMixUpdate(title="New title", channel_name="New channel", upload_date="2026-09-25")
    )
    library_api.remove_watched_mix("video-id")

    assert updated["title"] == "New title"
    assert saved == {
        "video_id": "video-id",
        "youtube_url": "https://youtube.com/watch?v=video-id",
        "title": "New title",
        "channel_name": "New channel",
        "upload_date": "2026-09-25",
    }


def test_watched_mix_rating_updates_the_saved_mix(monkeypatch):
    monkeypatch.setattr(
        library_api,
        "set_watched_mix_rating",
        lambda video_id, rating: {"video_id": video_id, "rating": rating},
    )

    result = library_api.update_watched_mix_rating(
        "video-id", WatchedMixRatingUpdate(rating=5)
    )

    assert result == {"video_id": "video-id", "rating": 5}


def test_watched_mix_list_allows_numeric_ratings(monkeypatch):
    monkeypatch.setattr(
        library_api,
        "watched_mixes",
        lambda: [{"video_id": "video-id", "title": "Mix", "rating": 4}],
    )

    result = library_api.watched_mix_list()

    assert result[0]["rating"] == 4


def test_watched_mix_detail_uses_video_id_for_live_youtube_media(monkeypatch):
    fetched: list[str] = []
    monkeypatch.setattr(
        library_api,
        "watched_mix",
        lambda _id: {
            "video_id": "abc123",
            "youtube_url": "https://youtu.be/abc123?si=old-tracking-value",
            "title": "",
            "channel_name": "",
            "upload_date": "",
        },
    )
    monkeypatch.setattr(
        library_api,
        "fetch_youtube_metadata",
        lambda url: fetched.append(url) or SimpleNamespace(
            title="Live title",
            channel_name="Live channel",
            view_count=42,
            upload_date="2026-01-05",
            error="",
        ),
    )
    result = library_api.watched_mix_detail("abc123")

    canonical = "https://www.youtube.com/watch?v=abc123"
    assert fetched == [canonical]
    assert result["youtube_url"] == canonical
    assert result["thumbnail_url"] == "/api/v1/watched-mixes/abc123/cover"
    assert result["live_title"] == "Live title"
    assert result["live_channel_name"] == "Live channel"
    assert result["live_view_count"] == 42
