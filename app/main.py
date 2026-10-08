import os
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Depends, Request,
    Response, Form, status, HTTPException
)
from fastapi.responses import RedirectResponse, HTMLResponse, Response as FastAPIResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from app.config import settings, BASE_DIR
from app.core.security import (
    create_session_token, verify_session_token, verify_admin_credentials,
    is_authenticated, require_auth, SESSION_COOKIE_NAME
)
from app.core.process_manager import process_manager
from app.core.metrics_manager import metrics_manager
from app.core.pz_settings_manager import pz_settings_manager
from app.core.backup_manager import backup_manager
from app.core.task_scheduler import task_scheduler
from app.core.webhook_manager import webhook_manager
from app.core.activity_manager import activity_manager
from app.core.player_manager import player_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print("[PZ-Server] ============================================================")
    print(f"[PZ-Server] Panel web activo en http://0.0.0.0:{settings.panel_port}")
    print(f"[PZ-Server] Usuario del panel: '{settings.admin_user}'")
    print(f"[PZ-Server] Contraseña del panel: '{settings.admin_password}'")
    print(f"[PZ-Server] Modo: {'STEAM' if settings.use_steam else 'NO-STEAM (GOG/nosteam)'}")
    print("[PZ-Server] ============================================================")
    metrics_manager.start()
    task_scheduler.start_loop()
    await webhook_manager.notify("starting", "El panel PZ Server Manager ha arrancado.")

    # Auto-inicio SOLO si la configuración inicial está completada y autostart_server está activado
    if settings.autostart_server and settings.is_setup_done and process_manager.is_installed():
        async def _autostart():
            await asyncio.sleep(2)
            if process_manager.get_status() == "OFFLINE":
                await process_manager.broadcast_log("[PZ-Server] Inicio automático activado al arrancar el panel.")
                await webhook_manager.notify("starting")
                await process_manager.start_server()
                await webhook_manager.notify("start")
        asyncio.create_task(_autostart())
    elif not settings.is_setup_done:
        print("[PZ-Server] [SETUP PENDIENTE] Esperando configuración inicial en el panel web (pestaña Setup).")

    yield

    task_scheduler.stop_loop()
    metrics_manager.stop()
    if process_manager.process and process_manager.process.returncode is None:
        try:
            print("[PZ-Server] [SEGURIDAD] Contenedor deteniéndose. Ejecutando guardado seguro...")
            await process_manager.stop_server(grace_seconds=20)
        except Exception as e:
            print(f"[PZ-Server] Error durante guardado seguro al apagar: {e}")


app = FastAPI(
    title="Project Zomboid Server Manager",
    description="Panel Web para Servidor Dedicado de Project Zomboid (Steam / No-Steam)",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

web_dir = BASE_DIR / "web"
templates = Jinja2Templates(directory=str(web_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")


# --- Modelos Pydantic ----------------------------------------------------------
class CommandRequest(BaseModel):
    command: str

class BroadcastRequest(BaseModel):
    message: str


def _augment_metrics(metrics: dict, include_players: bool = False) -> dict:
    """Compatibiliza el diccionario de métricas con el frontend portado de ARK."""
    m = dict(metrics or {})
    m.setdefault("pz_ram_gb", m.get("ark_ram_gb", 0.0))
    m.setdefault("ark_ram_gb", m.get("pz_ram_gb", 0.0))
    if include_players:
        m["players_online"] = 0  # Fase 3: player_manager por RCON/consola
        m["max_players"] = settings.max_players
        m["session_name"] = settings.server_name
        m["world"] = settings.world_label
    return m


def _placeholder_success(area: str):
    return {"success": False, "error": f"'{area}' llegará en fases posteriores del panel PZ."}


# --- Páginas HTML ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    metrics = _augment_metrics(metrics_manager.get_current_metrics(), include_players=True)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "server_name": settings.server_name,
            "session_name": settings.server_name,
            "world": settings.world_label,
            "status": process_manager.get_status(),
            "is_installed": process_manager.is_installed(),
            "is_setup_done": settings.is_setup_done,
            "steam_mode": settings.use_steam,
            "metrics": metrics,
            "max_players": settings.max_players,
            "timezone": settings.timezone,
            "server_port": settings.server_port,
            "direct_port": settings.direct_port,
            "panel_version": app.version,
        },
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.post("/login")
async def login_post(request: Request, response: Response,
                     username: str = Form(...), password: str = Form(...)):
    if verify_admin_credentials(username, password):
        token = create_session_token(username)
        redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        redirect.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=(request.url.scheme == "https"),
            samesite="lax",
            max_age=3600,
        )
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Usuario o contraseña incorrectos. Revisa PANEL_USER / PANEL_PASSWORD "
                          "(se leen del archivo .env a través de docker-compose.yml)."},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )

