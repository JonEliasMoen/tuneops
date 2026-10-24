"""Bounded, read-only SQL queries for the shared track browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .connection import execute_batch
from .database import DATABASE_PATH, connect_readonly, initialize


DIMENSION_SORT_FIELDS = {
    "rating", "energy", "tension", "vibe", "movement", "driver",
    "function", "structure", "texture", "scale",
}
TEXT_SORT_FIELDS = {"title", "artist", "remix", "album"}
MEMBERSHIP_SORT_FIELDS = {
    "playlists": "playlist",
    "events": "event",
    "sources": "source",
    "mixes": "mix",
    "djmi": "watched_mix",
}


def _membership(kind: str, collection_id: str) -> tuple[str, list[Any]]:
    if kind == "liked":
        return """
            SELECT lt.provider_track_id AS track_id, lt.date_added,
                   '' AS mix_position, lt.position AS source_order
            FROM liked_tracks lt
            WHERE lt.provider='tidal' AND lt.provider_user_id=(
                SELECT provider_user_id FROM liked_track_snapshots
                WHERE provider='tidal' ORDER BY cached_at DESC LIMIT 1
            )
        """, []
    if kind in {"playlist", "event", "source"}:
        return """
            SELECT pt.provider_track_id AS track_id, pt.date_added,
                   '' AS mix_position, pt.position AS source_order
            FROM playlist_tracks pt
            WHERE pt.provider='tidal' AND pt.provider_playlist_id=?
        """, [str(collection_id)]
    if kind == "setlist":
        return """
            SELECT st.provider_track_id AS track_id, st.date_added,
                   st.mix_position, st.position AS source_order
            FROM setlist_tracks st
            WHERE st.provider='tidal' AND st.folder_name=?
        """, [str(collection_id)]
    if kind == "watched_mix":
        return """
            SELECT wmt.provider_track_id AS track_id, wmt.associated_at AS date_added,
                   '' AS mix_position, wmt.position AS source_order
            FROM watched_mix_tracks wmt
            WHERE wmt.provider='tidal' AND wmt.video_id=?
        """, [str(collection_id)]
    if kind in {"search", "artist"}:
        artist_join = "" if kind == "search" else """
            JOIN track_artists selected_artist
              ON selected_artist.provider=members.provider
             AND selected_artist.provider_track_id=members.provider_track_id
             AND selected_artist.artist_key=?
        """
        params = [] if kind == "search" else [str(collection_id)]
        return f"""
            WITH all_memberships AS (
                SELECT provider, provider_track_id, date_added
                FROM liked_tracks WHERE provider='tidal'
                UNION ALL
                SELECT provider, provider_track_id, date_added
                FROM playlist_tracks WHERE provider='tidal'
                UNION ALL
                SELECT provider, provider_track_id, date_added
                FROM setlist_tracks WHERE provider='tidal'
            ), members AS (
                SELECT provider, provider_track_id, MAX(date_added) AS date_added
                FROM all_memberships GROUP BY provider, provider_track_id
            )
            SELECT members.provider_track_id AS track_id, members.date_added,
                   '' AS mix_position,
                   ROW_NUMBER() OVER (
                       ORDER BY track.artist COLLATE NOCASE,
                                track.title COLLATE NOCASE,
                                track.provider_track_id
                   ) - 1 AS source_order
            FROM members
            JOIN tracks track
              ON track.provider=members.provider
             AND track.provider_track_id=members.provider_track_id
            {artist_join}
        """, params
    raise ValueError(f"Unsupported SQL collection type: {kind}")


def _camelot_expression(alias: str = "b") -> str:
    key = f"UPPER(REPLACE(REPLACE({alias}.musical_key, '♯', '#'), '♭', 'B'))"
    minor = {
        "G#": "01A", "AB": "01A", "D#": "02A", "EB": "02A",
        "A#": "03A", "BB": "03A", "F": "04A", "C": "05A",
        "G": "06A", "D": "07A", "A": "08A", "E": "09A",
        "B": "10A", "F#": "11A", "GB": "11A", "C#": "12A", "DB": "12A",
    }
    major = {
        "B": "01B", "F#": "02B", "GB": "02B", "C#": "03B", "DB": "03B",
        "G#": "04B", "AB": "04B", "D#": "05B", "EB": "05B",
        "A#": "06B", "BB": "06B", "F": "07B", "C": "08B",
        "G": "09B", "D": "10B", "A": "11B", "E": "12B",
    }

    def cases(values: dict[str, str]) -> str:
        return " ".join(f"WHEN '{source}' THEN '{target}'" for source, target in values.items())

    return f"""
        CASE
          WHEN UPPER({alias}.key_scale) LIKE '%MINOR%' THEN CASE {key} {cases(minor)} ELSE '' END
          WHEN UPPER({alias}.key_scale) LIKE '%MAJOR%' THEN CASE {key} {cases(major)} ELSE '' END
          ELSE ''
        END
    """


def _query_parts(
    kind: str,
    collection_id: str,
    username: str,
    *,
    query: str = "",
    artists: list[str] | None = None,
    keys: list[str] | None = None,
    ratings: list[str] | None = None,
    tags: list[str] | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    collection_types: list[str] | None = None,
) -> tuple[str, list[Any]]:
    membership_sql, membership_params = _membership(kind, collection_id)
    params: list[Any] = [*membership_params, str(username or "").strip().casefold()]
    predicates: list[str] = []
    normalized_query = " ".join(str(query or "").casefold().split())
    if normalized_query:
        fields = ["b.title", "b.remix"]
        if kind == "search":
            fields.extend(["b.artist", "b.album"])
        predicates.append("LOWER(" + " || ' ' || ".join(f"COALESCE({field}, '')" for field in fields) + ") LIKE ?")
        params.append(f"%{normalized_query}%")
    artist_values = [str(value) for value in artists or [] if str(value)]
    if artist_values:
        placeholders = ",".join("?" for _ in artist_values)
        predicates.append(f"""EXISTS (
            SELECT 1 FROM track_artists filter_artist
            WHERE filter_artist.provider='tidal'
              AND filter_artist.provider_track_id=b.id
              AND filter_artist.artist_key IN ({placeholders})
        )""")
        params.extend(artist_values)
    key_values = [str(value) for value in keys or [] if str(value)]
    if key_values:
        placeholders = ",".join("?" for _ in key_values)
        predicates.append(f"({_camelot_expression()}) IN ({placeholders})")
        params.extend(key_values)
    if bpm_min is not None:
        predicates.append("b.bpm >= ?")
        params.append(float(bpm_min))
    if bpm_max is not None:
        predicates.append("b.bpm <= ?")
        params.append(float(bpm_max))
    rating_values = [str(value) for value in ratings or [] if str(value)]
    if rating_values:
        placeholders = ",".join("?" for _ in rating_values)
        predicates.append(f"""EXISTS (
            SELECT 1 FROM track_dimension_values rating_filter
            WHERE rating_filter.provider='tidal'
              AND rating_filter.provider_track_id=b.id
              AND rating_filter.dimension='rating'
              AND rating_filter.value IN ({placeholders})
        )""")
        params.extend(rating_values)
    tag_pairs = [
        tuple(str(value).split(":", 1)) for value in tags or [] if ":" in str(value)
    ]
    if tag_pairs:
        clauses = []
        for dimension, value in tag_pairs:
            clauses.append("(tag_filter.dimension=? AND tag_filter.value=?)")
            params.extend([dimension, value])
        predicates.append("""EXISTS (
            SELECT 1 FROM track_dimension_values tag_filter
            WHERE tag_filter.provider='tidal'
              AND tag_filter.provider_track_id=b.id
              AND (""" + " OR ".join(clauses) + "))")
    type_clauses: list[str] = []
    for collection_type in dict.fromkeys(collection_types or []):
        if collection_type in {"playlist", "event", "source"}:
            type_clauses.append("""EXISTS (
                SELECT 1 FROM playlist_tracks type_pt
                JOIN playlists type_p
                  ON type_p.provider=type_pt.provider
                 AND type_p.provider_playlist_id=type_pt.provider_playlist_id
                WHERE type_pt.provider='tidal'
                  AND type_pt.provider_track_id=b.id
                  AND type_p.collection_type=?
            )""")
            params.append(collection_type)
        elif collection_type == "mix":
            type_clauses.append("""EXISTS (
                SELECT 1 FROM setlist_tracks type_st
                WHERE type_st.provider='tidal' AND type_st.provider_track_id=b.id
            )""")
        elif collection_type == "watched_mix":
            type_clauses.append("""EXISTS (
                SELECT 1 FROM watched_mix_tracks type_wmt
                WHERE type_wmt.provider='tidal' AND type_wmt.provider_track_id=b.id
            )""")
    if type_clauses:
        predicates.append("(" + " OR ".join(type_clauses) + ")")
    where = " AND ".join(predicates) if predicates else "1=1"
    ctes = f"""
        WITH membership AS ({membership_sql}),
        plays AS (
            SELECT tidal_track_id AS track_id, COUNT(*) AS play_count,
                   MAX(played_at) AS last_played
            FROM lastfm_scrobbles
            WHERE username=? AND tidal_track_id IS NOT NULL
            GROUP BY tidal_track_id
        ),
        base AS (
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix, t.album,
                   t.duration_seconds, t.bpm, t.musical_key, t.key_scale,
                   t.release_year AS year, t.isrc, t.album_art_url,
                   membership.date_added, membership.mix_position,
                   membership.source_order,
                   plays.play_count, plays.last_played
            FROM membership
            JOIN tracks t
              ON t.provider='tidal' AND t.provider_track_id=membership.track_id
            LEFT JOIN plays ON plays.track_id=t.provider_track_id
        ),
        filtered AS (SELECT b.* FROM base b WHERE {where})
    """
    return ctes, params


def _sort_expression(field: str) -> str:
    if field in TEXT_SORT_FIELDS:
        return f"f.{field} COLLATE NOCASE"
    if field in {"bpm", "year", "play_count"}:
        return f"f.{field}"
    if field == "date_added":
        return "f.date_added"
    if field == "length":
        return "f.duration_seconds"
    if field == "key":
        return _camelot_expression("f")
    if field in DIMENSION_SORT_FIELDS:
        return f"""(
            SELECT GROUP_CONCAT(sort_dimension.value, ' | ')
            FROM track_dimension_values sort_dimension
            WHERE sort_dimension.provider='tidal'
              AND sort_dimension.provider_track_id=f.id
              AND sort_dimension.dimension='{field}'
        )"""
    membership_type = MEMBERSHIP_SORT_FIELDS.get(field)
    if membership_type in {"playlist", "event", "source"}:
        return f"""(
            SELECT GROUP_CONCAT(sort_playlist.name, ' | ')
            FROM playlist_tracks sort_pt
            JOIN playlists sort_playlist
              ON sort_playlist.provider=sort_pt.provider
             AND sort_playlist.provider_playlist_id=sort_pt.provider_playlist_id
            WHERE sort_pt.provider='tidal' AND sort_pt.provider_track_id=f.id
              AND sort_playlist.collection_type='{membership_type}'
        )"""
    if membership_type == "mix":
        return """(
            SELECT GROUP_CONCAT(sort_setlist.folder_name, ' | ')
            FROM setlist_tracks sort_setlist
            WHERE sort_setlist.provider='tidal' AND sort_setlist.provider_track_id=f.id
        )"""
    if membership_type == "watched_mix":
        return """(
            SELECT GROUP_CONCAT(COALESCE(NULLIF(sort_mix.channel_name, ''), sort_mix.title), ' | ')
            FROM watched_mix_tracks sort_wmt
            JOIN watched_mixes sort_mix ON sort_mix.video_id=sort_wmt.video_id
            WHERE sort_wmt.provider='tidal' AND sort_wmt.provider_track_id=f.id
        )"""
    return "f.source_order"


def collection_track_page(
    kind: str,
    collection_id: str,
    username: str,
    *,
    offset: int,
    limit: int,
    sort_field: str = "",
    sort_direction: str = "",
    path: Path = DATABASE_PATH,
    **filters: Any,
) -> tuple[list[dict[str, Any]], int]:
    """Return one filtered/sorted page before relationship enrichment."""
    initialize(path)
    ctes, params = _query_parts(kind, collection_id, username, **filters)
    direction = "DESC" if str(sort_direction).casefold() == "desc" else "ASC"
    expression = _sort_expression(sort_field) if sort_direction in {"asc", "desc"} else "f.source_order"
    missing = f"CASE WHEN ({expression}) IS NULL OR ({expression})='' THEN 1 ELSE 0 END"
    sql = ctes + f"""
        SELECT f.*, COUNT(*) OVER() AS _total
        FROM filtered f
        ORDER BY {missing} ASC, {expression} {direction}, f.source_order ASC, f.id ASC
        LIMIT ? OFFSET ?
    """
    with connect_readonly(path) as connection:
        rows = connection.execute(sql, [*params, max(1, int(limit)), max(0, int(offset))]).fetchall()
    total = int(rows[0]["_total"]) if rows else 0
    return [
        {key: value for key, value in dict(row).items() if key != "_total"}
        for row in rows
    ], total


def collection_stats(
    kind: str,
    collection_id: str,
    username: str,
    *,
    path: Path = DATABASE_PATH,
    **filters: Any,
) -> dict[str, Any]:
    """Aggregate collection statistics without materializing its track rows."""
    initialize(path)
    ctes, params = _query_parts(kind, collection_id, username, **filters)
    sql = ctes + """
        SELECT 'artist' AS record_type, artist.artist_key AS key,
               artist.name AS label, COUNT(DISTINCT filtered.id) AS item_count,
               NULL AS minimum, NULL AS maximum
        FROM filtered
        JOIN track_artists filtered_artist
          ON filtered_artist.provider='tidal'
         AND filtered_artist.provider_track_id=filtered.id
        JOIN artists artist
          ON artist.provider=filtered_artist.provider
         AND artist.artist_key=filtered_artist.artist_key
        GROUP BY artist.artist_key, artist.name
        UNION ALL
        SELECT 'bpm', '', '', COUNT(*), MIN(bpm), MAX(bpm) FROM filtered WHERE bpm > 0
        UNION ALL
        SELECT 'vibe', vibe.value, vibe.value, COUNT(DISTINCT filtered.id), NULL, NULL
        FROM filtered
        JOIN track_dimension_values vibe
          ON vibe.provider='tidal' AND vibe.provider_track_id=filtered.id
         AND vibe.dimension='vibe'
        GROUP BY vibe.value
    """
    with connect_readonly(path) as connection:
        rows = connection.execute(sql, params).fetchall()
    return _stats_from_rows(rows)


def _stats_from_rows(rows: list[Any]) -> dict[str, Any]:
    artists = [
        {"id": str(row["key"]), "name": str(row["label"]), "count": int(row["item_count"])}
        for row in rows if row["record_type"] == "artist"
    ]
    artists.sort(key=lambda item: (-item["count"], item["name"].casefold()))
    bpm = next((row for row in rows if row["record_type"] == "bpm"), None)
    vibes = [
        (str(row["key"]), int(row["item_count"]))
        for row in rows if row["record_type"] == "vibe"
    ]
    vibes.sort(key=lambda item: (-item[1], item[0].casefold()))
    return {
        "top_artists": artists[:3],
        "artist_options": [
            {"label": item["name"], "value": item["id"]}
            for item in sorted(artists, key=lambda item: item["name"].casefold())
        ],
        "bpm_min": float(bpm["minimum"]) if bpm and bpm["minimum"] is not None else None,
        "bpm_max": float(bpm["maximum"]) if bpm and bpm["maximum"] is not None else None,
        "vibe": vibes[0][0] if vibes else "",
        "vibe_count": vibes[0][1] if vibes else 0,
    }


def collection_track_page_with_stats(
    kind: str,
    collection_id: str,
    username: str,
    *,
    offset: int,
    limit: int,
    sort_field: str = "",
    sort_direction: str = "",
    path: Path = DATABASE_PATH,
    **filters: Any,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Return the first page and statistics in one backend batch."""
    initialize(path)
    ctes, params = _query_parts(kind, collection_id, username, **filters)
    direction = "DESC" if str(sort_direction).casefold() == "desc" else "ASC"
    expression = _sort_expression(sort_field) if sort_direction in {"asc", "desc"} else "f.source_order"
    missing = f"CASE WHEN ({expression}) IS NULL OR ({expression})='' THEN 1 ELSE 0 END"
    page_sql = ctes + f"""
        SELECT f.*, COUNT(*) OVER() AS _total
        FROM filtered f
        ORDER BY {missing} ASC, {expression} {direction}, f.source_order ASC, f.id ASC
        LIMIT ? OFFSET ?
    """
    stats_sql = ctes + """
        SELECT 'artist' AS record_type, artist.artist_key AS key,
               artist.name AS label, COUNT(DISTINCT filtered.id) AS item_count,
               NULL AS minimum, NULL AS maximum
        FROM filtered
        JOIN track_artists filtered_artist
          ON filtered_artist.provider='tidal'
         AND filtered_artist.provider_track_id=filtered.id
        JOIN artists artist
          ON artist.provider=filtered_artist.provider
         AND artist.artist_key=filtered_artist.artist_key
        GROUP BY artist.artist_key, artist.name
        UNION ALL
        SELECT 'bpm', '', '', COUNT(*), MIN(bpm), MAX(bpm) FROM filtered WHERE bpm > 0
        UNION ALL
        SELECT 'vibe', vibe.value, vibe.value, COUNT(DISTINCT filtered.id), NULL, NULL
        FROM filtered
        JOIN track_dimension_values vibe
          ON vibe.provider='tidal' AND vibe.provider_track_id=filtered.id
         AND vibe.dimension='vibe'
        GROUP BY vibe.value
    """
    with connect_readonly(path) as connection:
        page_cursor, stats_cursor = execute_batch(connection, [
            (
                page_sql,
                [*params, max(1, int(limit)), max(0, int(offset))],
            ),
            (stats_sql, params),
        ])
        page_rows = page_cursor.fetchall()
        stats_rows = stats_cursor.fetchall()
    total = int(page_rows[0]["_total"]) if page_rows else 0
    items = [
        {key: value for key, value in dict(row).items() if key != "_total"}
        for row in page_rows
    ]
    return items, total, _stats_from_rows(stats_rows)


def collection_relationships(
    track_ids: list[str], path: Path = DATABASE_PATH,
) -> dict[str, dict[str, Any]]:
    """Fetch all inspector/table relationships for one bounded track page."""
    unique_ids = list(dict.fromkeys(str(value) for value in track_ids if value))
    result = {
        track_id: {
            "playlists": [], "events": [], "sources": [], "mixes": [],
            "djmi": [], "artists": [], "dimensions": {},
        }
        for track_id in unique_ids
    }
    if not unique_ids:
        return result
    initialize(path)
    placeholders = ",".join("?" for _ in unique_ids)
    repeated = unique_ids * 5
    sql = f"""
        SELECT 'playlist' AS record_type, pt.provider_track_id AS track_id,
               p.provider_playlist_id AS related_id, p.name AS label,
               p.collection_type AS detail, NULL AS dimension, NULL AS value
        FROM playlist_tracks pt
        JOIN playlists p
          ON p.provider=pt.provider AND p.provider_playlist_id=pt.provider_playlist_id
        WHERE pt.provider='tidal' AND pt.provider_track_id IN ({placeholders})
        UNION ALL
        SELECT 'setlist', st.provider_track_id, s.folder_name,
               COALESCE(NULLIF(s.tidal_playlist_name, ''), s.folder_name),
               '', NULL, NULL
        FROM setlist_tracks st JOIN setlists s ON s.folder_name=st.folder_name
        WHERE st.provider='tidal' AND st.provider_track_id IN ({placeholders})
        UNION ALL
        SELECT 'watched', wmt.provider_track_id, wm.video_id,
               COALESCE(NULLIF(wm.channel_name, ''), NULLIF(wm.title, ''), wm.video_id),
               wm.title, NULL, NULL
        FROM watched_mix_tracks wmt JOIN watched_mixes wm ON wm.video_id=wmt.video_id
        WHERE wmt.provider='tidal' AND wmt.provider_track_id IN ({placeholders})
        UNION ALL
        SELECT 'artist', ta.provider_track_id, a.artist_key, a.name,
               CAST(ta.position AS TEXT), NULL, NULL
        FROM track_artists ta JOIN artists a
          ON a.provider=ta.provider AND a.artist_key=ta.artist_key
        WHERE ta.provider='tidal' AND ta.provider_track_id IN ({placeholders})
        UNION ALL
        SELECT 'dimension', provider_track_id, '', '', '', dimension, value
        FROM track_dimension_values
        WHERE provider='tidal' AND provider_track_id IN ({placeholders})
        ORDER BY track_id, record_type, label COLLATE NOCASE
    """
    with connect_readonly(path) as connection:
        rows = connection.execute(sql, repeated).fetchall()
    for row in rows:
        track_id = str(row["track_id"])
        target = result[track_id]
        record_type = row["record_type"]
        if record_type == "playlist":
            kind = str(row["detail"] or "playlist")
            target[{"playlist": "playlists", "event": "events", "source": "sources"}.get(kind, "playlists")].append(
                {"id": row["related_id"], "name": row["label"], "collection_type": kind}
            )
        elif record_type == "setlist":
            target["mixes"].append({"id": row["related_id"], "name": row["label"]})
        elif record_type == "watched":
            target["djmi"].append(
                {"id": row["related_id"], "name": row["label"], "title": row["detail"]}
            )
        elif record_type == "artist":
            target["artists"].append(
                {"id": row["related_id"], "name": row["label"], "position": int(row["detail"] or 0)}
            )
        elif record_type == "dimension":
            target["dimensions"].setdefault(str(row["dimension"]), []).append(str(row["value"]))
    for target in result.values():
        target["artists"].sort(key=lambda item: item.pop("position"))
    return result
