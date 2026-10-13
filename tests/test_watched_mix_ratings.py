from music_library.database import (
    save_watched_mix,
    set_watched_mix_rating,
    watched_mix,
    watched_mixes,
)


def test_watched_mix_rating_is_stored_on_watched_mix(tmp_path):
    database = tmp_path / "library.sqlite3"
    save_watched_mix(
        "video-id",
        "https://www.youtube.com/watch?v=video-id",
        title="A fine mix",
        path=database,
    )

    assert watched_mix("video-id", database)["rating"] == 0
    assert set_watched_mix_rating("video-id", 4, database)["rating"] == 4
    assert watched_mixes(database)[0]["rating"] == 4
    assert set_watched_mix_rating("video-id", 0, database)["rating"] == 0


def test_watched_mix_rating_rejects_invalid_values(tmp_path):
    database = tmp_path / "library.sqlite3"
    save_watched_mix(
        "video-id",
        "https://www.youtube.com/watch?v=video-id",
        path=database,
    )

    try:
        set_watched_mix_rating("video-id", 6, database)
    except ValueError as exc:
        assert str(exc) == "Rating must be between 0 and 5"
    else:
        raise AssertionError("Expected an invalid rating to be rejected")
