import os
import json
import secrets
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent

# Detecta ejecución dentro de Docker (/home/steam) frente a desarrollo local
_IN_CONTAINER = Path("/home/steam").is_dir()


def _resolve_dir(env_name: str, container_path: str, local_relative: str) -> Path:
    """Resuelve un directorio por variable de entorno, ruta de contenedor o ruta local."""
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
        self.base_dir: Path = BASE_DIR
        self.panel_dir: Path = _resolve_dir("PZ_PANEL_DIR", "/app/data", "data")
        self.server_dir: Path = _resolve_dir(
            "PZ_SERVER_DIR", "/home/steam/steamcmd/pz", "dev-data/pz-server"
        )
        self.data_dir: Path = _resolve_dir(
            "PZ_DATA_DIR", "/home/steam/Zomboid", "dev-data/zomboid"
        )
        self.backups_dir: Path = _resolve_dir(
            "PZ_BACKUPS_DIR", "/home/steam/pz-backups", "dev-data/pz-backups"
        )
        self.console_log: Path = self.data_dir / "console.txt"

        self.panel_port: int = int(os.getenv("PANEL_PORT", "8080"))
        self.admin_user: str = os.getenv("PANEL_USER", "admin")
        self.admin_password: str = os.getenv("PANEL_PASSWORD", "adminpassword")

        self.login_max_attempts: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
        self.login_cooldown_seconds: int = int(os.getenv("LOGIN_COOLDOWN_SECONDS", "600"))
        self.session_timeout_minutes: int = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))
        self.https_enabled: bool = os.getenv("HTTPS_ENABLED", "false").lower() in ("true", "1", "yes")
        self.trust_proxy_headers: bool = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in ("true", "1", "yes")
        _raw_proxies = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1")
        self.trusted_proxies: list[str] = [p.strip() for p in _raw_proxies.split(",") if p.strip()]

        self._config_file: Path = self.panel_dir / "pz_panel_config.json"
        self._revoked_tokens_file: Path = self.panel_dir / ".revoked_tokens.json"
        self.runtime_config: Dict[str, Any] = self._load_runtime_config()

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

        # Ajustes de juego persistidos desde la interfaz web
        self.in_container: bool = Path("/home/steam").is_dir()
        self._server_name: str = "servertest"
        self._admin_username: str = "admin"
        self._server_admin_password: str = "adminpass"
        self._use_steam: bool = True
        self._update_on_start: bool = True
        self._autostart_server: bool = False
        self._override_launcher_memory: bool = True

        self._memory_min: str = "4g"
        self._memory_max: str = "6g"
        self._max_players: int = 16
        self._additional_args: str = ""
        self._branch: str = ""
        self._rcon_password: str = ""
        self._rcon_port: int = 27015
        self._server_port: int = 16261
        self._direct_port: int = 16262
        self._disk_limit_gb: float = 0.0

        # Campos de presentación usados por el frontend
        self.world_label: str = "Knox County"
        self.timezone: str = os.getenv("TZ", "UTC")

        # Marcadores de "mundo cargado / listo" en la consola (por build)
        markers = "SERVER STARTED,Server started,Server is up,world loaded"
        self.ready_markers: list = [m.strip() for m in markers.split(",") if m.strip()]

        # FIFO de control cuando el panel NO posee el proceso
        self.control_fifo: Path = Path(os.getenv("PZ_CONTROL_FIFO", "/run/pz/zomboid.control"))

        # Ruta al lanzador del server
        self.pz_run_script: Path = Path(os.getenv("PZ_RUN_SCRIPT", "/home/steam/scripts/pz_run.sh"))

    @property
    def launcher_json(self) -> Path:
        return self.server_dir / "ProjectZomboid64.json"

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
    def server_admin_password(self) -> str:
        return str(self._rt("admin_password", self._server_admin_password))

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
            return max(1, int(self._rt("max_players", self._max_players)))
        except (TypeError, ValueError):
            return self._max_players

    @property
    def branch(self) -> str:
        return str(self._rt("branch", self._branch)).strip()

    @property
    def additional_args(self) -> str:
        return str(self._rt("additional_args", self._additional_args)).strip()

    @property
    def server_port(self) -> int:
        try:
            return int(self._rt("server_port", self._server_port))
        except (TypeError, ValueError):
            return self._server_port

    @property
    def direct_port(self) -> int:
        try:
            return int(self._rt("direct_port", self._direct_port))
        except (TypeError, ValueError):
            return self._direct_port

    @property
    def rcon_port(self) -> Optional[int]:
        try:
            return int(self._rt("rcon_port", self._rcon_port))
        except (TypeError, ValueError):
            return self._rcon_port

    @property
    def rcon_password(self) -> str:
        return str(self._rt("rcon_password", self._rcon_password))

    @property
    def disk_limit_gb(self) -> float:
        try:
            return float(self._rt("disk_limit_gb", self._disk_limit_gb) or 0.0)
        except (TypeError, ValueError):
            return self._disk_limit_gb

    def save_wizard(self, payload: dict) -> None:
        updates = {}
        if "server_name" in payload and str(payload.get("server_name", "")).strip():
            # Sanitizar nombre de sesión para evitar caracteres inválidos en nombres de archivo
            clean_name = "".join(
                c for c in str(payload.get("server_name", "")).strip()
                if c.isalnum() or c in ("_", "-")
            )
            if clean_name:
                updates["server_name"] = clean_name
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
                updates["max_players"] = max(1, int(float(payload.get("max_players"))))
            except (TypeError, ValueError):
                pass
        if "memory_min" in payload and str(payload.get("memory_min", "")).strip():
            updates["memory_min"] = str(payload.get("memory_min", "")).strip()
        if "memory_max" in payload and str(payload.get("memory_max", "")).strip():
            updates["memory_max"] = str(payload.get("memory_max", "")).strip()
        if "branch" in payload:
            updates["branch"] = str(payload.get("branch", "")).strip()
        if "additional_args" in payload:
            updates["additional_args"] = str(payload.get("additional_args", "")).strip()
        for int_key in ("server_port", "direct_port", "rcon_port"):
            if int_key in payload and payload.get(int_key) not in (None, ""):
                try:
                    updates[int_key] = int(payload[int_key])
                except (TypeError, ValueError):
                    pass
        if "rcon_password" in payload:
            updates["rcon_password"] = str(payload.get("rcon_password", "")).strip()
        if "disk_limit_gb" in payload and payload.get("disk_limit_gb") not in (None, ""):
            try:
                updates["disk_limit_gb"] = max(0.0, float(payload["disk_limit_gb"]))
            except (TypeError, ValueError):
                pass
        if "mod_ids" in payload:
            updates["mod_ids"] = str(payload.get("mod_ids", "")).strip()
        if "pvp" in payload:
            updates["pvp"] = self._rt_bool(payload["pvp"], False)
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

    def is_installed(self) -> bool:
        """¿Existe el lanzador del servidor dedicado de PZ?"""
        for name in ("start-server.sh", "ProjectZomboid64", "ProjectZomboid32"):
            if (self.server_dir / name).exists():
                return True
        return False


settings = Settings()
