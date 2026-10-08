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


class ProcessManager:
    """
    Controlador del ciclo de vida del servidor dedicado de Project Zomboid.

    Project Zomboid administra su consola por STDIN del
    proceso. Este manager:
      - Instala/actualiza con SteamCMD (AppID 380870) solo en modo Steam.
      - Arranca el lanzador real (vía pz_run.sh) con stdin en modo PIPE.
      - En ausencia de binarios (desarrollo/validación) arranca una SIMULACIÓN.
      - Difunde las líneas de consola (stdout) a los clientes WebSocket.
      - Envía comandos escribiendo en el stdin del proceso.
    """

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.status: str = "OFFLINE"  # OFFLINE, STARTING, RUNNING, STOPPING, INSTALLING
        self.connected_websockets: Set[WebSocket] = set()
        self.log_buffer: Deque[str] = deque(maxlen=2000)
        self._reader_task: Optional[asyncio.Task] = None
        self._log_file_task: Optional[asyncio.Task] = None
        self.started_at: Optional[float] = None
        self._intentional_stop: bool = False
        self._server_up_detected: bool = False
        self._is_simulation: bool = False

    # ------------------------------------------------------------------ helpers
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
        for ws in self.connected_websockets:
            try:
                await ws.send_text(clean_line)
            except Exception:
                dead_ws.add(ws)
        self.connected_websockets.difference_update(dead_ws)

    # ------------------------------------------------------------ instalación
    def _patch_launcher_memory(self) -> None:
        """Ajusta -Xms/-Xmx del lanzador JVM.

        En B42 los args de memoria viven en ProjectZomboid64.json (campo vmArgs).
        Se prefiere editar ese JSON; si no existe, se hace un fallback textual
        sobre los lanzadores .sh/.bat que hornean -Xms/-Xmx.
        """
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
                continue  # binario o encoding raro: se omite para no corromper
            if "\x00" in data:
                continue
            if not re.search(r"-Xm[sx]\d+", data):
                continue
            new_data = pattern.sub(
                lambda m: ("-Xms" + settings.memory_min) if m.group(0).startswith("-Xms")
                else ("-Xmx" + settings.memory_max),
                data,
            )
            if new_data != data:
                try:
                    f.write_text(new_data, encoding="utf-8")
                    asyncio.create_task(
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

            def _replace(arg_prefix: str, new_val: str, lowered: bool) -> bool:
                nonlocal vm, changed
                for i, arg in enumerate(vm):
                    if isinstance(arg, str) and arg.lower().startswith(lowered):
                        if arg != new_val:
                            vm[i] = new_val
                            changed = True
                        return True
                vm.append(new_val)
                changed = True
                return True

            _replace("-Xms", "-Xms" + settings.memory_min, "-xms")
            _replace("-Xmx", "-Xmx" + settings.memory_max, "-xmx")
            if changed:
                cfg["vmArgs"] = vm
                tmp = json_file.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
                tmp.replace(json_file)
                asyncio.create_task(
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

    async def install_server(self) -> bool:
        """Descarga/actualiza los binarios del servidor dedicado (descarga anónima).

        Funciona en modo Steam y No-Steam: los binarios oficiales del servidor PZ
        se descargan igualmente (AppID 380870, anónimo). El modo No-Steam solo
        cambia el arranque (-nosteam), no la descarga.
        """
        if self.status in ("RUNNING", "STARTING", "INSTALLING"):
            await self.broadcast_log("[PZ-Server] Ya hay una tarea o proceso en ejecución.")
            return False

        self.status = "INSTALLING"
        await self.broadcast_log("=" * 60)
        await self.broadcast_log(" Descargando Project Zomboid Dedicated Server (AppID 380870)")
        await self.broadcast_log("=" * 60)
        await self.broadcast_log(f"[PZ-Server] Destino: {settings.server_dir}")
        await self.broadcast_log(
            "[PZ-Server] Modo " + ("STEAM" if settings.use_steam else "NO-STEAM")
            + ": la descarga de binarios es anónima en ambos modos."
        )

        # 1) DepotDownloader (descarga anónima fiable para este AppID)
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
            # 2) Fallback: SteamCMD (a veces falla con 'Missing configuration')
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
        # El panel corre como usuario `steam` dentro del contenedor.
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
                await self.broadcast_log(line.decode("utf-8", errors="replace").rstrip())
            await proc.wait()

            if proc.returncode == 0:
                self._make_launchers_executable()
                self._patch_launcher_memory()
                await self.broadcast_log("[PZ-Server] [OK] Servidor instalado/actualizado correctamente.")
                self.status = "OFFLINE"
                return True
            await self.broadcast_log(f"[PZ-Server] [ERROR] {tool_name} falló (código {proc.returncode}).")
            self.status = "OFFLINE"
            return False
        except FileNotFoundError:
            await self.broadcast_log(f"[PZ-Server] [ERROR] No se encontró el instalador: {tool_name}")
            self.status = "OFFLINE"
            return False
        except Exception as e:
            await self.broadcast_log(f"[PZ-Server] [ERROR] Instalación fallida: {e}")
            self.status = "OFFLINE"
            return False

    def _make_launchers_executable(self) -> None:
        """Da permisos de ejecución a los lanzadores descargados."""
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
        """Pre-escribe claves mínimas del <SERVER_NAME>.ini si no existen.

        La primera ejecución del server genera el resto del .ini con valores por
        defecto; aquí forzamos que los puertos y límites coincidan con el compose.
        Sigue la estrategia 'insert-if-missing' (no pisa valores ya editados).
        """
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
                asyncio.create_task(
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
            # El subproceso (simulación o consola PZ) debe emitir UTF-8 para que el
            # panel lo decodifique sin pérdida (evita mojibake cp1252 en Windows).
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

        # 0. Instalación automática si no hay binarios (en contenedor):
        #    crea/rellena el volumen PZ_SERVER_DIR con la descarga anónima.
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

        # 1. Si hay binarios reales, lanzarlos vía pz_run.sh (construye args PZ)
        if self.is_installed():
            self.status = "STARTING"
            await self.broadcast_log(f"[PZ-Server] Iniciando Project Zomboid ({settings.server_name})...")
            # Ajustes de la referencia (indifferentbroccoli/pz): memoria en
            # ProjectZomboid64.json + claves mínimas del .ini antes de arrancar.
            self._patch_launcher_memory()
            self._ensure_ini_defaults()
            pz_run = settings.pz_run_script
            if not pz_run.exists():
                # Fallback a la copia local del repositorio (desarrollo)
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
            # 2. Sin binarios y fuera del contenedor (desarrollo/validación local): simulación
            self.status = "STARTING"
            self._is_simulation = True
            await self.broadcast_log("[PZ-Server] [SIMULACIÓN] No hay binarios: arrancando servidor simulado...")
            cmd = [sys.executable, "-m", "app.core.sim_server"]
            self._server_up_detected = False

        self.started_at = time.time()
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
            await self.broadcast_log(f"[PZ-Server] Error al iniciar el proceso: {e}")
            return False

        self._reader_task = asyncio.create_task(self._stream_output(self.process))
        await self.broadcast_log(f"[PZ-Server] Proceso lanzado (PID {self.process.pid}). Estado: STARTING.")
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
            await self.broadcast_log(decoded)
        await proc.wait()
        if not self._intentional_stop:
            await self.broadcast_log("[PZ-Server] El proceso del servidor se ha detenido.")
        self.status = "OFFLINE"
        self._is_simulation = False
        self._reader_task = None

    async def _stream_log_file(self) -> None:
        """Tail opcional de console.txt (el server PZ duplica su consola a este archivo)."""
        log_path = settings.console_log
        for _ in range(30):
            if log_path.exists():
                break
            await asyncio.sleep(1)
        if not log_path.exists():
            return
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                while self.status in ("STARTING", "RUNNING"):
                    line = f.readline()
                    if line:
                        clean = line.rstrip("\r\n")
                        if clean:
                            await self.broadcast_log(clean)
                    else:
                        await asyncio.sleep(0.5)
                        f.seek(f.tell())
        except Exception:
            pass
        finally:
            self._log_file_task = None

    # ------------------------------------------------------------ disponibilidad
    async def _watch_server_readiness(self) -> None:
        """Espera a que el server cargue el mundo (marcador de log) o a un timeout."""
        start = time.time()
        last_heartbeat = start
        await self.broadcast_log("[PZ-Server] Monitor de disponibilidad activo. Cargando mundo...")

        while self.status == "STARTING" and self.process and self.process.returncode is None:
            await asyncio.sleep(4.0)
            if self.status != "STARTING":
                return

            elapsed = int(time.time() - start)

            if self._server_up_detected:
                self.status = "RUNNING"
                await self.broadcast_log("[PZ-Server] [OK] ¡Servidor 100% listo y aceptando jugadores!")
                await self.broadcast_log(f"[PZ-Server] Mundo '{settings.server_name}' cargado en {elapsed}s.")
                return

            # Timeout de seguridad: builds que no imprimen el marcador esperado
            if elapsed > 240:
                self.status = "RUNNING"
                await self.broadcast_log(
                    "[PZ-Server] [OK] Servidor marcado como RUNNING (timeout de 240s). "
                    "Si tu build no emitió el marcador, ajusta PZ_READY_MARKERS."
                )
                return

            if time.time() - last_heartbeat >= 45:
                last_heartbeat = time.time()
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                await self.broadcast_log(
                    f"[PZ-Server] [EN PROCESO] Cargando mundo ({mins}m {secs}s). "
                    "Los servidores PZ pueden tardar varios minutos en el primer arranque."
                )

    async def is_server_ready(self) -> bool:
        if self._server_up_detected:
            return True
        if self._is_simulation and self.started_at and (time.time() - self.started_at > 6):
            return True
        return False

    # ------------------------------------------------------------ comandos
    async def _write_console(self, text: str) -> None:
        if self.process and self.process.stdin and self.process.returncode is None:
            try:
                self.process.stdin.write((text + "\n").encode("utf-8"))
                await self.process.stdin.drain()
                return
            except Exception as e:
                logger.debug(f"No se pudo escribir en stdin: {e}")
        # Fallback: FIFO de control (solo si el server fuera lanzado fuera del panel)
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
        # PZ no devuelve una respuesta estructurada: la salida llega por la consola.
        return f"[PZ-Server] Comando enviado a la consola: {cmd}"

    async def save_world(self) -> str:
        await self.broadcast_log("[PZ-Server] Guardando mundo... (save)")
        await self._write_console("save")
        return "[PZ-Server] save enviado."

    async def broadcast(self, message: str) -> str:
        safe = message.replace('"', '\\"')
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
            await self.save_world()
            await asyncio.sleep(2)
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
        await self.broadcast_log("[PZ-Server] Servidor de Project Zomboid detenido.")
        return True

    async def restart_server(self) -> bool:
        await self.stop_server()
        await asyncio.sleep(3)
        self._intentional_stop = False
        return await self.start_server()


process_manager = ProcessManager()