@app.get("/logout")
async def logout():
    res = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    res.delete_cookie(SESSION_COOKIE_NAME)
    return res

@app.get("/health")
async def health_check():
    """Healthcheck endpoint para Docker."""
    return {
        "status": "ok",
        "server_status": process_manager.get_status(),
        "installed": process_manager.is_installed(),
        "mode": "steam" if settings.use_steam else "nosteam",
    }


# --- WebSocket de Consola en Tiempo Real ---------------------------------------
WS_HEARTBEAT_TOKEN = "\u200b"
WS_HEARTBEAT_IDLE_SECONDS = 25

@app.websocket("/ws/console")
async def websocket_console(websocket: WebSocket):
    if settings.admin_password:
        token = websocket.cookies.get(SESSION_COOKIE_NAME)
        if not token or not verify_session_token(token):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    await websocket.accept()
    process_manager.connected_websockets.add(websocket)
    for line in list(process_manager.log_buffer):
        try:
            await websocket.send_text(line)
        except Exception:
            break
    stop = asyncio.Event()

    async def _heartbeat():
        while not stop.is_set():
            try:
                await asyncio.sleep(WS_HEARTBEAT_IDLE_SECONDS)
                if stop.is_set():
                    return
                await websocket.send_text(WS_HEARTBEAT_TOKEN)
            except Exception:
                stop.set()
                return

    hb = asyncio.create_task(_heartbeat())
    try:
        while not stop.is_set():
            try:
                cmd = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                break
            if stop.is_set() or not cmd:
                break
            try:
                await process_manager.send_command(cmd)
            except Exception:
                break
    finally:
        stop.set()
        hb.cancel()
        process_manager.connected_websockets.discard(websocket)


# --- API: estado y control -------------------------------------------------------
@app.get("/api/status", dependencies=[Depends(require_auth)])
async def api_status():
    metrics = _augment_metrics(metrics_manager.get_current_metrics(), include_players=True)
    return {
        "status": process_manager.get_status(),
        "is_installed": process_manager.is_installed(),
        "is_setup_done": settings.is_setup_done,
        "simulation": process_manager._is_simulation,
        "server_name": settings.server_name,
        "session_name": settings.server_name,
        "world": settings.world_label,
        "steam_mode": settings.use_steam,
        "players_online": metrics.get("players_online", 0),
        "max_players": settings.max_players,
        "metrics": metrics,
    }

@app.get("/api/metrics", dependencies=[Depends(require_auth)])
async def api_metrics():
    curr = _augment_metrics(metrics_manager.get_current_metrics(), include_players=True)
    hist = metrics_manager.get_history()
    return {
        "current": curr,
        "history": hist,
    }

@app.get("/api/server/config", dependencies=[Depends(require_auth)])
async def api_server_config():
    return {
        "server_name": settings.server_name,
        "steam_mode": settings.use_steam,
        "admin_username": settings.admin_username,
        "memory_min": settings.memory_min,
        "memory_max": settings.memory_max,
        "server_dir": str(settings.server_dir),
        "data_dir": str(settings.data_dir),
        "installed": process_manager.is_installed(),
    }

