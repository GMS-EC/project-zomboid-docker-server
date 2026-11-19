import time
import shutil
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Depends, Request,
    Response, Form, status, HTTPException, Query
)
from fastapi.responses import RedirectResponse, HTMLResponse, Response as FastAPIResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from app.config import settings, BASE_DIR
from app.core.security import (
    create_session_token, verify_session_token, verify_admin_credentials,
    is_authenticated, require_auth, revoke_token, extract_token_from_request,
    login_limiter, get_client_ip, SESSION_COOKIE_NAME
)
from app.core.process_manager import process_manager
from app.core.metrics_manager import metrics_manager
from app.core.pz_settings_manager import pz_settings_manager
from app.core.backup_manager import backup_manager
from app.core.task_scheduler import task_scheduler
from app.core.webhook_manager import webhook_manager
from app.core.activity_manager import activity_manager
from app.core.player_manager import player_manager
from app.core.diagnostic_manager import diagnostic_manager
from app.routers import files as files_router


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Cabeceras de seguridad HTTP inspiradas en Dockraft."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://*.akamaihd.net https://*.steamstatic.com; "
            "connect-src 'self' ws: wss:;"
        )
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print("[PZ-Server] ============================================================")
    print(f"[PZ-Server] Panel web activo en http://0.0.0.0:{settings.panel_port}")
    print(f"[PZ-Server] Usuario del panel: '{settings.admin_user}'")
    print(f"[PZ-Server] Modo: {'STEAM' if settings.use_steam else 'NO-STEAM (GOG/nosteam)'}")
    print("[PZ-Server] ============================================================")
    metrics_manager.start()
    task_scheduler.start_loop()

    if settings.autostart_server and settings.is_setup_done and process_manager.is_installed():
        async def _autostart():
            await asyncio.sleep(2)
            if process_manager.get_status() == "OFFLINE":
                await process_manager.broadcast_log("[PZ-Server] Inicio automático activado al arrancar el panel.")
                await process_manager.start_server()
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
    version="0.3.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(files_router.router)

web_dir = BASE_DIR / "web"
templates = Jinja2Templates(directory=str(web_dir / "templates"))
START_TIME_TOKEN = str(int(time.time()))
templates.env.globals["asset_v"] = START_TIME_TOKEN
templates.env.globals["panel_version"] = app.version
if (web_dir / "static").exists():
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")


# --- Modelos Pydantic ----------------------------------------------------------
class CommandRequest(BaseModel):
    command: str


class BroadcastRequest(BaseModel):
    message: str


def _augment_metrics(metrics: dict, include_players: bool = False) -> dict:
    """Garantiza la compatibilidad de métricas para el frontend con datos reales en vivo."""
    m = dict(metrics or {})
    m.setdefault("pz_ram_gb", m.get("ark_ram_gb", 0.0))
    m.setdefault("ark_ram_gb", m.get("pz_ram_gb", 0.0))
    if include_players:
        m["players_online"] = len(process_manager.online_players)
        m["max_players"] = settings.max_players
        m["session_name"] = settings.server_name
        m["world"] = settings.world_label
        m["steam_mode"] = settings.use_steam
    if process_manager.status == "INSTALLING":
        m["install_progress"] = process_manager.install_progress
    return m


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
            "memory_min": settings.memory_min,
            "memory_max": settings.memory_max,
            "branch": settings.branch,
            "panel_version": app.version,
            "asset_v": START_TIME_TOKEN,
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    client_ip = get_client_ip(request)
    is_locked, remaining = login_limiter.is_locked(client_ip)
    err = f"Demasiados intentos fallidos. Espera {remaining}s antes de volver a intentar." if is_locked else None
    return templates.TemplateResponse(request=request, name="login.html", context={"error": err})


