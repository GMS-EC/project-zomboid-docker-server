import json
import tarfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.core import security
from app.core.activity_manager import activity_manager
from app.core.diagnostic_manager import diagnostic_manager
from app.core.player_manager import player_manager
from app.core.process_manager import process_manager
from app.core.pz_settings_manager import pz_settings_manager
from app.core.task_scheduler import task_scheduler, _next_cron_dt
from app.core.webhook_manager import webhook_manager


def test_security_auth_rate_limit_revocation_and_headers(client):
    # Acceso sin autenticación a "/" redirige a "/login" y entrega headers de seguridad
    r_root = client.get("/", follow_redirects=False)
    assert r_root.status_code == 302
    assert r_root.headers["location"].endswith("/login")
    assert r_root.headers.get("X-Content-Type-Options") == "nosniff"
    assert r_root.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r_root.headers

    # API sin sesión devuelve 401
    r_api = client.get("/api/status")
    assert r_api.status_code == 401

    # Intentos fallidos activan bloqueo 429 en el intento max_attempts + 1 (max=3)
    for _ in range(3):
        bad = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert bad.status_code == 401
    locked = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert locked.status_code == 429

    # Resetear rate limiter simulando paso de cooldown y entrar correctamente
    security.login_limiter.records.clear()
    ok = client.post(
        "/login",
        data={"username": "admin", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    token = ok.cookies.get(security.SESSION_COOKIE_NAME)
    assert token

    dash = client.get("/")
    assert dash.status_code == 200
    for marker in ('id="tab-files"', 'id="tab-logs"', 'id="tab-mods"', 'id="tab-players"', 'id="tab-backups"', 'id="tab-tasks"'):
        assert marker in dash.text

    assert client.get("/api/status").status_code == 200

    # Cerrar sesión revoca el token; reutilizarlo manualmente devuelve 401
    out = client.get("/logout", follow_redirects=False)
    assert out.status_code == 302
    assert client.get("/api/status", cookies={security.SESSION_COOKIE_NAME: token}).status_code == 401


def test_dynamic_settings_ini_and_sandbox(auth_client):
    settings.save_wizard({
        "server_name": "My PZ/World! 42",
        "use_steam": True,
        "memory_min": "4g",
        "memory_max": "8g",
        "max_players": 24,
        "branch": "unstable",
        "additional_args": "-debug",
        "server_port": 16300,
        "direct_port": 16301,
        "rcon_port": 27020,
        "disk_limit_gb": 12.5,
    })

    # Sanitización de nombre + propiedades dinámicas
    assert "/" not in settings.server_name
    assert "!" not in settings.server_name
    assert settings.branch == "unstable"
    assert settings.additional_args == "-debug"
    assert settings.server_port == 16300
    assert settings.direct_port == 16301
    assert settings.rcon_port == 27020
    assert settings.disk_limit_gb == 12.5

    # Guardar cambios vía API /api/settings (ini + sandbox + panel)
    resp = auth_client.post("/api/settings", json={
        "server": {"MaxPlayers": 30, "PVP": "true", "DefaultPort": 16400},
        "sandbox": {"xp_multiplier": 2.5, "day_length": 4},
        "panel": {"branch": "legacy41", "additional_args": "-cachedir=/tmp", "disk_limit_gb": 20},
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    assert settings.branch == "legacy41"
    assert settings.server_port == 16400
    assert settings.max_players == 30
    assert settings.disk_limit_gb == 20.0

    got = auth_client.get("/api/settings").json()
    assert got["server"]["MaxPlayers"] == "30"
    assert got["server"]["PVP"] == "true"
    assert float(got["sandbox"]["xp_multiplier"]) == 2.5
    assert int(got["sandbox"]["day_length"]) == 4


def test_smart_pz_mods_manager_separation_and_resolution(auth_client):
    # Crear un mod local simulado con mod.info + carpeta de mapa
    local_mod_dir = settings.server_dir / "steamapps" / "workshop" / "content" / "108600" / "2729973596" / "mods" / "BritaArmor"
    (local_mod_dir / "media" / "maps" / "BritaMap").mkdir(parents=True, exist_ok=True)
    (local_mod_dir / "media" / "maps" / "BritaMap" / "map.info").write_text("title=Brita Map\n", encoding="utf-8")
    (local_mod_dir / "mod.info").write_text("name=Brita Armor Pack\nid=Brita_2\n", encoding="utf-8")

    # Mockear respuesta de Steam API para un segundo mod remoto (2687618628)
    mock_steam_resp = MagicMock()
    mock_steam_resp.status_code = 200
    mock_steam_resp.json.return_value = {
        "response": {
            "publishedfiledetails": [{
                "publishedfileid": "2687618628",
                "title": "Autotsar Tuning Atelier",
                "preview_url": "https://steamstatic.com/preview.jpg",
                "description": "Workshop ID: 2687618628\nMod ID: AutotsarBus\nMap Folder: AutotsarYard",
            }]
        }
    }

    with patch("app.core.pz_settings_manager.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_steam_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        save_res = auth_client.post("/api/mods", json={
            "workshop_items": "2729973596;2687618628",
            "auto_resolve": True,
        })
        assert save_res.status_code == 200
        assert save_res.json()["success"] is True

        resolve_res = auth_client.post("/api/mods/resolve", json={"sync_to_ini": True})
        assert resolve_res.status_code == 200
        assert resolve_res.json()["success"] is True

    mods_data = auth_client.get("/api/mods").json()
    assert mods_data["workshop_items"] == ["2729973596", "2687618628"]
    # Verificar que Mods= contiene IDs textuales y NUNCA los números de Workshop
    assert "Brita_2" in mods_data["mod_ids"]
    assert "AutotsarBus" in mods_data["mod_ids"]
    assert "2729973596" not in mods_data["mod_ids"]
    assert "2687618628" not in mods_data["mod_ids"]
    assert len(mods_data["local_mods"]) >= 1
    assert any(c["workshop_id"] == "2687618628" and c["title"] == "Autotsar Tuning Atelier" for c in mods_data["catalog"])


def test_console_player_tracking_and_player_actions(auth_client):
    # Parseo de eventos reales y simulador + ignorar ecos "> ..."
    process_manager.parse_console_line("> simjoin FakeEcho")
    assert len(process_manager.online_players) == 0

    process_manager.parse_console_line("[PZ-Sim] Jugador conectado: RickGrimes (SteamID: 76561198000000001)")
    process_manager.parse_console_line("Players connected (2):")
    process_manager.parse_console_line("-RickGrimes")
    process_manager.parse_console_line("-DarylDixon")

    status_data = auth_client.get("/api/status").json()
    assert status_data["players_online"] == 2
    assert status_data["metrics"]["players_online"] == 2
    assert process_manager.online_players["rickgrimes"]["steam_id"] == "76561198000000001"

    players_data = auth_client.get("/api/players").json()
    assert players_data["online_count"] == 2
    assert players_data["max_players"] == settings.max_players
    names = {p["name"] for p in players_data["online"]}
    assert names == {"RickGrimes", "DarylDixon"}

    sent_cmds = []

    async def fake_send(cmd: str):
        sent_cmds.append(cmd)
        return f"Sent: {cmd}"

    with patch.object(process_manager, "send_command", side_effect=fake_send):
        r_add = auth_client.post("/api/players/add", json={"username": "MaggieGreene", "password": "pw123", "access_level": "moderator"})
        assert r_add.status_code == 200 and r_add.json()["success"] is True

        r_role = auth_client.post("/api/players/role", json={"username": "DarylDixon", "access_level": "admin"})
        assert r_role.status_code == 200 and r_role.json()["success"] is True

        r_msg = auth_client.post("/api/players/message", json={"username": "DarylDixon", "message": "Hola mundo"})
        assert r_msg.status_code == 200 and r_msg.json()["success"] is True

        r_kick = auth_client.post("/api/players/kick", json={"username": "DarylDixon"})
        assert r_kick.status_code == 200 and r_kick.json()["success"] is True

        r_ban = auth_client.post("/api/players/ban", json={"username": "DarylDixon", "reason": "Grief"})
        assert r_ban.status_code == 200 and r_ban.json()["success"] is True

        r_unban = auth_client.post("/api/players/unban", json={"username": "DarylDixon"})
        assert r_unban.status_code == 200 and r_unban.json()["success"] is True

    assert any(c.startswith("adduser ") for c in sent_cmds)
    assert any(c == 'setaccesslevel "DarylDixon" "admin"' for c in sent_cmds)
    assert any('DarylDixon' in c and 'kickuser' in c for c in sent_cmds)
    assert any('DarylDixon' in c and 'banuser' in c for c in sent_cmds)
    assert any('DarylDixon' in c and 'unbanuser' in c for c in sent_cmds)

    process_manager.parse_console_line("[PZ-Sim] Jugador desconectado: RickGrimes")
    assert "rickgrimes" not in process_manager.online_players


def test_file_manager_crud_zip_and_security(auth_client):
    assert auth_client.post("/api/files/create-folder", json={"path": "ServerConfigs"}).status_code == 200
    assert auth_client.post("/api/files/create-file", json={"path": "ServerConfigs/test.ini"}).status_code == 200
    assert auth_client.post("/api/files/write", json={"path": "ServerConfigs/test.ini", "content": "PVP=false\n"}).status_code == 200

    read_res = auth_client.get("/api/files/read", params={"path": "ServerConfigs/test.ini"})
    assert read_res.status_code == 200
    assert "PVP=false" in read_res.json()["content"]

    assert auth_client.post("/api/files/duplicate", json={"path": "ServerConfigs/test.ini"}).status_code == 200
    assert auth_client.post("/api/files/rename", json={"path": "ServerConfigs/test.ini", "new_name": "renamed.ini"}).status_code == 200
    comp = auth_client.post("/api/files/compress", json={"path": "ServerConfigs"}).json()
    assert comp["archive_name"].endswith(".zip")

    assert auth_client.post("/api/files/create-folder", json={"path": "Extracted"}).status_code == 200
    assert auth_client.post("/api/files/extract", json={"path": comp["archive_name"], "target_dir": "Extracted"}).status_code == 200
    assert (settings.data_dir / "Extracted" / "ServerConfigs" / "renamed.ini").is_file()

    # Path traversal y archivo protegido bloqueados con 403
    assert auth_client.get("/api/files/read", params={"path": "../panel/pz_panel_config.json"}).status_code == 403
    (settings.data_dir / "pz_panel_config.json").write_text("{}", encoding="utf-8")
    assert auth_client.get("/api/files/read", params={"path": "pz_panel_config.json"}).status_code == 403
    assert auth_client.delete("/api/files/delete", params={"path": "pz_panel_config.json"}).status_code == 403


def test_scoped_backups_create_list_restore_delete(auth_client):
    world_dir = settings.data_dir / "Saves" / "Multiplayer" / settings.server_name
    server_dir = settings.data_dir / "Server"
    db_dir = settings.data_dir / "db"
    world_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)

    (world_dir / "map_meta.bin").write_bytes(b"WORLD_V1")
    (server_dir / f"{settings.server_name}.ini").write_text("MaxPlayers=16\n", encoding="utf-8")
    (db_dir / f"{settings.server_name}.db").write_bytes(b"DB_V1")

    r_world = auth_client.post("/api/backups/create", json={"name": "solo_mundo", "scope": "world"}).json()
    r_cfg = auth_client.post("/api/backups/create", json={"name": "solo_cfg", "scope": "config"}).json()
    r_full = auth_client.post("/api/backups/create", json={"name": "completo", "scope": "full"}).json()
    assert r_world["success"] and r_cfg["success"] and r_full["success"]

    with tarfile.open(settings.backups_dir / r_world["filename"], "r:gz") as tf:
        names = tf.getnames()
        assert any("map_meta.bin" in n for n in names)
        assert not any(n.endswith(".ini") for n in names)

    with tarfile.open(settings.backups_dir / r_cfg["filename"], "r:gz") as tf:
        names = tf.getnames()
        assert any(n.endswith(".ini") for n in names)
        assert not any("map_meta.bin" in n for n in names)

    # Listar backups y verificar metadata de alcance/origen
    listed = auth_client.get("/api/backups/list").json()
    by_name = {b["filename"]: b for b in listed}
    assert by_name[r_world["filename"]]["scope"] == "world"
    assert by_name[r_cfg["filename"]]["scope"] == "config"
    assert by_name[r_full["filename"]]["scope"] == "full"

    # Mutar mundo y restaurar copia full
    (world_dir / "map_meta.bin").write_bytes(b"CORRUPTED")
    with patch.object(process_manager, "get_status", return_value="OFFLINE"):
        r_rest = auth_client.post("/api/backups/restore", json={"filename": r_full["filename"]}).json()
    assert r_rest["success"] is True
    assert (world_dir / "map_meta.bin").read_bytes() == b"WORLD_V1"

    r_del = auth_client.delete(f"/api/backups/{r_cfg['filename']}").json()
    assert r_del["success"] is True


def test_custom_tasks_and_pure_python_cron(auth_client):
    base_dt = datetime(2026, 6, 1, 14, 10, 0)
    nxt = _next_cron_dt("30 14 * * *", base_dt)
    assert nxt == datetime(2026, 6, 1, 14, 30, 0)
    nxt_step = _next_cron_dt("*/15 * * * *", base_dt)
    assert nxt_step == datetime(2026, 6, 1, 14, 15, 0)

    c_res = auth_client.post("/api/tasks", json={
        "name": "Anuncio Horario",
        "action": "command",
        "command": 'servermsg "Servidor activo"',
        "schedule_type": "cron",
        "cron_expression": "0 */2 * * *",
    }).json()
    task_id = c_res["id"]
    assert c_res["next_run"] is not None

    tasks = auth_client.get("/api/tasks").json()
    assert len(tasks) == 1

    # Cuando el servidor está OFFLINE, las tareas command se omiten de forma segura
    offline_res = auth_client.post(f"/api/tasks/{task_id}/run").json()
    assert offline_res["success"] is True
    assert "apagado" in offline_res["message"].lower()

    # Cuando el servidor está RUNNING, envía el comando por STDIN/RCON
    with patch.object(process_manager, "get_status", return_value="RUNNING"), \
         patch.object(process_manager, "send_command", new=AsyncMock(return_value="ok")) as mock_cmd:
        run_res = auth_client.post(f"/api/tasks/{task_id}/run").json()
        assert run_res["success"] is True
        mock_cmd.assert_awaited_with('servermsg "Servidor activo"')

    t_res = auth_client.post(f"/api/tasks/{task_id}/toggle", json={"enabled": False}).json()
    assert t_res["task"]["enabled"] is False

    d_res = auth_client.delete(f"/api/tasks/{task_id}").json()
    assert d_res["success"] is True
    assert auth_client.get("/api/tasks").json() == []


def test_activity_logs_compat_and_csv_export(auth_client):
    entry = activity_manager.log("Consola", '=cmd|" /C calc"!A0', user="admin", action="command_executed")
    assert entry["detail"] == entry["details"] == entry["message"]
    assert entry["id"] >= 1
    assert entry["action"] == "command_executed"

    logs_res = auth_client.get("/api/activity/logs", params={"category": "console", "search": "calc"}).json()
    assert logs_res["total"] == 1
    assert logs_res["logs"][0]["message"] == '=cmd|" /C calc"!A0'

    csv_res = auth_client.get("/api/activity/export", params={"format": "csv"})
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    # Protección CSV Formula Injection: "=" debe quedar precedido por "'"
    assert "'=cmd|" in csv_res.text

    clr = auth_client.post("/api/activity/clear").json()
    assert clr["success"] is True


def test_diagnostics_and_webhooks(auth_client):
    settings.console_log.write_text(
        "ERROR: java.lang.OutOfMemoryError: Java heap space\n",
        encoding="utf-8",
    )
    diag = auth_client.get("/api/diagnostics").json()
    assert diag["has_issue"] is True
    assert diag["category"] == "memory"

    settings.console_log.write_text(
        "ERROR: KahluaException in SandboxVars.lua line 10\n",
        encoding="utf-8",
    )
    diag_lua = auth_client.get("/api/diagnostics").json()
    assert diag_lua["has_issue"] is True
    assert diag_lua["category"] == "lua_mod"

    # Webhooks Discord + Telegram + masking + dispatch
    save_wh = auth_client.post("/api/webhooks/config", json={
        "language": "es",
        "discord": {"enabled": True, "webhook_url": "https://discord.com/api/webhooks/1/abc"},
        "telegram": {"enabled": True, "bot_token": "123456:SECRET_TOKEN", "chat_id": "-100999"},
        "events": {"server_start": True, "player_join": True},
    }).json()
    assert save_wh["success"] is True

    got_wh = auth_client.get("/api/webhooks/config").json()
    assert got_wh["telegram"]["enabled"] is True
    assert got_wh["telegram"]["bot_token"] == "••••••••••••"
    assert got_wh["telegram"]["chat_id"] == "-100999"

    # Re-enviar token enmascarado debe preservar el token real
    auth_client.post("/api/webhooks/config", json={
        "telegram": {"enabled": True, "bot_token": "••••••••••••", "chat_id": "-100999"},
    })
    assert settings.runtime_config["telegram_bot_token"] == "123456:SECRET_TOKEN"

    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    with patch("app.core.webhook_manager.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_http_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        import asyncio
        sent = asyncio.run(webhook_manager.notify("start", "Servidor listo"))
        assert sent is True
        # Debe haberse enviado tanto a Discord como a Telegram (2 calls)
        assert mock_client.post.await_count == 2


def test_workshop_collection_and_spawnregions_sync(auth_client):
    col_resp = MagicMock()
    col_resp.status_code = 200
    col_resp.json.return_value = {
        "response": {
            "collectiondetails": [{
                "result": 1,
                "children": [
                    {"publishedfileid": "2729973596"},
                    {"publishedfileid": "2687618628"},
                ],
            }]
        }
    }

    items_resp = MagicMock()
    items_resp.status_code = 200
    items_resp.json.return_value = {
        "response": {
            "publishedfiledetails": [
                {
                    "publishedfileid": "2729973596",
                    "title": "Raven Creek",
                    "description": "Mod ID: RavenCreek\nMap Folder: RavenCreek",
                },
                {
                    "publishedfileid": "2687618628",
                    "title": "Mod Tool Lib",
                    "description": "Mod ID: ModToolLib",
                },
            ]
        }
    }

    with patch("app.core.pz_settings_manager.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = [col_resp, items_resp]
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        res = auth_client.post(
            "/api/mods/collection",
            json={"collection": "https://steamcommunity.com/sharedfiles/filedetails/?id=999001"},
        ).json()

    assert res["success"] is True
    assert res["collection_id"] == "999001"
    assert res["imported_count"] == 2
    assert "RavenCreek" in res["mod_ids"]
    assert "ModToolLib" in res["mod_ids"]
    assert res["map_folders"][0] == "RavenCreek"
    assert "Muldraugh, KY" in res["map_folders"]

    # Verificar generación automática de _spawnregions.lua y lectura vía /api/settings
    assert pz_settings_manager.spawnregions_path.is_file()
    sr_text = pz_settings_manager.spawnregions_path.read_text(encoding="utf-8")
    assert 'name = "RavenCreek"' in sr_text
    assert 'file = "media/maps/RavenCreek/spawnpoints.lua"' in sr_text
    assert sr_text.index("RavenCreek") < sr_text.index("Muldraugh, KY")

    raw_save = auth_client.post("/api/settings/raw", json={
        "type": "spawnregions",
        "content": sr_text + "-- custom comment\n",
    }).json()
    assert raw_save["success"] is True

    settings_data = auth_client.get("/api/settings").json()
    assert "-- custom comment" in settings_data["raw_spawnregions"]
    assert settings.server_name in settings_data["profiles"]


def test_world_wipe_preserves_config_and_backs_up(auth_client):
    world_dir = settings.data_dir / "Saves" / "Multiplayer" / settings.server_name
    server_dir = settings.data_dir / "Server"
    db_dir = settings.data_dir / "db"
    world_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)

    (world_dir / "map_p.bin").write_bytes(b"OLD_WORLD_DATA")
    ini_file = server_dir / f"{settings.server_name}.ini"
    ini_file.write_text("MaxPlayers=22\n", encoding="utf-8")
    db_file = db_dir / f"{settings.server_name}.db"
    db_file.write_bytes(b"WHITELIST_DB")

    wipe_res = auth_client.post("/api/server/wipe-world").json()
    assert wipe_res["success"] is True
    assert wipe_res["removed"] is True
    assert wipe_res["backup"] and wipe_res["backup"].endswith(".tar.gz")

    # El mundo fue limpiado pero .ini, .db y respaldo previo permanecen intactos
    assert not world_dir.exists()
    assert ini_file.read_text(encoding="utf-8") == "MaxPlayers=22\n"
    assert db_file.read_bytes() == b"WHITELIST_DB"
    assert (settings.backups_dir / wipe_res["backup"]).is_file()


def test_player_admin_actions_and_install_progress(auth_client):
    process_manager._update_install_progress("42.5% Downloading Depot 380871...")
    st = auth_client.get("/api/status").json()
    assert st["install_progress"]["running"] is True
    assert st["install_progress"]["percent"] == 42.5
    assert "Descargando" in st["install_progress"]["step"]

    sent = []

    async def fake_send(cmd: str):
        sent.append(cmd)
        return f"Executed: {cmd}"

    with patch.object(process_manager, "send_command", side_effect=fake_send):
        assert auth_client.post("/api/players/action", json={"username": "Rick", "action": "godmode_on"}).json()["success"]
        assert auth_client.post("/api/players/action", json={"username": "Rick", "action": "invisible_on"}).json()["success"]
        assert auth_client.post("/api/players/action", json={"username": "Rick", "action": "additem", "arg1": "Base.Axe", "arg2": "3"}).json()["success"]
        assert auth_client.post("/api/players/action", json={"username": "Rick", "action": "addvehicle", "arg1": "Base.CarNormal"}).json()["success"]
        assert auth_client.post("/api/players/action", json={"username": "Rick", "action": "addxp", "arg1": "Carpentry", "arg2": "500"}).json()["success"]
        assert auth_client.post("/api/players/action", json={"username": "Rick", "action": "teleport", "arg1": "Daryl"}).json()["success"]
        assert auth_client.post("/api/players/action", json={"username": "Rick", "action": "teleport", "arg1": "10600,9300,0"}).json()["success"]

    assert 'godmod "Rick" -true' in sent
    assert 'invisible "Rick" -true' in sent
    assert 'additem "Rick" "Base.Axe" 3' in sent
    assert 'addvehicle "Base.CarNormal" "Rick"' in sent
    assert 'addxp "Rick" Carpentry=500' in sent
    assert 'teleport "Rick" "Daryl"' in sent
    assert 'teleportto 10600,9300,0' in sent


def test_dockraft_backups_policies_targets_and_uncompressed_restore(auth_client):
    srv_dir = settings.data_dir / "Server"
    world_dir = settings.data_dir / "Saves" / "Multiplayer" / settings.server_name
    srv_dir.mkdir(parents=True, exist_ok=True)
    world_dir.mkdir(parents=True, exist_ok=True)

    ini_path = srv_dir / f"{settings.server_name}.ini"
    ini_path.write_text("PublicName=OriginalPZ\n", encoding="utf-8")
    (world_dir / "map_t.bin").write_bytes(b"WORLD_BIN")

    targets = auth_client.get("/api/backups/targets").json()
    target_names = [t["name"] for t in targets]
    assert "Server" in target_names
    assert "Saves" in target_names

    # Políticas de respaldo (crear, listar, actualizar, eliminar)
    pol_res = auth_client.post("/api/backups/policies", json={
        "name": "Solo Config",
        "scope": "custom",
        "targets": ["Server"],
        "compression": False,
        "stop_server": False,
        "pre_command": 'servermsg "Iniciando"',
        "post_command": 'servermsg "Listo"',
    }).json()
    assert pol_res["success"] is True
    pid = pol_res["policy"]["id"]

    pol_list = auth_client.get("/api/backups/policies").json()
    assert any(p["id"] == pid and p["name"] == "Solo Config" for p in pol_list["policies"])

    cfg_save = auth_client.post("/api/backups/config", json={"backup_max_count": 5}).json()
    assert cfg_save["success"] is True
    assert auth_client.get("/api/backups/config").json()["backup_max_count"] == 5

    # Crear respaldo custom sin compresión
    created = auth_client.post("/api/backups/create", json={
        "scope": "custom",
        "targets": ["Server"],
        "compression": False,
        "tag": "custom_raw",
    }).json()
    assert created["success"] is True
    fname = created["filename"]
    archive_path = settings.backups_dir / fname
    assert archive_path.is_file()

    # Verificar que es un tar válido sin gzip y solo contiene Server/
    with tarfile.open(str(archive_path), "r:") as tar:
        names = tar.getnames()
        assert any(n.endswith(f"{settings.server_name}.ini") for n in names)
        assert not any("Saves" in n for n in names)

    listed = auth_client.get("/api/backups/list").json()
    assert any(b["filename"] == fname and b["scope"] == "custom" for b in listed)
    status = auth_client.get("/api/backups/status").json()
    assert status["is_running"] is False
    assert status["status"] == "completed"

    # Alterar .ini y restaurar desde archivo sin comprimir
    ini_path.write_text("PublicName=Corrupted\n", encoding="utf-8")
    restored = auth_client.post("/api/backups/restore", json={"filename": fname}).json()
    assert restored["success"] is True
    assert ini_path.read_text(encoding="utf-8") == "PublicName=OriginalPZ\n"

    # Eliminar vía REST DELETE /api/backups/{filename} y eliminar política
    del_res = auth_client.delete(f"/api/backups/{fname}").json()
    assert del_res["success"] is True
    assert not archive_path.exists()
    assert auth_client.delete(f"/api/backups/{fname}").status_code == 404

    del_pol = auth_client.delete(f"/api/backups/policies/{pid}").json()
    assert del_pol["success"] is True
    assert all(p["id"] != pid for p in del_pol["policies"])


def test_dockraft_tasks_crud_edit_and_backup_policy(auth_client):
    srv_dir = settings.data_dir / "Server"
    world_dir = settings.data_dir / "Saves" / "Multiplayer" / settings.server_name
    srv_dir.mkdir(parents=True, exist_ok=True)
    world_dir.mkdir(parents=True, exist_ok=True)
    (srv_dir / "keep.ini").write_text("PVP=false\n", encoding="utf-8")
    (world_dir / "skip.bin").write_bytes(b"SKIP_ME")

    pol = auth_client.post("/api/backups/policies", json={
        "name": "Politica Tarea",
        "scope": "custom",
        "targets": ["Server"],
        "compression": False,
    }).json()["policy"]

    # Crear tarea ligada a la política de respaldo usando endpoint REST Dockraft
    created = auth_client.post("/api/tasks", json={
        "name": "Backup Nocturno",
        "action": "backup",
        "backup_policy_id": pol["id"],
        "schedule_type": "cron",
        "cron_expression": "0 4 * * *",
        "enabled": True,
    }).json()
    tid = created["id"]
    assert created["backup_policy_id"] == pol["id"]

    raw_list = auth_client.get("/api/tasks").json()
    assert isinstance(raw_list, list)
    assert any(t["id"] == tid for t in raw_list)

    single = auth_client.get(f"/api/tasks/{tid}").json()
    assert single["name"] == "Backup Nocturno"

    # Ejecutar tarea de respaldo ligada a la política y comprobar respaldo generado
    run_res = auth_client.post(f"/api/tasks/{tid}/run").json()
    assert run_res["success"] is True
    bks = auth_client.get("/api/backups/list").json()
    assert len(bks) >= 1
    newest = settings.backups_dir / bks[0]["filename"]
    with tarfile.open(str(newest), "r:") as tar:
        names = tar.getnames()
        assert any("keep.ini" in n for n in names)
        assert not any("skip.bin" in n for n in names)

    # Editar tarea con PUT /api/tasks/{id}
    updated = auth_client.put(f"/api/tasks/{tid}", json={
        "name": "Check Updates Diario",
        "action": "check_updates",
        "schedule_type": "interval",
        "interval_value": 12,
        "interval_unit": "hours",
    }).json()
    assert updated["name"] == "Check Updates Diario"
    assert updated["action"] == "check_updates"

    # Toggle de tarea
    toggled = auth_client.post(f"/api/tasks/{tid}/toggle").json()
    assert toggled["success"] is True
    assert toggled["enabled"] is False
    assert toggled["task"]["enabled"] is False

    assert auth_client.delete(f"/api/tasks/{tid}").json()["success"] is True
    assert auth_client.get(f"/api/tasks/{tid}").status_code == 404


def test_dockraft_multichannel_webhooks_config_and_tests(auth_client):
    save_res = auth_client.post("/api/webhooks/config", json={
        "language": "en",
        "discord": {
            "enabled": True,
            "webhook_url": "https://discord.com/api/webhooks/99/xyz",
        },
        "telegram": {
            "enabled": True,
            "bot_token": "999:TG_SECRET",
            "chat_id": "-100888",
        },
        "email": {
            "enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "panel@example.com",
            "smtp_password": "MAIL_SECRET_PASSWORD",
            "smtp_use_tls": True,
            "from_email": "panel@example.com",
            "to_emails": "admin@example.com",
        },
        "events": {
            "server_start": True,
            "server_stop": False,
            "player_join": True,
            "player_leave": False,
        },
    })
    assert save_res.status_code == 200
    saved = save_res.json()["config"]
    assert saved["language"] == "en"
    assert saved["discord"]["enabled"] is True
    assert saved["telegram"]["bot_token"] == "••••••••••••"
    assert saved["email"]["smtp_password"] == "••••••••••••"
    assert saved["events"]["server_stop"] is False
    assert saved["events"]["player_join"] is True

    # Preservar secretos cuando llegan enmascarados
    auth_client.post("/api/webhooks/config", json={
        "telegram": {"enabled": True, "bot_token": "••••••••••••"},
        "email": {"enabled": True, "smtp_password": "••••••••••••"},
    })
    assert settings.runtime_config["telegram_bot_token"] == "999:TG_SECRET"
    assert settings.runtime_config["webhook_email"]["smtp_password"] == "MAIL_SECRET_PASSWORD"

    # Sincronización con eventos en notify()
    assert webhook_manager._is_event_enabled("shutdown", settings.runtime_config["discord_events"]) is False
    assert webhook_manager._is_event_enabled("players_join", settings.runtime_config["discord_events"]) is True
    assert webhook_manager._is_event_enabled("players_leave", settings.runtime_config["discord_events"]) is False

    # Probar canales individuales Discord, Telegram y Email
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    with patch("app.core.webhook_manager.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_http_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        assert auth_client.post("/api/webhooks/test/discord").json()["status"] == "success"
        assert auth_client.post("/api/webhooks/test/telegram").json()["status"] == "success"
        assert mock_client.post.await_count == 2

    with patch("app.core.webhook_manager.smtplib.SMTP") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value = mock_smtp
        mail_test = auth_client.post("/api/webhooks/test/email")
        assert mail_test.status_code == 200
        assert mail_test.json()["status"] == "success"
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("panel@example.com", "MAIL_SECRET_PASSWORD")
        mock_smtp.sendmail.assert_called_once()

    bad_ch = auth_client.post("/api/webhooks/test/unknown")
    assert bad_ch.status_code == 400


def test_gog_nosteam_disables_mods(auth_client):
    try:
        # Cargar primero un mod en modo Steam
        assert auth_client.post("/api/mods", json={"workshop_items": "2729973596", "mods_names_raw": "RavenCreek"}).json()["success"] is True

        # Instalar / guardar en modo GOG (-nosteam) ignorando y limpiando mods
        with patch.object(process_manager, "is_installed", return_value=True), \
             patch.object(process_manager, "start_server", new=AsyncMock(return_value=True)):
            inst = auth_client.post("/api/server/install", json={
                "use_steam": False,
                "server_name": settings.server_name,
                "admin_password": "pw",
                "mod_ids": "2687618628",
            }).json()
        assert inst["success"] is True
        assert settings.use_steam is False

        mods_state = auth_client.get("/api/mods").json()
        assert mods_state["steam_mode"] is False
        assert mods_state["workshop_items"] == []
        assert mods_state["mod_ids"] == []

        assert auth_client.post("/api/mods", json={"workshop_items": "2687618628"}).status_code == 400
        assert auth_client.post("/api/mods/resolve", json={"workshop_ids": ["2687618628"]}).status_code == 400
        assert auth_client.post("/api/mods/collection", json={"collection": "999001"}).status_code == 400

        # Volver a Steam vía Ajustes reactiva la gestión de mods
        sw = auth_client.post("/api/settings", json={"panel": {"use_steam": True}}).json()
        assert sw["success"] is True
        assert auth_client.get("/api/mods").json()["steam_mode"] is True
        assert auth_client.post("/api/mods", json={"workshop_items": "2687618628"}).status_code == 200
    finally:
        settings.save_runtime_config({"use_steam": True})