@app.post("/api/server/install", dependencies=[Depends(require_auth)])
async def api_server_install(payload: Optional[dict] = None):
    """Guarda la configuración inicial del asistente (Setup) e instala/inicia el servidor."""
    p = payload or {}
    if p:
        settings.save_wizard(p)
        mod_ids = p.get("mod_ids", "")
        if mod_ids:
            pz_settings_manager.save_mods(mod_ids)
        if "pvp" in p:
            pz_settings_manager.save_general({"PVP": "true" if p["pvp"] else "false"})

    installed = process_manager.is_installed()
    if installed:
        await process_manager.broadcast_log(
            "[PZ-Server] Configuración inicial guardada correctamente. Iniciando servidor..."
        )
        asyncio.create_task(process_manager.start_server())
        return {
            "success": True,
            "message": "Configuración inicial guardada. Iniciando servidor de Project Zomboid...",
        }

    # Descarga automática de binarios (anónima) — aplica a Steam y No-Steam.
    await process_manager.broadcast_log(
        "[PZ-Server] Setup guardado. Descargando binarios con SteamCMD (AppID 380870) "
        "en modo " + ("STEAM" if settings.use_steam else "NO-STEAM (-nosteam)") + "..."
    )
    asyncio.create_task(process_manager.install_server())
    return {
        "success": True,
        "message": "Setup guardado. Descarga de binarios iniciada automáticamente.",
    }

@app.post("/api/server/start", dependencies=[Depends(require_auth)])
async def api_server_start():
    if not settings.is_setup_done:
        return {
            "success": False,
            "error": "El servidor requiere configuración inicial en la pestaña Setup antes de iniciar.",
            "is_setup_done": False,
            "status": "OFFLINE",
        }
    ok = await process_manager.start_server()
    return {"success": ok, "status": process_manager.get_status()}

@app.post("/api/server/stop", dependencies=[Depends(require_auth)])
async def api_server_stop():
    ok = await process_manager.stop_server()
    return {"success": ok, "status": process_manager.get_status()}

@app.post("/api/server/restart", dependencies=[Depends(require_auth)])
async def api_server_restart():
    ok = await process_manager.restart_server()
    return {"success": ok, "status": process_manager.get_status()}

@app.post("/api/server/command", dependencies=[Depends(require_auth)])
async def api_server_command(req: CommandRequest):
    resp = await process_manager.send_command(req.command)
    return {"success": True, "response": resp}

@app.post("/api/server/save", dependencies=[Depends(require_auth)])
async def api_server_save():
    resp = await process_manager.save_world()
    return {"success": True, "response": resp}

@app.post("/api/server/broadcast", dependencies=[Depends(require_auth)])
async def api_server_broadcast(req: BroadcastRequest):
    resp = await process_manager.broadcast(req.message)
    return {"success": True, "response": resp}

@app.get("/api/server/logs", dependencies=[Depends(require_auth)])
async def api_server_logs():
    return {"logs": list(process_manager.log_buffer)}

@app.get("/api/server/logs/download", dependencies=[Depends(require_auth)])
async def api_download_logs():
    content = "\n".join(process_manager.log_buffer) if process_manager.log_buffer else "Sin logs todavía."
    return FastAPIResponse(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=pz_console.log"},
    )


# ==============================================================================
# Endpoints reales (Fases 3-5): jugadores, respaldos, tareas, ajustes, mods,
# webhooks y actividad.
# ==============================================================================

# ----------------------------- Jugadores -----------------------------
@app.get("/api/players", dependencies=[Depends(require_auth)])
async def api_players():
    return await player_manager.get_players()

@app.post("/api/players/kick", dependencies=[Depends(require_auth)])
async def api_player_kick(payload: Optional[dict] = None):
    name = ((payload or {}).get("username")) or ((payload or {}).get("name"))
    if not name:
        return {"success": False, "error": "Usuario requerido."}
    resp = await player_manager.kick(name)
    return {"success": True, "response": resp}

@app.post("/api/players/ban", dependencies=[Depends(require_auth)])
async def api_player_ban(payload: Optional[dict] = None):
    name = ((payload or {}).get("username")) or ((payload or {}).get("name"))
    if not name:
        return {"success": False, "error": "Usuario requerido."}
    resp = await player_manager.ban(name)
    return {"success": True, "response": resp}