@app.post("/login")
async def login_post(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
):
    client_ip = get_client_ip(request)
    is_locked, remaining = login_limiter.is_locked(client_ip)
    if is_locked:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": f"IP bloqueada temporalmente por seguridad. Espera {remaining}s."},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    if verify_admin_credentials(username, password):
        login_limiter.record_success(client_ip)
        token = create_session_token(username.strip())
        activity_manager.log(
            "Seguridad",
            f"Inicio de sesión exitoso (IP: {client_ip})",
            user=username.strip(),
            action="login_success",
        )
        redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        redirect.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=(request.url.scheme == "https" or settings.https_enabled),
            samesite="lax",
            max_age=3600,
        )
        return redirect

    rem_attempts, cooldown = login_limiter.record_failure(client_ip)
    activity_manager.log(
        "Seguridad",
        f"Intento fallido para '{username.strip()}' (IP: {client_ip})",
        user=username.strip() or "desconocido",
        action="login_failed",
        status="warning",
    )
    msg = (
        f"Demasiados intentos fallidos. Bloqueado por {cooldown}s."
        if cooldown > 0
        else f"Usuario o contraseña incorrectos. Intentos restantes: {rem_attempts}."
    )
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": msg},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@app.get("/logout")
async def logout(request: Request):
    token = extract_token_from_request(request)
    revoke_token(token)
    activity_manager.log("Seguridad", "Sesión cerrada por el administrador", action="logout")
    res = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    res.delete_cookie(SESSION_COOKIE_NAME)
    return res


@app.get("/health")
async def health_check():
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
                activity_manager.log("Consola", cmd.strip(), action="command_executed")
                await process_manager.send_command(cmd)
            except Exception:
                break
    finally:
        stop.set()
        hb.cancel()
        process_manager.connected_websockets.discard(websocket)


