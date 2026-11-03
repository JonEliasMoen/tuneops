from pathlib import Path

from backend.music_library import database
from backend.music_tools.youtube_analytics import service as youtube_service
from backend.utils import backup_turso, migrate_database


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_moved_backend_modules_keep_repository_root_paths():
    assert database.ROOT == REPOSITORY_ROOT
    assert youtube_service.ROOT == REPOSITORY_ROOT
    assert youtube_service.TOKEN_PATH == REPOSITORY_ROOT / ".youtube_oauth.json"
    assert backup_turso.ROOT == REPOSITORY_ROOT
    assert backup_turso.DEFAULT_BACKUP_DIR == REPOSITORY_ROOT / "backups" / "database"
    assert migrate_database.ROOT == REPOSITORY_ROOT
