import os
import json
import secrets
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent

# ¿Estamos dentro del contenedor (Linux con /home/steam) o en desarrollo local?
_IN_CONTAINER = Path("/home/steam").is_dir()


def _resolve_dir(env_name: str, container_path: str, local_relative: str) -> Path:
    """Resuelve un directorio: 1º variable de entorno, 2º ruta de contenedor,
    3º ruta local de desarrollo (Windows/macOS/Linux sin contenedor)."""
    env_val = os.getenv(env_name, "").strip()
    if env_val:
        p = Path(env_val)
    elif _IN_CONTAINER:
        p = Path(container_path)
    else:
        p = BASE_DIR / local_relative
    p.mkdir(parents=True, exist_ok=True)
    return p


class Settings:
    def __init__(self):
        # --- Directorios ----------------------------------------------------
        self.base_dir: Path = BASE_DIR
        self.panel_dir: Path = _resolve_dir("PZ_PANEL_DIR", "/app/data", "data")

        # Instalación del servidor dedicado (AppID 380870) / archivos No-Steam
        self.server_dir: Path = _resolve_dir(
            "PZ_SERVER_DIR", "/home/steam/steamcmd/pz", "dev-data/pz-server"
        )
        # Datos del mundo (equivalente a ~/Zomboid)
        self.data_dir: Path = _resolve_dir(
            "PZ_DATA_DIR", "/home/steam/Zomboid", "dev-data/zomboid"
        )
        # Copias de seguridad (Fase 3)
        self.backups_dir: Path = _resolve_dir(
            "PZ_BACKUPS_DIR", "/home/steam/pz-backups", "dev-data/pz-backups"
        )

        # Archivo de consola que escribe el servidor PZ en su cachedir
        self.console_log: Path = self.data_dir / "console.txt"

        # --- Panel web ------------------------------------------------------
        self.panel_port: int = int(os.getenv("PANEL_PORT", "8080"))
        self.admin_user: str = os.getenv("PANEL_USER", "admin")
        self.admin_password: str = os.getenv("PANEL_PASSWORD", "adminpassword")

        # --- Config persistente del panel (secret + preferencias) -----------
        self._config_file: Path = self.panel_dir / "pz_panel_config.json"
        self.runtime_config: Dict[str, Any] = self._load_runtime_config()

        # Secret Key persistente (env -> json -> nuevo)
        env_secret = os.getenv("SECRET_KEY", "").strip()
        if env_secret:
            self.secret_key = env_secret
        else:
            saved = str(self.runtime_config.get("secret_key", "")).strip()
            if saved:
                self.secret_key = saved
            else:
                self.secret_key = secrets.token_hex(32)
                self.runtime_config["secret_key"] = self.secret_key
                self.save_runtime_config({})

        # --- Servidor PZ: configuración de JUEGO (solo desde la interfaz web) ---
        # No se lee ninguna variable de entorno de juego: los valores base son
        # constantes y se sobrescriben desde Setup/Ajustes (runtime_config).
        self.in_container: bool = Path("/home/steam").is_dir()
        self._server_name: str = "servertest"
        self._admin_username: str = "admin"
        self._admin_ark_password: str = "adminpass"
        self._use_steam: bool = True
        self._update_on_start: bool = True
        self._autostart_server: bool = False
        self._override_launcher_memory: bool = True

        self._memory_min: str = "4g"
        self._memory_max: str = "6g"
        self._max_players: int = 16

        # Comandos extra para el lanzador PZ (a futuro, desde la web)
        self.additional_args: str = ""
        # Rama de Steam ("" = estable; "unstable"; "legacy41") — a futuro desde web
        self.branch: str = ""
        # RCON desactivado por defecto (se activará desde la web en el futuro)
        self.rcon_password: str = ""
        self.rcon_port: Optional[int] = 27015

        # Lanzador JVM: en B42 los args de memoria viven en ProjectZomboid64.json (vmArgs)
        self.launcher_json: Path = self.server_dir / "ProjectZomboid64.json"

        # Campos de presentación usados por el frontend
        self.world_label: str = "Knox County"
        self.timezone: str = os.getenv("TZ", "UTC")  # infra (zona horaria del contenedor)
        self.server_port: int = 16261
        self.direct_port: int = 16262

        # Marcadores de "mundo cargado / listo" en la consola (por build)
        markers = "SERVER STARTED,Server started,Server is up,world loaded"
        self.ready_markers: list = [m.strip() for m in markers.split(",") if m.strip()]

        # FIFO de control cuando el panel NO posee el proceso (modo solo-servidor)
        self.control_fifo: Path = Path(os.getenv("PZ_CONTROL_FIFO", "/run/pz/zomboid.control"))

        # Ruta al lanzador del server y scripts
        self.pz_run_script: Path = Path(os.getenv("PZ_RUN_SCRIPT", "/home/steam/scripts/pz_run.sh"))
        self.start_script: Path = Path(os.getenv("PZ_START_SCRIPT", "/home/steam/scripts/start.sh"))

    # ------------------------------------------------------------------ runtime
    def _rt(self, key: str, default: Any = None):
        v = self.runtime_config.get(key)
        return v if v is not None else default

    @staticmethod
    def _rt_bool(v: Any, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        if v is None:
            return default
        return bool(v)

    @property
    def server_name(self) -> str:
        return str(self._rt("server_name", self._server_name))

    @property
    def use_steam(self) -> bool:
        return self._rt_bool(self._rt("use_steam"), self._use_steam)

    @property
    def update_on_start(self) -> bool:
        return self._rt_bool(self._rt("update_on_start"), self._update_on_start)

    @property
    def autostart_server(self) -> bool:
        return self._rt_bool(self._rt("autostart_server"), self._autostart_server)

    @property
    def is_setup_done(self) -> bool:
        """Indica si el usuario completó la configuración inicial desde el panel web."""
        return self._rt_bool(self._rt("setup_completed"), False)

    @property
    def override_launcher_memory(self) -> bool:
        return self._rt_bool(self._rt("override_launcher_memory"), self._override_launcher_memory)

    @property
    def admin_username(self) -> str:
        return str(self._rt("admin_username", self._admin_username))

    @property
    def admin_ark_password(self) -> str:
        return str(self._rt("admin_password", self._admin_ark_password))

    @property
    def server_password(self) -> str:
        return str(self._rt("server_password", ""))

    @property
    def memory_min(self) -> str:
        return str(self._rt("memory_min", self._memory_min))

    @property
    def memory_max(self) -> str:
        return str(self._rt("memory_max", self._memory_max))

    @property
    def max_players(self) -> int:
        try:
            return int(self._rt("max_players", self._max_players))
        except (TypeError, ValueError):
            return self._max_players

    def save_wizard(self, payload: dict) -> None:
        updates = {}
        if "server_name" in payload and str(payload.get("server_name", "")).strip():
            updates["server_name"] = str(payload.get("server_name", "")).strip()
        if "use_steam" in payload:
            updates["use_steam"] = self._rt_bool(payload.get("use_steam"), self._use_steam)
        if "admin_username" in payload and str(payload.get("admin_username", "")).strip():
            updates["admin_username"] = str(payload.get("admin_username", "")).strip()
        if "admin_password" in payload and str(payload.get("admin_password", "")).strip():
            updates["admin_password"] = str(payload.get("admin_password", "")).strip()
        if "server_password" in payload:
            updates["server_password"] = str(payload.get("server_password", "")).strip()
        if "max_players" in payload and payload.get("max_players") not in (None, ""):
            try:
                updates["max_players"] = int(float(payload.get("max_players")))
            except (TypeError, ValueError):
                pass
        if "memory_min" in payload and str(payload.get("memory_min", "")).strip():
            updates["memory_min"] = str(payload.get("memory_min", "")).strip()
        if "memory_max" in payload and str(payload.get("memory_max", "")).strip():
            updates["memory_max"] = str(payload.get("memory_max", "")).strip()
        if "mod_ids" in payload:
            updates["mod_ids"] = str(payload.get("mod_ids", "")).strip()
        if "pvp" in payload:
            updates["pvp"] = bool(payload["pvp"])
        updates["setup_completed"] = True
        self.save_runtime_config(updates)

    def _load_runtime_config(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if self._config_file.exists():
            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        return data

    def save_runtime_config(self, updates: Dict[str, Any]) -> None:
        """Persiste cambios en la configuración de runtime del panel."""
        self.runtime_config.update(updates)
        self.panel_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._config_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.runtime_config, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._config_file)
        except Exception:
            pass

    @property
    def is_steam_mode(self) -> bool:
        return self.use_steam

    def is_installed(self) -> bool:
        """¿Existe el lanzador del servidor dedicado de PZ?"""
        for name in ("start-server.sh", "ProjectZomboid64", "ProjectZomboid32"):
            if (self.server_dir / name).exists():
                return True
        return False


settings = Settings()
