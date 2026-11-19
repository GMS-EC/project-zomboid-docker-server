import os
import re
import json
import sys
import time
import asyncio
import logging
from collections import deque
from pathlib import Path
from typing import Set, List, Deque, Optional, Dict, Any

import psutil
from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger("pzserver.process")

PZ_STEAMCMD_APPID = "380870"

_RE_PLAYERS_HEADER = re.compile(r"Players connected\s*\((\d+)\)\s*:", re.IGNORECASE)
_RE_STEAMID = re.compile(r"(?:SteamID[:=\s]+|7656119)(7656119\d{10}|\d{17})", re.IGNORECASE)
_RE_JOIN_PATTERNS = [
    re.compile(r'^\[PZ-Sim\]\s*Jugador conectado:\s*["\']?([A-Za-z0-9_\-\. ]+?)["\']?(?:\s*\(SteamID:\s*([0-9]+)\))?$', re.IGNORECASE),
    re.compile(r'\buser\s+["\']?([^"\'\n]+?)["\']?\s+fully connected\b', re.IGNORECASE),
    re.compile(r'\bplayer\s+["\']?([^"\'\n]+?)["\']?\s+(?:joined|fully connected|connected)(?:\s*\(SteamID:\s*([0-9]+)\))?', re.IGNORECASE),
]
_RE_LEAVE_PATTERNS = [
    re.compile(r'^\[PZ-Sim\]\s*Jugador desconectado:\s*["\']?([A-Za-z0-9_\-\. ]+?)["\']?$', re.IGNORECASE),
    re.compile(r'\buser\s+["\']?([^"\'\n]+?)["\']?\s+disconnected\b', re.IGNORECASE),
    re.compile(r'\bplayer\s+["\']?([^"\'\n]+?)["\']?\s+(?:left|disconnected)\b', re.IGNORECASE),
    re.compile(r'\bConnectionLost\b.*?username=["\']?([^"\'\s]+)["\']?', re.IGNORECASE),
]