@app.post("/api/players/unban", dependencies=[Depends(require_auth)])
async def api_player_unban(payload: Optional[dict] = None):
    name = ((payload or {}).get("username")) or ((payload or {}).get("name"))
    if not name:
        return {"success": False, "error": "Usuario requerido."}
    resp = await player_manager.unban(name)
    return {"success": True, "response": resp}

@app.post("/api/players/message", dependencies=[Depends(require_auth)])
async def api_player_message(payload: Optional[dict] = None):
    name = ((payload or {}).get("username")) or ((payload or {}).get("name"))
    msg = (payload or {}).get("message", "")
    if not name or not msg:
        return {"success": False, "error": "Usuario y mensaje requeridos."}
    resp = await player_manager.message_player(name, msg)
    return {"success": True, "response": resp}

# ----------------------------- Respaldos -----------------------------
@app.get("/api/backups", dependencies=[Depends(require_auth)])
async def api_backups_list():
    return {"backups": backup_manager.list_backups()}

@app.post("/api/backups/create", dependencies=[Depends(require_auth)])
async def api_backup_create(payload: Optional[dict] = None):
    name = (payload or {}).get("name")
    res = await backup_manager.create_backup(name)
    return res

@app.post("/api/backups/restore", dependencies=[Depends(require_auth)])
async def api_backup_restore(payload: Optional[dict] = None):
    filename = (payload or {}).get("filename", "")
    res = await backup_manager.restore_backup(filename)
    return res

@app.post("/api/backups/delete", dependencies=[Depends(require_auth)])
async def api_backup_delete(payload: Optional[dict] = None):
    filename = (payload or {}).get("filename", "")
    ok = backup_manager.delete_backup(filename)
    if ok:
        activity_manager.log("Backups", f"Copia eliminada: {filename}")
    return {"success": ok}

@app.get("/api/backups/download/{filename}", dependencies=[Depends(require_auth)])
async def api_backup_download(filename: str):
    path = backup_manager.get_backup_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path=str(path), filename=filename, media_type="application/gzip")

# ----------------------------- Mods -----------------------------
@app.get("/api/mods", dependencies=[Depends(require_auth)])
async def api_mods_get():
    return pz_settings_manager.get_mods()

@app.post("/api/mods", dependencies=[Depends(require_auth)])
async def api_mods_save(payload: Optional[dict] = None):
    ids = (payload or {}).get("mod_ids", "")
    res = pz_settings_manager.save_mods(ids)
    if res.get("success"):
        await process_manager.broadcast_log(
            f"[PZ-Server] Mods actualizados en .ini ({res['count']}). Reinicia el server para aplicarlos."
        )
    return res

@app.post("/api/mods/update", dependencies=[Depends(require_auth)])
async def api_mods_update():
    if settings.use_steam:
        await process_manager.broadcast_log(
            "[PZ-Server] En modo Steam los mods se descargan/actualizan en el arranque (SteamCMD)."
        )
    else:
        await process_manager.broadcast_log(
            "[PZ-Server] Modo No-Steam: instala los mods manualmente en la carpeta del server."
        )
    return {"success": True, "message": "Los mods se gestionan en el arranque del server (Steam) o manualmente (No-Steam)."}

# ----------------------------- Tareas / Scheduler -----------------------------
@app.get("/api/tasks/config", dependencies=[Depends(require_auth)])
async def api_tasks_config_get():
    return task_scheduler.get_config()

@app.post("/api/tasks/config", dependencies=[Depends(require_auth)])
async def api_tasks_config_save(payload: Optional[dict] = None):
    task_scheduler.save_config(payload or {})
    activity_manager.log("Tareas", "Configuración de tareas guardada")
    return {"success": True}

@app.get("/api/tasks/status", dependencies=[Depends(require_auth)])
async def api_tasks_status():
    return task_scheduler.get_status()

@app.post("/api/server/restart_safe", dependencies=[Depends(require_auth)])
async def api_server_restart_safe(payload: Optional[dict] = None):
    minutes = int((payload or {}).get("minutes", 5) or 5)
    await task_scheduler.trigger_safe_restart(minutes)
    await process_manager.broadcast_log(f"[PZ-Server] Reinicio seguro programado en {minutes} minutos.")
    return {"success": True, "message": f"Reinicio seguro programado en {minutes} minutos."}