# --- API: estado, métricas y diagnóstico ---------------------------------------
@app.get("/api/status", dependencies=[Depends(require_auth)])
async def api_status():
    metrics = _augment_metrics(metrics_manager.get_current_metrics(), include_players=True)
    return {
        "status": process_manager.get_status(),
        "is_installed": process_manager.is_installed(),
        "is_setup_done": settings.is_setup_done,
        "simulation": process_manager._is_simulation,
        "install_progress": process_manager.install_progress,
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
    return {"current": curr, "history": hist}


@app.get("/api/diagnostics", dependencies=[Depends(require_auth)])
async def api_diagnostics():
    return diagnostic_manager.analyze_diagnostics()


@app.post("/api/server/install", dependencies=[Depends(require_auth)])
async def api_server_install(payload: Optional[dict] = None):
    """Guarda la configuración inicial del asistente (Setup) e instala/inicia el servidor."""
    p = payload or {}
    if p:
        settings.save_wizard(p)
        mod_ids = str(p.get("mod_ids", "") or "").strip()
        if settings.use_steam and mod_ids:
            # Si el usuario ingresó Workshop IDs numéricos en el wizard, resolver Mod IDs reales
            tokens = [t.strip() for t in mod_ids.replace(";", ",").split(",") if t.strip()]
            numeric_ids = [t for t in tokens if t.isdigit()]
            text_ids = [t for t in tokens if not t.isdigit()]
            if numeric_ids:
                pz_settings_manager.save_mods(";".join(numeric_ids), ";".join(text_ids) if text_ids else None)
                asyncio.create_task(pz_settings_manager.resolve_workshop_items(numeric_ids, sync_to_ini=True))
            else:
                pz_settings_manager.save_mods("", ";".join(text_ids))
        ini_updates = {}
        if not settings.use_steam:
            ini_updates["WorkshopItems"] = ""
            ini_updates["Mods"] = ""
        if "pvp" in p:
            ini_updates["PVP"] = "true" if settings._rt_bool(p["pvp"], False) else "false"
        if "server_password" in p:
            ini_updates["Password"] = str(p.get("server_password", "") or "").strip()
        if "admin_password" in p and str(p.get("admin_password", "")).strip():
            ini_updates["AdminPassword"] = str(p.get("admin_password", "")).strip()
        if "max_players" in p and p.get("max_players") not in (None, ""):
            ini_updates["MaxPlayers"] = str(settings.max_players)
        if ini_updates:
            pz_settings_manager.set_ini_values(ini_updates)
        activity_manager.log("Servidor", f"Setup guardado para '{settings.server_name}'", action="setup_saved")

    installed = process_manager.is_installed()
    force_update = bool(p.get("force_update", False))
    if installed and not force_update:
        await process_manager.broadcast_log(
            "[PZ-Server] Configuración inicial guardada correctamente. Iniciando servidor..."
        )
        asyncio.create_task(process_manager.start_server())
        return {
            "success": True,
            "message": "Configuración inicial guardada. Iniciando servidor de Project Zomboid...",
        }

    await process_manager.broadcast_log(
        "[PZ-Server] Setup guardado. Descargando binarios (AppID 380870) en modo "
        + ("STEAM" if settings.use_steam else "NO-STEAM (-nosteam)") + "..."
    )
    asyncio.create_task(process_manager.install_server(auto_start=True))
    return {
        "success": True,
        "installing": True,
        "message": "Setup guardado. Descargando servidor y arrancará automáticamente al finalizar.",
    }


@app.post("/api/server/update", dependencies=[Depends(require_auth)])
async def api_server_update():
    """Fuerza actualización/validación de binarios del servidor PZ."""
    if process_manager.get_status() in ("RUNNING", "STARTING", "INSTALLING"):
        return {"success": False, "error": "Detén el servidor antes de actualizar binarios."}
    activity_manager.log("Actualización", "Actualización de binarios iniciada (AppID 380870)", action="server_update")
    asyncio.create_task(process_manager.install_server())
    return {"success": True, "message": "Descarga/validación de binarios iniciada. Revisa la consola."}


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
    if ok:
        activity_manager.log("Servidor", f"Inicio del servidor ({settings.server_name})", action="server_start")
    return {"success": ok, "status": process_manager.get_status()}


@app.post("/api/server/stop", dependencies=[Depends(require_auth)])
async def api_server_stop():
    ok = await process_manager.stop_server()
    if ok:
        activity_manager.log("Servidor", "Servidor detenido de forma segura", action="server_stop")
    return {"success": ok, "status": process_manager.get_status()}


@app.post("/api/server/restart", dependencies=[Depends(require_auth)])
async def api_server_restart():
    ok = await process_manager.restart_server()
    activity_manager.log("Servidor", "Reinicio manual del servidor", action="server_restart")
    return {"success": ok, "status": process_manager.get_status()}


@app.post("/api/server/command", dependencies=[Depends(require_auth)])
async def api_server_command(req: CommandRequest):
    activity_manager.log("Consola", req.command.strip(), action="command_executed")
    resp = await process_manager.send_command(req.command)
    return {"success": True, "response": resp}


@app.post("/api/server/broadcast", dependencies=[Depends(require_auth)])
async def api_server_broadcast(req: BroadcastRequest):
    activity_manager.log("Consola", f'servermsg "{req.message}"', action="broadcast")
    resp = await process_manager.broadcast(req.message)
    return {"success": True, "response": resp}


@app.get("/api/server/logs/download", dependencies=[Depends(require_auth)])
async def api_download_logs():
    content = "\n".join(process_manager.log_buffer) if process_manager.log_buffer else "Sin logs todavía."
    return FastAPIResponse(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=pz_console.log"},
    )


# ----------------------------- Jugadores -----------------------------
@app.get("/api/players", dependencies=[Depends(require_auth)])
async def api_players():
    return await player_manager.get_players()


@app.post("/api/players/refresh", dependencies=[Depends(require_auth)])
async def api_players_refresh():
    resp = await player_manager.refresh_online()
    return {"success": True, "response": resp}


@app.post("/api/players/kick", dependencies=[Depends(require_auth)])
async def api_player_kick(payload: Optional[dict] = None):
    p = payload or {}
    name = p.get("username") or p.get("name")
    sid = p.get("steam_id")
    reason = p.get("reason", "")
    try:
        resp = await player_manager.kick(username=name, steam_id=sid, reason=reason)
        return {"success": True, "response": resp}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@app.post("/api/players/ban", dependencies=[Depends(require_auth)])
async def api_player_ban(payload: Optional[dict] = None):
    p = payload or {}
    name = p.get("username") or p.get("name")
    sid = p.get("steam_id")
    reason = p.get("reason", "")
    try:
        resp = await player_manager.ban(username=name, steam_id=sid, reason=reason)
        return {"success": True, "response": resp}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@app.post("/api/players/unban", dependencies=[Depends(require_auth)])
async def api_player_unban(payload: Optional[dict] = None):
    p = payload or {}
    name = p.get("username") or p.get("name")
    sid = p.get("steam_id")
    try:
        resp = await player_manager.unban(username=name, steam_id=sid)
        return {"success": True, "response": resp}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@app.post("/api/players/message", dependencies=[Depends(require_auth)])
async def api_player_message(payload: Optional[dict] = None):
    p = payload or {}
    name = p.get("username") or p.get("name")
    sid = p.get("steam_id")
    msg = p.get("message", "")
    try:
        resp = await player_manager.message_player(username=name, message=msg, steam_id=sid)
        return {"success": True, "response": resp}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@app.post("/api/players/role", dependencies=[Depends(require_auth)])
async def api_player_role(payload: Optional[dict] = None):
    p = payload or {}
    name = p.get("username") or p.get("name") or ""
    level = p.get("access_level") or p.get("level") or "none"
    return await player_manager.set_access_level(name, level)


@app.post("/api/players/add", dependencies=[Depends(require_auth)])
async def api_player_add(payload: Optional[dict] = None):
    p = payload or {}
    name = p.get("username") or p.get("name") or ""
    password = p.get("password") or ""
    level = p.get("access_level") or "none"
    return await player_manager.add_user(name, password, level)


@app.post("/api/players/action", dependencies=[Depends(require_auth)])
async def api_player_action(payload: Optional[dict] = None):
    p = payload or {}
    name = p.get("username") or p.get("name") or ""
    action = p.get("action") or ""
    arg1 = p.get("arg1") or ""
    arg2 = p.get("arg2") or ""
    return await player_manager.admin_action(name, action, arg1, arg2)


@app.post("/api/server/wipe-world", dependencies=[Depends(require_auth)])
async def api_server_wipe_world():
    """Realiza copia de seguridad previa y reinicia solo la carpeta Saves/Multiplayer/<SERVER_NAME>."""
    if process_manager.get_status() in ("RUNNING", "STARTING"):
        await process_manager.stop_server()

    world_dir = settings.data_dir / "Saves" / "Multiplayer" / settings.server_name
    bk = await backup_manager.create_backup("pre_wipe", scope="world")
    removed = False
    if world_dir.exists():
        shutil.rmtree(world_dir)
        removed = True

    activity_manager.log(
        "Servidor",
        f"Wipe de mundo '{settings.server_name}' completado (respaldo: {bk.get('filename', 'N/A')})",
        action="world_wipe",
        status="warning",
    )
    await process_manager.broadcast_log(
        f"[PZ-Server] Wipe de mundo ejecutado para '{settings.server_name}'. Respaldo previo: {bk.get('filename', 'N/A')}."
    )
    return {
        "success": True,
        "removed": removed,
        "backup": bk.get("filename"),
        "message": f"Mundo '{settings.server_name}' reiniciado al Día 1 (respaldo previo guardado: {bk.get('filename', 'N/A')}).",
    }


# ----------------------------- Respaldos -----------------------------
async def _execute_backup_pipeline(p: dict, job_id: str) -> dict:
    tag = str(p.get("tag") or p.get("name") or "manual").strip() or "manual"
    scope = str(p.get("scope") or "full")
    targets = p.get("targets") if isinstance(p.get("targets"), list) else None
    compression = p.get("compression", True)
    stop_server = bool(p.get("stop_server", False))
    pre_cmd = str(p.get("pre_command") or "").strip()
    post_cmd = str(p.get("post_command") or "").strip()

    was_running = process_manager.get_status() == "RUNNING"
    try:
        if was_running and pre_cmd:
            backup_manager.update_job(job_id, stage="saving")
            await process_manager.send_command(pre_cmd)
        if was_running and stop_server:
            backup_manager.update_job(job_id, stage="stopping")
            await process_manager.stop_server()

        backup_manager.update_job(job_id, stage="compressing")
        res = await backup_manager.create_backup(
            custom_name=p.get("name"),
            scope=scope,
            targets=targets,
            compression=bool(compression),
            tag=tag,
        )

        if was_running and stop_server:
            backup_manager.update_job(job_id, stage="restarting")
            await process_manager.start_server()
        if post_cmd and process_manager.get_status() == "RUNNING":
            await process_manager.send_command(post_cmd)

        if res.get("success"):
            backup_manager.update_job(
                job_id,
                is_running=False,
                status="completed",
                stage="completed",
                filename=res.get("filename"),
                size_formatted=res.get("size_formatted"),
                size_bytes=res.get("size_bytes", 0),
                origin=res.get("origin"),
                is_auto=res.get("is_auto"),
                scope=res.get("scope"),
                scope_label=res.get("scope_label"),
                created_at=res.get("created_at"),
                error=None,
            )
        else:
            backup_manager.update_job(
                job_id,
                is_running=False,
                status="error",
                stage="error",
                error=res.get("error", "Error creando respaldo"),
            )
        return res
    except Exception as exc:
        backup_manager.update_job(job_id, is_running=False, status="error", stage="error", error=str(exc))
        raise


@app.get("/api/backups/list", dependencies=[Depends(require_auth)])
async def api_backups_list_raw():
    return await asyncio.to_thread(backup_manager.list_backups)


@app.get("/api/backups/targets", dependencies=[Depends(require_auth)])
async def api_backups_targets():
    return await asyncio.to_thread(backup_manager.get_available_targets)


@app.get("/api/backups/status", dependencies=[Depends(require_auth)])
async def api_backups_status():
    return backup_manager.progress


@app.post("/api/backups/create", dependencies=[Depends(require_auth)])
async def api_backup_create(payload: Optional[dict] = None):
    p = payload or {}
    job_id = str(time.time_ns())[-10:]
    if not backup_manager.try_start_job(job_id, stage="preparing"):
        raise HTTPException(status_code=409, detail="Ya hay una copia de seguridad en progreso.")

    if p.get("background"):
        asyncio.create_task(_execute_backup_pipeline(p, job_id))
        return {"status": "started", "job_id": job_id, "progress": backup_manager.progress}

    return await _execute_backup_pipeline(p, job_id)


@app.post("/api/backups/restore", dependencies=[Depends(require_auth)])
async def api_backup_restore(payload: Optional[dict] = None):
    filename = (payload or {}).get("filename", "")
    return await backup_manager.restore_backup(filename)


@app.get("/api/backups/config", dependencies=[Depends(require_auth)])
async def api_backups_config_get():
    cfg = settings.runtime_config
    return {
        "auto_backup": bool(cfg.get("auto_backup_enabled", True)),
        "backup_interval_hours": int(cfg.get("auto_backup_interval_hours", 6) or 6),
        "backup_max_count": int(cfg.get("backup_max_count", 10) or 10),
        "backup_scope": cfg.get("backup_scope", "full"),
        "backup_targets": cfg.get("backup_targets", []),
        "backup_compression": bool(cfg.get("backup_compression", True)),
        "backup_stop_server": bool(cfg.get("backup_stop_server", False)),
        "backup_pre_command": str(cfg.get("backup_pre_command") or ""),
    }


@app.post("/api/backups/config", dependencies=[Depends(require_auth)])
async def api_backups_config_save(payload: Optional[dict] = None):
    p = payload or {}
    updates = {}
    if "backup_max_count" in p and p["backup_max_count"] is not None:
        updates["backup_max_count"] = max(1, min(100, int(p["backup_max_count"])))
    for key in ("backup_scope", "backup_targets", "backup_compression", "backup_stop_server", "backup_pre_command"):
        if key in p:
            updates[key] = p[key]
    if updates:
        settings.save_runtime_config(updates)
    if "backup_max_count" in updates:
        backup_manager.prune_backups(max_count=updates["backup_max_count"])
    return {"status": "saved", "success": True, "config": settings.runtime_config}


@app.get("/api/backups/policies", dependencies=[Depends(require_auth)])
async def api_backups_policies_get():
    cfg = settings.runtime_config
    return {
        "max_count": int(cfg.get("backup_max_count", 10) or 10),
        "policies": backup_manager.get_policies(),
    }


@app.post("/api/backups/policies", dependencies=[Depends(require_auth)])
async def api_backups_policies_save(payload: Optional[dict] = None):
    p = payload or {}
    if p.get("backup_max_count") is not None:
        mc = max(1, min(100, int(p["backup_max_count"])))
        settings.save_runtime_config({"backup_max_count": mc})
        backup_manager.prune_backups(max_count=mc)
    saved = backup_manager.save_policy(p)
    return {
        "status": "saved",
        "success": True,
        "policy": saved,
        "policies": backup_manager.get_policies(),
        "max_count": int(settings.runtime_config.get("backup_max_count", 10) or 10),
    }


@app.delete("/api/backups/policies/{policy_id}", dependencies=[Depends(require_auth)])
async def api_backups_policies_delete(policy_id: str):
    remaining = backup_manager.delete_policy(policy_id)
    return {"status": "deleted", "success": True, "policies": remaining}


@app.delete("/api/backups/{filename}", dependencies=[Depends(require_auth)])
async def api_backup_delete_rest(filename: str):
    ok = backup_manager.delete_backup(filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    activity_manager.log("Backups", f"Copia eliminada: {filename}", action="backup_deleted")
    return {"status": "success", "success": True}


@app.get("/api/backups/download/{filename}", dependencies=[Depends(require_auth)])
async def api_backup_download(filename: str):
    path = backup_manager.get_backup_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path=str(path), filename=filename, media_type="application/gzip")


# ----------------------------- Mods Inteligentes PZ -----------------------------
@app.get("/api/mods", dependencies=[Depends(require_auth)])
async def api_mods_get():
    return pz_settings_manager.get_mods()


@app.post("/api/mods", dependencies=[Depends(require_auth)])
async def api_mods_save(payload: Optional[dict] = None):
    if not settings.use_steam:
        raise HTTPException(
            status_code=400,
            detail="Los mods están deshabilitados en modo No-Steam / GOG (-nosteam).",
        )
    p = payload or {}
    workshop_raw = p.get("workshop_items")
    if workshop_raw is None:
        workshop_raw = p.get("mod_ids", "")
    mods_names_raw = p.get("mods_names_raw")
    map_raw = p.get("map_raw")
    catalog_hints = p.get("catalog_hints")
    auto_resolve = bool(p.get("auto_resolve", False))

    if auto_resolve and workshop_raw:
        wids = [w.strip() for w in str(workshop_raw).replace(",", ";").split(";") if w.strip().isdigit()]
        if wids:
            await pz_settings_manager.resolve_workshop_items(wids, sync_to_ini=False)

    res = pz_settings_manager.save_mods(
        str(workshop_raw or ""),
        mods_names_raw=mods_names_raw,
        map_raw=map_raw,
        catalog_hints=catalog_hints if isinstance(catalog_hints, dict) else None,
    )
    if res.get("success"):
        await process_manager.broadcast_log(
            f"[PZ-Server] Mods actualizados en .ini (WorkshopItems={res['count']}). Reinicia el server para aplicarlos."
        )
    return res


@app.post("/api/mods/resolve", dependencies=[Depends(require_auth)])
async def api_mods_resolve(payload: Optional[dict] = None):
    if not settings.use_steam:
        raise HTTPException(
            status_code=400,
            detail="Los mods están deshabilitados en modo No-Steam / GOG (-nosteam).",
        )
    p = payload or {}
    raw_ids = p.get("workshop_ids")
    if isinstance(raw_ids, str):
        wids = [x.strip() for x in raw_ids.replace(",", ";").split(";") if x.strip()]
    elif isinstance(raw_ids, list):
        wids = [str(x).strip() for x in raw_ids if str(x).strip()]
    else:
        wids = pz_settings_manager.get_mods().get("workshop_items", [])
    sync_to_ini = bool(p.get("sync_to_ini", True))
    res = await pz_settings_manager.resolve_workshop_items(wids, sync_to_ini=sync_to_ini)
    return res


@app.post("/api/mods/collection", dependencies=[Depends(require_auth)])
async def api_mods_collection(payload: Optional[dict] = None):
    if not settings.use_steam:
        raise HTTPException(
            status_code=400,
            detail="Los mods están deshabilitados en modo No-Steam / GOG (-nosteam).",
        )
    p = payload or {}
    col = p.get("collection") or p.get("collection_id") or ""
    return await pz_settings_manager.resolve_workshop_collection(str(col))


# ----------------------------- Tareas / Scheduler -----------------------------
@app.get("/api/tasks", dependencies=[Depends(require_auth)])
async def api_tasks_raw_list():
    return task_scheduler.list_tasks()


@app.post("/api/tasks", dependencies=[Depends(require_auth)])
async def api_tasks_raw_create(payload: Optional[dict] = None):
    return task_scheduler.create_task(payload or {})


@app.get("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
async def api_tasks_get_single(task_id: str):
    t = task_scheduler.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return t


@app.put("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
async def api_tasks_update(task_id: str, payload: Optional[dict] = None):
    t = task_scheduler.update_task(task_id, payload or {})
    if not t:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return t


@app.post("/api/tasks/{task_id}/toggle", dependencies=[Depends(require_auth)])
async def api_tasks_toggle(task_id: str, payload: Optional[dict] = None):
    enabled = (payload or {}).get("enabled") if payload else None
    t = task_scheduler.toggle_task(task_id, enabled=enabled)
    if not t:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return {**t, "success": True, "task": t}


@app.post("/api/tasks/{task_id}/run", dependencies=[Depends(require_auth)])
async def api_tasks_run(task_id: str):
    try:
        return await task_scheduler.run_task_now(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
async def api_tasks_delete(task_id: str):
    ok = task_scheduler.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return {"success": True}


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
        elif sk.startswith("panel_") or sk in (
            "memory_min", "memory_max", "use_steam", "autostart_server",
            "update_on_start", "branch", "additional_args", "disk_limit_gb"
        ):
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
    elif file_type == "spawnregions":
        ok = pz_settings_manager.save_raw_spawnregions(content)
    else:
        ok = pz_settings_manager.save_raw_ini(content)
    return {"success": ok}


@app.post("/api/server/reloadoptions", dependencies=[Depends(require_auth)])
async def api_server_reloadoptions():
    activity_manager.log("Configuración", "Recarga en caliente (reloadoptions)", action="reloadoptions")
    resp = await process_manager.send_command("reloadoptions")
    return {"success": True, "response": resp}


# ----------------------------- Webhooks Discord, Telegram & Email -----------------------------
@app.get("/api/webhooks/config", dependencies=[Depends(require_auth)])
async def api_webhooks_config_get():
    return webhook_manager.get_sanitized_config()


@app.post("/api/webhooks/config", dependencies=[Depends(require_auth)])
async def api_webhooks_config_save(payload: Optional[dict] = None):
    saved = webhook_manager.save_config(payload or {})
    activity_manager.log("Webhooks", "Configuración multi-canal guardada", action="webhooks_saved")
    return {"status": "saved", "success": True, "config": saved}


@app.post("/api/webhooks/test/{channel}", dependencies=[Depends(require_auth)])
async def api_webhooks_test_channel(channel: str):
    res = await webhook_manager.test_channel(channel.lower())
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Error enviando notificación de prueba"))
    activity_manager.log("Webhooks", f"Prueba enviada a {channel}", action="webhooks_test")
    return res


# ----------------------------- Actividad y Registros -----------------------------
@app.get("/api/activity/logs", dependencies=[Depends(require_auth)])
async def api_activity_logs(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return activity_manager.get_logs(category=category, search=search, limit=limit, offset=offset)


@app.post("/api/activity/clear", dependencies=[Depends(require_auth)])
async def api_activity_clear():
    activity_manager.clear()
    activity_manager.log("Seguridad", "Historial de auditoría vaciado por el administrador", action="activity_cleared")
    return {"success": True, "message": "Historial vaciado correctamente"}


@app.get("/api/activity/export", dependencies=[Depends(require_auth)])
async def api_activity_export(format: str = Query("csv", pattern="^(txt|json|csv)$")):
    content = activity_manager.export_logs(format_type=format)
    media_type = (
        "application/json" if format == "json"
        else ("text/csv; charset=utf-8" if format == "csv" else "text/plain; charset=utf-8")
    )
    filename = f"pz_activity_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format}"
    return FastAPIResponse(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
