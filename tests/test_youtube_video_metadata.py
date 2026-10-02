from music_library.database import (
    store_youtube_video_metadata,
    youtube_video_metadata,
)


def test_youtube_video_metadata_is_persisted_independently(tmp_path):
    database = tmp_path / "library.sqlite3"

    stored = store_youtube_video_metadata([{
        "video_id": "abc123",
        "title": "My Mix",
        "upload_date": "2026-01-05",
    }], database)

    assert stored == 1
    result = youtube_video_metadata(database)["abc123"]
    assert result["title"] == "My Mix"
    assert result["upload_date"] == "2026-01-05"
