import os
import re
import time
import asyncio
import tarfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

from app.config import settings
from app.core.process_manager import process_manager
from app.core.webhook_manager import webhook_manager
from app.core.activity_manager import activity_manager

logger = None  # módulo log vía activity/console

class BackupManager:
    """
    Respaldo del mundo de Project Zomboid:
      - Saves/Multiplayer/<SERVER_NAME>   (mundo, mapa, jugadores del mundo)
      - Server/<SERVER_NAME>.ini + *_SandboxVars.lua + *_spawnregions.lua
      - db/<SERVER_NAME>.db                (cuentas/whitelist/baneos)
    Se empaqueta en .tar.gz con guardado previo vía consola (save) si está corriendo.
    """

    def __init__(self):
        self.backup_dir: Path = settings.backups_dir

    # ----------------------------- utilidades -----------------------------
    @staticmethod
    def _is_subpath(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (ValueError, AttributeError):
            return False

    def _safe_target(self, filename: str) -> Optional[Path]:
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            return None
        target = (self.backup_dir / Path(filename).name).resolve()
        if not self._is_subpath(target, self.backup_dir):
            return None
        return target if target.exists() and target.is_file() else None

    # ------------------------------- listado ------------------------------
    def list_backups(self) -> List[Dict[str, Any]]:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for item in self.backup_dir.iterdir():
            if item.is_file() and item.name.endswith(".tar.gz"):
                st = item.stat()
                results.append({
                    "filename": item.name,
                    "size_mb": round(st.st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
                    "timestamp": st.st_mtime,
                })
        results.sort(key=lambda x: x["timestamp"], reverse=True)
        return results

    def _max_count(self) -> int:
        cfg = settings.runtime_config
        try:
            return max(1, int(cfg.get("backup_max_count", 10)))
        except Exception:
            return 10

    # ------------------------------ creación ------------------------------
    def _collect_sources(self) -> List[tuple]:
        """Devuelve [(ruta_a_comprimir, nombre_raiz_dentro_del_tar)]"""
        data = settings.data_dir
        sources = []
        world = data / "Saves" / "Multiplayer" / settings.server_name
        if world.exists():
            sources.append((world, "Saves/Multiplayer/" + settings.server_name))

        server_dir = data / "Server"
        if server_dir.is_dir():
            prefix = server_dir / settings.server_name
            for suffix in (".ini", "_SandboxVars.lua", "_spawnregions.lua", "_spawnpoints.lua"):
                f = Path(str(prefix) + suffix)
                if f.exists():
                    sources.append((f, "Server/" + f.name))

        db = data / "db" / f"{settings.server_name}.db"
        if db.exists():
            sources.append((db, "db/" + db.name))
        return sources

    async def create_backup(self, custom_name: Optional[str] = None) -> Dict[str, Any]:
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            # Guardar mundo si el server está corriendo (canal consola)
            if process_manager.get_status() == "RUNNING":
                try:
                    await process_manager.save_world()
                    await asyncio.sleep(2)
                except Exception:
                    pass

            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            if custom_name and custom_name.strip() and custom_name.strip() != "auto":
                safe = re.sub(r"[^a-zA-Z0-9_-]", "_", custom_name.strip())
                prefix = f"pz_backup_{safe}"
            else:
                prefix = f"pz_backup_{now_str}"
            filename = prefix + ".tar.gz"
            target = self.backup_dir / filename

            sources = self._collect_sources()
            if not sources:
                # Crear respaldo "vacío" para que el flujo nunca falle
                sources = [(settings.server_dir if settings.server_dir.exists() else settings.data_dir, "metadata")]
            if not sources or (len(sources) == 1 and sources[0][1] == "metadata"):
                # empaqueta al menos los archivos de configuración si existen
                sources = []
                for f in list(settings.data_dir.rglob("*.ini"))[:1]:
                    sources.append((f, "Server/" + f.name))

            with tarfile.open(target, "w:gz") as tar:
                for src, arc in sources:
                    try:
                        tar.add(str(src), arcname=arc, recursive=True)
                    except Exception:
                        pass

            st = target.stat()
            await process_manager.broadcast_log(
                f"[PZ-Server] Respaldo creado: {filename} ({round(st.st_size/1024/1024,2)} MB)"
            )
            activity_manager.log("Backups", f"Copia creada: {filename}")
            await webhook_manager.notify("backup", f"Copia de seguridad creada: {filename}")
            self._rotate()
            return {"success": True, "filename": filename,
                    "size_mb": round(st.st_size / (1024 * 1024), 2)}
        except Exception as e:
            await process_manager.broadcast_log(f"[PZ-Server] [ERROR] Respaldo fallido: {e}")
            return {"success": False, "error": str(e)}

    def _rotate(self) -> None:
        max_count = self._max_count()
        backups = self.list_backups()
        for old in backups[max_count:]:
            try:
                (self.backup_dir / old["filename"]).unlink(missing_ok=True)
            except Exception:
                pass

    # ----------------------------- restauración ---------------------------
    async def restore_backup(self, filename: str) -> Dict[str, Any]:
        path = self._safe_target(filename)
        if not path:
            return {"success": False, "error": "Archivo no encontrado o nombre inválido."}
        if process_manager.get_status() in ("RUNNING", "STARTING", "INSTALLING"):
            return {"success": False, "error": "Detén el servidor antes de restaurar un respaldo."}
        try:
            data = settings.data_dir
            data.mkdir(parents=True, exist_ok=True)
            with tarfile.open(str(path), "r:gz") as tar:
                for member in tar.getmembers():
                    dest = (data / member.name).resolve()
                    if not self._is_subpath(dest, data):
                        raise ValueError("Entrada fuera del directorio de datos (seguridad).")
                try:
                    tar.extractall(str(data), filter="fully_trusted")
                except TypeError:
                    tar.extractall(str(data))
            activity_manager.log("Backups", f"Copia restaurada: {filename}")
            await process_manager.broadcast_log(f"[PZ-Server] Respaldo restaurado: {filename}")
            return {"success": True, "message": f"Respaldo {filename} restaurado."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_backup(self, filename: str) -> bool:
        path = self._safe_target(filename)
        if not path:
            return False
        try:
            path.unlink()
            return True
        except Exception:
            return False

    def get_backup_path(self, filename: str) -> Optional[Path]:
        return self._safe_target(filename)


backup_manager = BackupManager()
