import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Directorio temporal de arranque para evitar escribir en data/ o dev-data/ durante imports
_BOOT_TMP = Path(tempfile.mkdtemp(prefix="pz_pytest_boot_"))
for _subdir in ("panel", "server", "data", "backups"):
    (_BOOT_TMP / _subdir).mkdir(parents=True, exist_ok=True)

os.environ["PZ_PANEL_DIR"] = str(_BOOT_TMP / "panel")
os.environ["PZ_SERVER_DIR"] = str(_BOOT_TMP / "server")
os.environ["PZ_DATA_DIR"] = str(_BOOT_TMP / "data")
os.environ["PZ_BACKUPS_DIR"] = str(_BOOT_TMP / "backups")
os.environ["PANEL_USER"] = "admin"
os.environ["PANEL_PASSWORD"] = "testpassword123"
os.environ["SECRET_KEY"] = "pytest-secret-key-do-not-use-in-prod"
os.environ["LOGIN_MAX_ATTEMPTS"] = "3"
os.environ["LOGIN_COOLDOWN_SECONDS"] = "60"

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core import security
from app.core.activity_manager import activity_manager
from app.core.backup_manager import backup_manager
from app.core.file_manager import file_manager
from app.core.process_manager import process_manager
from app.core.task_scheduler import task_scheduler
from app.main import app


@pytest.fixture(autouse=True)
def isolated_env(tmp_path):
    """Aísla cada prueba en carpetas temporales independientes y resetea singletons."""
    panel_dir = tmp_path / "panel"
    server_dir = tmp_path / "server"
    data_dir = tmp_path / "data"
    backups_dir = tmp_path / "backups"
    for d in (panel_dir, server_dir, data_dir, backups_dir):
        d.mkdir(parents=True, exist_ok=True)

    settings.panel_dir = panel_dir
    settings.server_dir = server_dir
    settings.data_dir = data_dir
    settings.backups_dir = backups_dir
    settings.console_log = data_dir / "console.txt"
    settings._config_file = panel_dir / "pz_panel_config.json"
    settings._revoked_tokens_file = panel_dir / ".revoked_tokens.json"
    settings.runtime_config = {"secret_key": settings.secret_key}
    settings.admin_user = "admin"
    settings.admin_password = "testpassword123"
    settings.login_max_attempts = 3
    settings.login_cooldown_seconds = 60

    security.login_limiter.max_attempts = 3
    security.login_limiter.cooldown_seconds = 60
    security.login_limiter.records.clear()
    security._revoked_tokens.clear()

    activity_manager.file = panel_dir / "activity.json"
    activity_manager._entries.clear()
    activity_manager._next_id = 1

    backup_manager.backup_dir = backups_dir

    task_scheduler.tasks_file = panel_dir / "tasks.json"
    task_scheduler.tasks = []
    task_scheduler.stop_loop()

    file_manager._custom_base_dir = None
    file_manager.invalidate_quota_cache()

    process_manager.online_players.clear()
    process_manager.log_buffer.clear()
    process_manager.last_exit_code = None
    process_manager.process = None
    process_manager.status = "OFFLINE"
    process_manager.pz_version = None
    process_manager.install_progress = {"running": False, "percent": 0.0, "step": "", "last_line": ""}

    yield tmp_path

    task_scheduler.stop_loop()
    process_manager.online_players.clear()


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def auth_client(client):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert security.SESSION_COOKIE_NAME in client.cookies
    return client