class ProcessManager:
    """Ciclo de vida del proceso PZ (instalación, ejecución por STDIN, consola WebSocket y jugadores)."""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.status: str = "OFFLINE"  # OFFLINE, STARTING, RUNNING, STOPPING, INSTALLING
        self.connected_websockets: Set[WebSocket] = set()
        self.log_buffer: Deque[str] = deque(maxlen=2000)
        self._reader_task: Optional[asyncio.Task] = None
        self.started_at: Optional[float] = None
        self.last_start_time: Optional[float] = None
        self.last_exit_code: Optional[int] = None
        self._intentional_stop: bool = False
        self._server_up_detected: bool = False
        self._is_simulation: bool = False
        self.install_progress: Dict[str, Any] = {
            "running": False,
            "percent": 0.0,
            "step": "",
            "last_line": "",
        }

        # Tracking en vivo de jugadores conectados (clave = username.lower())
        self.online_players: Dict[str, Dict[str, Any]] = {}
        self._collecting_players: bool = False
        self._collecting_expected_count: int = 0
        self._collecting_players_until: float = 0.0
        self._collected_players: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _schedule_bg(coro) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass

    @staticmethod
    def _is_pz_process_running() -> bool:
        try:
            for p in psutil.process_iter(['name', 'cmdline']):
                pname = (p.info.get('name') or '').lower()
                pcmd = (' '.join(p.info.get('cmdline') or [])).lower()
                if pname in ('python', 'python.exe', 'python3', 'bash', 'sh', 'powershell.exe', 'pwsh.exe', 'cmd.exe'):
                    continue
                if pname == 'java' and 'zombie.network.GameServer' in pcmd:
                    return True
                if 'projectzomboid64' in pcmd or 'start-server.sh' in pcmd:
                    return True
        except Exception:
            pass
        return False

    def is_installed(self) -> bool:
        return settings.is_installed()

    def get_status(self) -> str:
        if self.status in ("INSTALLING", "STOPPING"):
            return self.status
        if self.status == "STARTING":
            if self.process and self.process.returncode is not None:
                self.status = "OFFLINE"
                return "OFFLINE"
            return "STARTING"
        if not self._is_simulation and self.process and self.process.returncode is None:
            if self.status == "OFFLINE":
                self.status = "RUNNING"
            return self.status
        if self._is_simulation and self.process and self.process.returncode is None:
            return self.status if self.status in ("RUNNING", "STARTING") else "RUNNING"
        self.status = "OFFLINE"
        return "OFFLINE"

    async def broadcast_log(self, message: str) -> None:
        clean_line = message.rstrip("\r\n")
        if not clean_line:
            return
        self.log_buffer.append(clean_line)
        dead_ws = set()
        for ws in list(self.connected_websockets):
            try:
                await ws.send_text(clean_line)
            except Exception:
                dead_ws.add(ws)
        self.connected_websockets.difference_update(dead_ws)

    # ------------------------------------------------------------ detección jugadores
    def _finalize_players_collection(self) -> None:
        if not self._collecting_players:
            return
        self._collecting_players = False
        merged: Dict[str, Dict[str, Any]] = {}
        for key, entry in self._collected_players.items():
            existing = self.online_players.get(key)
            if existing and not entry.get("steam_id"):
                entry["steam_id"] = existing.get("steam_id", "")
            if existing and existing.get("connected_at"):
                entry["connected_at"] = existing["connected_at"]
            merged[key] = entry
        self.online_players = merged
        self._collected_players = {}

    def _record_player_join(self, username: str, steam_id: str = "") -> None:
        clean = username.strip().strip('"').strip()
        if not clean:
            return
        key = clean.lower()
        existing = self.online_players.get(key, {})
        sid = steam_id or existing.get("steam_id", "")
        self.online_players[key] = {
            "name": clean,
            "steam_id": sid,
            "connected_at": existing.get("connected_at") or time.time(),
        }
        try:
            from app.core.player_manager import player_manager
            player_manager.record_join(clean, sid)
        except Exception:
            pass
        try:
            from app.core.webhook_manager import webhook_manager
            self._schedule_bg(
                webhook_manager.notify(
                    "players_join",
                    f"El superviviente **{clean}** se ha conectado al servidor.",
                )
            )
        except Exception:
            pass

    def _record_player_leave(self, username: str) -> None:
        clean = username.strip().strip('"').strip()
        if not clean:
            return
        key = clean.lower()
        removed = self.online_players.pop(key, None)
        display_name = removed.get("name", clean) if removed else clean
        try:
            from app.core.player_manager import player_manager
            player_manager.record_leave(display_name)
        except Exception:
            pass
        try:
            from app.core.webhook_manager import webhook_manager
            self._schedule_bg(
                webhook_manager.notify(
                    "players_leave",
                    f"El superviviente **{display_name}** ha salido del servidor.",
                )
            )
        except Exception:
            pass

    def parse_console_line(self, line: str) -> None:
        """Analiza una línea de salida de consola para actualizar estado y jugadores en línea."""
        stripped = line.strip()
        if not stripped:
            if self._collecting_players:
                self._finalize_players_collection()
            return
        if stripped.startswith(">"):
            return

        # 1) Respuesta a 'players': "Players connected (N):" seguido de "-nombre"
        m_hdr = _RE_PLAYERS_HEADER.search(stripped)
        if m_hdr:
            count = int(m_hdr.group(1))
            if count == 0:
                self.online_players.clear()
                self._collecting_players = False
                self._collecting_expected_count = 0
                self._collected_players = {}
            else:
                self._collecting_players = True
                self._collecting_expected_count = count
                self._collecting_players_until = time.time() + 3.0
                self._collected_players = {}
            return

        if self._collecting_players:
            if time.time() > self._collecting_players_until:
                self._finalize_players_collection()
            elif stripped.startswith("-"):
                pname = stripped[1:].strip()
                if pname:
                    existing = self.online_players.get(pname.lower(), {})
                    self._collected_players[pname.lower()] = {
                        "name": pname,
                        "steam_id": existing.get("steam_id", ""),
                        "connected_at": existing.get("connected_at") or time.time(),
                    }
                    if len(self._collected_players) >= self._collecting_expected_count:
                        self._finalize_players_collection()
                return
            else:
                self._finalize_players_collection()

        # 2) Eventos de conexión
        for pat in _RE_JOIN_PATTERNS:
            m = pat.search(stripped)
            if m:
                pname = m.group(1).strip()
                sid = m.group(2).strip() if m.lastindex and m.lastindex >= 2 and m.group(2) else ""
                if not sid:
                    m_sid = _RE_STEAMID.search(stripped)
                    if m_sid:
                        raw_sid = m_sid.group(1)
                        sid = raw_sid if raw_sid.startswith("7656119") else f"7656119{raw_sid}"
                self._record_player_join(pname, sid)
                return

        # 3) Eventos de desconexión
        for pat in _RE_LEAVE_PATTERNS:
            m = pat.search(stripped)
            if m:
                self._record_player_leave(m.group(1))
                return

    # ------------------------------------------------------------ instalación
    def _patch_launcher_memory(self) -> None:
        """Ajusta -Xms/-Xmx del lanzador JVM."""
        if not settings.override_launcher_memory:
            return
        root = settings.server_dir
        if not root.is_dir():
            return

        if self._patch_launcher_json():
            return

        pattern = re.compile(r"-Xm[sx]\d+[gGmMkK]?")
        candidates = [
            root / "start-server.sh", root / "start-server64.sh", root / "start-server32.sh",
            root / "start-server.bat", root / "ProjectZomboid64", root / "ProjectZomboid32",
        ]
        for f in candidates:
            if not f.is_file():
                continue
            try:
                data = f.read_text(encoding="utf-8", errors="strict")
            except Exception:
                continue
            if "\x00" in data or not re.search(r"-Xm[sx]\d+", data):
                continue
            new_data = pattern.sub(
                lambda m: ("-Xms" + settings.memory_min) if m.group(0).startswith("-Xms")
                else ("-Xmx" + settings.memory_max),
                data,
            )
            if new_data != data:
                try:
                    f.write_text(new_data, encoding="utf-8")
                    self._schedule_bg(
                        self.broadcast_log(
                            f"[PZ-Server] Heap del lanzador ajustado en {f.name} (min={settings.memory_min}, max={settings.memory_max})"
                        )
                    )
                except Exception as e:
                    logger.warning(f"No se pudo ajustar {f}: {e}")

    def _patch_launcher_json(self) -> bool:
        """Edita ProjectZomboid64.json: garantiza -Xms/-Xmx en vmArgs."""
        json_file = settings.launcher_json
        if not json_file.is_file():
            return False
        try:
            cfg = json.loads(json_file.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                return False
            vm = cfg.get("vmArgs")
            if not isinstance(vm, list):
                vm = []
            changed = False

            def _replace(new_val: str, lowered: str) -> None:
                nonlocal changed
                for i, arg in enumerate(vm):
                    if isinstance(arg, str) and arg.lower().startswith(lowered):
                        if arg != new_val:
                            vm[i] = new_val
                            changed = True
                        return
                vm.append(new_val)
                changed = True

            _replace("-Xms" + settings.memory_min, "-xms")
            _replace("-Xmx" + settings.memory_max, "-xmx")
            if changed:
                cfg["vmArgs"] = vm
                tmp = json_file.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
                tmp.replace(json_file)
                self._schedule_bg(
                    self.broadcast_log(
                        f"[PZ-Server] Heap ajustado en ProjectZomboid64.json (min={settings.memory_min}, max={settings.memory_max})"
                    )
                )
            return True
        except Exception as e:
            logger.warning(f"No se pudo ajustar ProjectZomboid64.json: {e}")
            return False

    def _steamcmd_path(self) -> str:
        env_path = os.getenv("STEAMCMD", "").strip()
        if env_path:
            return env_path
        candidate = Path("/home/steam/steamcmd/steamcmd.sh")
        return str(candidate) if candidate.exists() else "steamcmd"

    def _depotdownloader_path(self) -> Optional[str]:
        env_path = os.getenv("DEPOTDOWNLOADER", "").strip()
        if env_path:
            return env_path
        candidate = Path("/depotdownloader/DepotDownloader")
        return str(candidate) if candidate.exists() else None

    def _update_install_progress(self, line: str) -> None:
        clean = (line or "").strip()
        if not clean:
            return
        low = clean.lower()
        pct = float(self.install_progress.get("percent", 0.0) or 0.0)
        m_pct = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", clean)
        if m_pct:
            try:
                pct = max(0.0, min(100.0, float(m_pct.group(1))))
            except ValueError:
                pass

        step = self.install_progress.get("step") or "Descargando servidor..."
        if "download" in low or "descarg" in low:
            step = "Descargando archivos del servidor (AppID 380870)..."
        elif "validat" in low or "verify" in low or "verific" in low:
            step = "Verificando integridad de archivos..."
        elif "pre-allocat" in low or "prealloc" in low:
            step = "Reservando espacio en disco..."
        elif "connect" in low or "logging in" in low:
            step = "Conectando con Steam..."
        elif "success" in low or "[ok]" in low or "completad" in low:
            step = "Instalación completada"
            pct = 100.0

        self.install_progress = {
            "running": True,
            "percent": round(pct, 1),
            "step": step,
            "last_line": clean[:220],
        }

    async def install_server(self, auto_start: bool = False) -> bool:
        """Descarga/actualiza los binarios del servidor dedicado (descarga anónima)."""
        if self.status in ("RUNNING", "STARTING", "INSTALLING"):
            await self.broadcast_log("[PZ-Server] Ya hay una tarea o proceso en ejecución.")
            return False

        self.status = "INSTALLING"
        self.install_progress = {
            "running": True,
            "percent": 2.0,
            "step": "Iniciando descarga (AppID 380870)...",
            "last_line": "",
        }
        await self.broadcast_log("=" * 60)
        await self.broadcast_log(" Descargando Project Zomboid Dedicated Server (AppID 380870)")
        await self.broadcast_log("=" * 60)
        await self.broadcast_log(f"[PZ-Server] Destino: {settings.server_dir}")
        await self.broadcast_log(
            "[PZ-Server] Modo " + ("STEAM" if settings.use_steam else "NO-STEAM")
            + (f" | Rama: {settings.branch}" if settings.branch else " | Rama: estable")
        )

        depot = self._depotdownloader_path()
        if depot:
            await self.broadcast_log("[PZ-Server] Instalador: DepotDownloader (anónimo).")
            cmd = [
                depot,
                "-app", PZ_STEAMCMD_APPID,
                "-dir", str(settings.server_dir),
                "-validate",
            ]
            if settings.branch:
                cmd += ["-branch", settings.branch]
        else:
            await self.broadcast_log(
                "[PZ-Server] Instalador: SteamCMD (DepotDownloader no disponible; si falla, "
                "revisa el error 'Missing configuration')."
            )
            steamcmd = self._steamcmd_path()
            cmd = [
                steamcmd,
                "+force_install_dir", str(settings.server_dir),
                "+login", "anonymous",
                "+app_update", PZ_STEAMCMD_APPID,
            ]
            if settings.branch:
                cmd += ["-beta", settings.branch]
            cmd += ["validate", "+quit"]

        tool_name = "DepotDownloader" if depot else "SteamCMD"
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._build_env(),
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                self._update_install_progress(decoded)
                await self.broadcast_log(decoded)
            await proc.wait()

            if proc.returncode == 0:
                self._make_launchers_executable()
                self._patch_launcher_memory()
                self.install_progress = {
                    "running": False,
                    "percent": 100.0,
                    "step": "Instalación completada",
                    "last_line": "[OK] Servidor instalado/actualizado correctamente.",
                }
                await self.broadcast_log("[PZ-Server] [OK] Servidor instalado/actualizado correctamente.")
                self.status = "OFFLINE"
                if auto_start:
                    await self.broadcast_log("[PZ-Server] Auto-arrancando servidor tras completar instalación...")
                    await self.start_server()
                return True
            await self.broadcast_log(f"[PZ-Server] [ERROR] {tool_name} falló (código {proc.returncode}).")
            self.install_progress["running"] = False
            self.install_progress["step"] = "Error en la descarga"
            self.status = "OFFLINE"
            return False
        except FileNotFoundError:
            await self.broadcast_log(f"[PZ-Server] [ERROR] No se encontró el instalador: {tool_name}")
            self.install_progress["running"] = False
            self.install_progress["step"] = "Error en la descarga"
            self.status = "OFFLINE"
            return False
        except Exception as e:
            await self.broadcast_log(f"[PZ-Server] [ERROR] Instalación fallida: {e}")
            self.install_progress["running"] = False
            self.install_progress["step"] = "Error en la descarga"
            self.status = "OFFLINE"
            return False

    def _make_launchers_executable(self) -> None:
        try:
            for name in ("start-server.sh", "ProjectZomboid64", "ProjectZomboid32"):
                f = settings.server_dir / name
                if f.exists():
                    f.chmod(f.stat().st_mode | 0o111)
            for sub in ("jre64/bin", "jre/bin"):
                d = settings.server_dir / sub
                if d.is_dir():
                    for f in d.iterdir():
                        if f.is_file():
                            f.chmod(f.stat().st_mode | 0o111)
        except Exception:
            pass

    # ------------------------------------------------------------ arranque
    def _ensure_ini_defaults(self) -> None:
        ini_dir = settings.data_dir / "Server"
        ini = ini_dir / f"{settings.server_name}.ini"
        defaults = {
            "DefaultPort": str(settings.server_port),
            "UDPPort": str(settings.direct_port),
            "MaxPlayers": str(settings.max_players),
        }
        if settings.server_password:
            defaults["Password"] = settings.server_password
        if settings.rcon_password:
            defaults["RCONPort"] = str(settings.rcon_port or 27015)
            defaults["RCONPassword"] = settings.rcon_password
        try:
            ini_dir.mkdir(parents=True, exist_ok=True)
            lines: List[str] = []
            if ini.exists():
                lines = ini.read_text(encoding="utf-8", errors="replace").splitlines()
            present = {ln.strip().split("=", 1)[0] for ln in lines if "=" in ln}
            added = []
            for key, value in defaults.items():
                if key not in present:
                    lines.append(f"{key}={value}")
                    added.append(f"{key}={value}")
            if added:
                ini.write_text("\n".join(lines) + "\n", encoding="utf-8")
                self._schedule_bg(
                    self.broadcast_log(
                        f"[PZ-Server] Claves iniciales añadidas a {ini.name}: {', '.join(k.split('=')[0] for k in added)}"
                    )
                )
        except Exception as e:
            logger.warning(f"No se pudo preparar {ini}: {e}")

    def _build_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env.update({
            "PZ_SERVER_DIR": str(settings.server_dir),
            "PZ_DATA_DIR": str(settings.data_dir),
            "USE_STEAM": "true" if settings.use_steam else "false",
            "SERVER_NAME": settings.server_name,
            "ADMIN_USERNAME": settings.admin_username,
            "ADMIN_PASSWORD": settings.server_admin_password,
            "SERVER_MEMORY_MIN": settings.memory_min,
            "SERVER_MEMORY_MAX": settings.memory_max,
            "OVERRIDE_LAUNCHER_MEMORY": "true" if settings.override_launcher_memory else "false",
            "ADDITIONAL_ARGS": settings.additional_args,
            "HOME": os.getenv("HOME", "/home/steam"),
            "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1",
            "PYTHONIOENCODING": "utf-8",
        })
        return env

    async def start_server(self) -> bool:
        if not settings.is_setup_done:
            await self.broadcast_log(
                "[PZ-Server] [BLOQUEADO] Configuración inicial pendiente. "
                "Define los parámetros del servidor en la pestaña Setup antes de iniciar."
            )
            return False

        if self.status in ("RUNNING", "STARTING", "INSTALLING") or self._is_pz_process_running():
            await self.broadcast_log("[PZ-Server] El servidor ya está en ejecución o iniciando.")
            return False

        self._intentional_stop = False
        self._server_up_detected = False
        self.last_exit_code = None
        self.online_players.clear()

        if not self.is_installed() and settings.in_container:
            await self.broadcast_log(
                "[PZ-Server] Servidor no instalado. Descargando binarios automáticamente "
                "(SteamCMD AppID 380870) — funciona también en modo NO-STEAM..."
            )
            ok = await self.install_server()
            if not ok:
                await self.broadcast_log(
                    "[PZ-Server] No se pudo completar la descarga. Revisa conectividad o monta "
                    "los archivos en PZ_SERVER_DIR (volumen steamcmd/pz) y pulsa Iniciar."
                )
                self.status = "OFFLINE"
                return False

        if self.is_installed():
            self.status = "STARTING"
            await self.broadcast_log(f"[PZ-Server] Iniciando Project Zomboid ({settings.server_name})...")
            self._patch_launcher_memory()
            self._ensure_ini_defaults()
            pz_run = settings.pz_run_script
            if not pz_run.exists():
                pz_run = settings.base_dir / "scripts" / "pz_run.sh"
            if pz_run.exists():
                cmd = ["bash", str(pz_run)]
            else:
                launcher = self._detect_launcher()
                if not launcher:
                    await self.broadcast_log("[PZ-Server] Lanzador del server no encontrado.")
                    self.status = "OFFLINE"
                    return False
                cmd = ["bash", str(launcher)]
        else:
            self.status = "STARTING"
            self._is_simulation = True
            await self.broadcast_log("[PZ-Server] [SIMULACIÓN] No hay binarios: arrancando servidor simulado...")
            cmd = [sys.executable, "-m", "app.core.sim_server"]
            self._server_up_detected = False

        now = time.time()
        self.started_at = now
        self.last_start_time = now
        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._build_env(),
                cwd=str(settings.server_dir if self.is_installed() else settings.base_dir),
            )
        except Exception as e:
            self.status = "OFFLINE"
            self._is_simulation = False
            await self.broadcast_log(f"[PZ-Server] Error al iniciar el proceso: {e}")
            return False

        self._reader_task = asyncio.create_task(self._stream_output(self.process))
        await self.broadcast_log(f"[PZ-Server] Proceso lanzado (PID {self.process.pid}). Estado: STARTING.")
        try:
            from app.core.webhook_manager import webhook_manager
            self._schedule_bg(webhook_manager.notify("starting", f"Iniciando servidor {settings.server_name}..."))
        except Exception:
            pass
        asyncio.create_task(self._watch_server_readiness())
        return True

    def _detect_launcher(self) -> Optional[Path]:
        for name in ("start-server.sh", "ProjectZomboid64", "ProjectZomboid32"):
            candidate = settings.server_dir / name
            if candidate.exists():
                return candidate
        return None

    async def _stream_output(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            up = decoded.upper()
            if any(marker.upper() in up for marker in settings.ready_markers):
                self._server_up_detected = True
            self.parse_console_line(decoded)
            await self.broadcast_log(decoded)
        await proc.wait()
        self.last_exit_code = proc.returncode
        self.online_players.clear()
        if not self._intentional_stop:
            await self.broadcast_log(f"[PZ-Server] El proceso del servidor se ha detenido (código {proc.returncode}).")
            try:
                from app.core.webhook_manager import webhook_manager
                if proc.returncode not in (0, None):
                    await webhook_manager.notify("crash", f"El proceso terminó inesperadamente (código {proc.returncode}).")
                else:
                    await webhook_manager.notify("shutdown")
            except Exception:
                pass
        self.status = "OFFLINE"
        self.started_at = None
        self._is_simulation = False
        self._reader_task = None

    # ------------------------------------------------------------ disponibilidad
    async def _watch_server_readiness(self) -> None:
        start = time.time()
        last_heartbeat = start
        await self.broadcast_log("[PZ-Server] Monitor de disponibilidad activo. Cargando mundo...")

        while self.status == "STARTING" and self.process and self.process.returncode is None:
            await asyncio.sleep(2.0 if self._is_simulation else 4.0)
            if self.status != "STARTING":
                return

            elapsed = int(time.time() - start)

            if self._server_up_detected:
                self.status = "RUNNING"
                await self.broadcast_log("[PZ-Server] [OK] ¡Servidor 100% listo y aceptando jugadores!")
                await self.broadcast_log(f"[PZ-Server] Mundo '{settings.server_name}' cargado en {elapsed}s.")
                try:
                    from app.core.webhook_manager import webhook_manager
                    await webhook_manager.notify("start", f"Mundo `{settings.server_name}` listo en {elapsed}s.")
                except Exception:
                    pass
                return

            if elapsed > 240:
                self.status = "RUNNING"
                await self.broadcast_log(
                    "[PZ-Server] [OK] Servidor marcado como RUNNING (timeout de 240s). "
                    "Si tu build no emitió el marcador, ajusta PZ_READY_MARKERS."
                )
                try:
                    from app.core.webhook_manager import webhook_manager
                    await webhook_manager.notify("start", f"Servidor `{settings.server_name}` activo.")
                except Exception:
                    pass
                return

            if time.time() - last_heartbeat >= 45:
                last_heartbeat = time.time()
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                await self.broadcast_log(
                    f"[PZ-Server] [EN PROCESO] Cargando mundo ({mins}m {secs}s). "
                    "Los servidores PZ pueden tardar varios minutos en el primer arranque."
                )

    # ------------------------------------------------------------ comandos
    async def _write_console(self, text: str) -> None:
        if self.process and self.process.stdin and self.process.returncode is None:
            try:
                self.process.stdin.write((text + "\n").encode("utf-8"))
                await self.process.stdin.drain()
                return
            except Exception as e:
                logger.debug(f"No se pudo escribir en stdin: {e}")
        fifo = settings.control_fifo
        if fifo.exists():
            try:
                with open(str(fifo), "w", encoding="utf-8") as f:
                    f.write(text + "\n")
            except Exception:
                pass

    async def send_command(self, command: str) -> str:
        cmd = command.strip()
        if not cmd:
            return ""
        await self.broadcast_log(f"> {cmd}")
        if not self.process or self.process.returncode is not None:
            return "[PZ-Server] El servidor no está en ejecución."
        await self._write_console(cmd)
        return f"[PZ-Server] Comando enviado a la consola: {cmd}"

    async def save_world(self) -> str:
        await self.broadcast_log("[PZ-Server] Guardando mundo... (save)")
        await self._write_console("save")
        try:
            from app.core.webhook_manager import webhook_manager
            self._schedule_bg(webhook_manager.notify("save"))
        except Exception:
            pass
        return "[PZ-Server] save enviado."

    async def broadcast(self, message: str) -> str:
        safe = message.replace('"', '\\"').replace("\n", " ").replace("\r", "")
        await self._write_console(f'servermsg "{safe}"')
        return f"[PZ-Server] servermsg enviado: {message}"

    async def players(self) -> str:
        await self._write_console("players")
        return "[PZ-Server] Comando 'players' enviado (respuesta en consola)."

    # ------------------------------------------------------------ detención
    async def stop_server(self, grace_seconds: int = 30) -> bool:
        if self.status == "OFFLINE" and not (self.process and self.process.returncode is None):
            await self.broadcast_log("[PZ-Server] El servidor ya está apagado.")
            return False

        self.status = "STOPPING"
        self._intentional_stop = True
        await self.broadcast_log("[PZ-Server] Apagado seguro: guardando y enviando 'quit' a la consola...")
        try:
            await self._write_console("save")
            await asyncio.sleep(1.5)
            await self._write_console("quit")
        except Exception:
            pass

        if self.process and self.process.returncode is None:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=grace_seconds)
            except asyncio.TimeoutError:
                await self.broadcast_log("[PZ-Server] Grace period superado. Terminando proceso...")
                try:
                    self.process.terminate()
                    await asyncio.wait_for(self.process.wait(), timeout=10)
                except Exception:
                    try:
                        proc = psutil.Process(self.process.pid)
                        for child in proc.children(recursive=True):
                            try:
                                child.kill()
                            except Exception:
                                pass
                        proc.kill()
                    except Exception:
                        pass

        self.status = "OFFLINE"
        self.started_at = None
        self._is_simulation = False
        self.online_players.clear()
        await self.broadcast_log("[PZ-Server] Servidor de Project Zomboid detenido.")
        try:
            from app.core.webhook_manager import webhook_manager
            await webhook_manager.notify("shutdown")
        except Exception:
            pass
        return True

    async def restart_server(self) -> bool:
        await self.stop_server()
        await asyncio.sleep(2)
        self._intentional_stop = False
        return await self.start_server()


process_manager = ProcessManager()