# ----------------------------- Ajustes (.ini / Sandbox / Raw) -----------------------------
@app.get("/api/settings", dependencies=[Depends(require_auth)])
async def api_settings_get():
    return pz_settings_manager.get_all_settings()

def _normalize_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {"server": {}, "sandbox": {}, "panel": {}}

    if "server" in payload or "sandbox" in payload or "panel" in payload:
        return {
            "server": payload.get("server") or {},
            "sandbox": payload.get("sandbox") or {},
            "panel": payload.get("panel") or {},
        }

    raw = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
    server = {}
    sandbox = {}
    panel = {}

    for k, v in raw.items():
        sk = str(k)
        if sk.startswith("sandbox_"):
            sandbox[sk[len("sandbox_"):]] = v
        elif sk.startswith("panel_") or sk in ("memory_min", "memory_max", "use_steam", "autostart_server", "update_on_start", "branch", "additional_args"):
            clean_key = sk[len("panel_"):] if sk.startswith("panel_") else sk
            panel[clean_key] = v
        elif sk in ("mode", "cfg_mode"):
            server["PVP"] = "true" if str(v).lower() == "pvp" else "false"
        else:
            server[sk] = v

    return {"server": server, "sandbox": sandbox, "panel": panel}

@app.post("/api/settings", dependencies=[Depends(require_auth)])
async def api_settings_save(payload: Optional[dict] = None):
    return pz_settings_manager.save_settings(_normalize_settings(payload or {}))

@app.post("/api/settings/raw", dependencies=[Depends(require_auth)])
async def api_settings_raw_save(payload: Optional[dict] = None):
    p = payload or {}
    file_type = p.get("type", "ini")
    content = p.get("content", "")
    if file_type == "sandbox":
        ok = pz_settings_manager.save_raw_sandbox(content)
    else:
        ok = pz_settings_manager.save_raw_ini(content)
    return {"success": ok}

@app.post("/api/server/reloadoptions", dependencies=[Depends(require_auth)])
async def api_server_reloadoptions():
    resp = await process_manager.send_command("reloadoptions")
    return {"success": True, "response": resp}

# ----------------------------- Webhooks Discord -----------------------------
DEFAULT_EVENTS = {
    "start": True, "starting": True, "shutdown": True,
    "save": True, "backup": True, "restart": True, "players": False,
}

@app.get("/api/webhooks", dependencies=[Depends(require_auth)])
async def api_webhooks_get():
    cfg = settings.runtime_config
    return {
        "url": cfg.get("discord_webhook_url", ""),
        "language": cfg.get("discord_language", "es"),
        "events": cfg.get("discord_events", DEFAULT_EVENTS),
    }

@app.post("/api/webhooks", dependencies=[Depends(require_auth)])
async def api_webhooks_save(payload: Optional[dict] = None):
    p = payload or {}
    settings.save_runtime_config({
        "discord_webhook_url": str(p.get("url", "")).strip(),
        "discord_language": str(p.get("language", "es")),
        "discord_events": p.get("events") or DEFAULT_EVENTS,
    })
    activity_manager.log("Webhooks", "Configuración de Webhook guardada")
    return {"success": True}

@app.post("/api/webhooks/test", dependencies=[Depends(require_auth)])
async def api_webhooks_test():
    ok = await webhook_manager.test()
    if ok:
        activity_manager.log("Webhooks", "Notificación de prueba enviada")
    return {"success": ok, "error": None if ok else "No se pudo entregar (revisa la URL)."}

# ----------------------------- Actividad -----------------------------
@app.get("/api/activity", dependencies=[Depends(require_auth)])
async def api_activity():
    return {"activities": activity_manager.get_recent()}

@app.get("/api/activity/download", dependencies=[Depends(require_auth)])
async def api_activity_download():
    import json as _json
    content = _json.dumps(activity_manager.get_recent(), indent=2, ensure_ascii=False)
    return FastAPIResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=actividad_pz.json"},
    )
