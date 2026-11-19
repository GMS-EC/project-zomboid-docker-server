import os
import re
import uuid
import json
import asyncio
import tarfile
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from fastapi import HTTPException

from app.config import settings
from app.core.fs_utils import PROTECTED_INTERNAL_FILES, atomic_write_json, format_size
from app.core.process_manager import process_manager
from app.core.webhook_manager import webhook_manager
from app.core.activity_manager import activity_manager


SCOPE_LABELS = {
    "full": "Completo (Mundo + Config + DB)",
    "world": "Solo Mundo (Saves)",
    "config": "Solo Config y DB",
    "custom": "Personalizado",
}


class BackupManager:
    """Respaldo y restauración del servidor PZ con alcances (full, world, config, custom) y políticas."""

    META_FILENAME = ".backups_meta.json"

    def __init__(self):
        self.backup_dir: Path = settings.backups_dir
        self._job_lock = threading.Lock()
        self.active_backup: Optional[Dict[str, Any]] = None

    @property
    def progress(self) -> Dict[str, Any]:
        with self._job_lock:
            cur = dict(self.active_backup) if self.active_backup else None
        if not cur:
            return {
                "is_running": False,
                "status": "idle",
                "stage": "idle",
                "job_id": None,
                "filename": None,
                "size_formatted": None,
                "size_bytes": 0,
                "error": None,
            }
        return {
            "is_running": bool(cur.get("is_running")),
            "status": cur.get("status", "idle"),
            "stage": cur.get("stage", "idle"),
            "job_id": cur.get("job_id"),
            "filename": cur.get("filename"),
            "size_formatted": cur.get("size_formatted"),
            "size_bytes": cur.get("size_bytes", 0),
            "origin": cur.get("origin"),
            "is_auto": cur.get("is_auto"),
            "scope": cur.get("scope"),
            "scope_label": cur.get("scope_label"),
            "created_at": cur.get("created_at"),
            "error": cur.get("error"),
        }

    def try_start_job(self, job_id: str, stage: str = "preparing") -> bool:
        with self._job_lock:
            if self.active_backup and self.active_backup.get("is_running"):
                return False
            self.active_backup = {
                "is_running": True,
                "status": "running",
                "stage": stage,
                "job_id": job_id,
                "filename": None,
                "size_formatted": None,
                "size_bytes": 0,
                "error": None,
            }
            return True

    def update_job(self, job_id: Optional[str] = None, **fields: Any) -> None:
        with self._job_lock:
            if self.active_backup is None:
                self.active_backup = {}
            if job_id and self.active_backup.get("job_id") not in (None, job_id):
                return
            self.active_backup.update(fields)

    @property
    def _meta_file(self) -> Path:
        return self.backup_dir / self.META_FILENAME

    def _load_meta(self) -> Dict[str, Dict[str, Any]]:
        if not self._meta_file.exists():
            return {}
        try:
            data = json.loads(self._meta_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_meta(self, meta: Dict[str, Dict[str, Any]]) -> None:
        try:
            atomic_write_json(self._meta_file, meta, indent=2)
        except Exception:
            pass

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

    def list_backups(self) -> List[Dict[str, Any]]:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        meta = self._load_meta()
        results = []
        for item in self.backup_dir.iterdir():
            if item.is_file() and item.name.endswith(".tar.gz"):
                st = item.stat()
                m = meta.get(item.name, {})
                scope = m.get("scope") if m.get("scope") in SCOPE_LABELS else "full"
                origin = m.get("origin") or ("auto" if "_auto" in item.name.lower() else "manual")
                results.append({
                    "filename": item.name,
                    "size_bytes": st.st_size,
                    "size_mb": round(st.st_size / (1024 * 1024), 2),
                    "size_formatted": format_size(st.st_size),
                    "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
                    "timestamp": st.st_mtime,
                    "scope": scope,
                    "scope_label": SCOPE_LABELS.get(scope, SCOPE_LABELS["full"]),
                    "origin": origin,
                    "is_auto": origin == "auto",
                })
        results.sort(key=lambda x: x["timestamp"], reverse=True)
        return results

    def _max_count(self) -> int:
        cfg = settings.runtime_config
        try:
            return max(1, int(cfg.get("backup_max_count", 10)))
        except Exception:
            return 10

    def get_available_targets(self) -> List[Dict[str, Any]]:
        targets: List[Dict[str, Any]] = []
        excluded = {"backups", ".git", ".idea", "__pycache__"}
        data_dir = settings.data_dir
        if not data_dir.exists():
            return targets
        try:
            for item in sorted(data_dir.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if (
                    item.name in excluded
                    or item.name.lower() in PROTECTED_INTERNAL_FILES
                    or item.name.endswith((".tmp", ".pid"))
                ):
                    continue
                sz = 0
                if item.is_file():
                    try:
                        sz = item.stat().st_size
                    except Exception:
                        pass
                elif item.is_dir():
                    try:
                        for r, _, fs in os.walk(item):
                            for f in fs:
                                try:
                                    sz += os.path.getsize(os.path.join(r, f))
                                except Exception:
                                    pass
                    except Exception:
                        pass
                low = item.name.lower()
                if low in ("saves", "multiplayer") or "world" in low:
                    cat = "world"
                elif low in ("mods", "workshop", "lua"):
                    cat = "plugin"
                elif low in ("server", "db") or low.endswith((".ini", ".lua", ".json")):
                    cat = "config"
                else:
                    cat = "other"
                fmt = format_size(sz)
                targets.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size_bytes": sz,
                    "size_formatted": fmt,
                    "size_fmt": fmt,
                    "category": cat,
                    "type": cat,
                })
        except Exception:
            pass
        return targets

    def _collect_sources(
        self,
        scope: str = "full",
        targets: Optional[List[str]] = None,
    ) -> List[tuple]:
        data = settings.data_dir
        sources = []

        if scope == "custom" and targets:
            for t in targets:
                clean_t = Path(str(t)).name
                if not clean_t or clean_t.lower() in PROTECTED_INTERNAL_FILES:
                    continue
                cand = (data / clean_t).resolve()
                if self._is_subpath(cand, data) and cand.exists() and not cand.is_symlink():
                    sources.append((cand, clean_t))
            return sources

        if scope in ("full", "world"):
            world = data / "Saves" / "Multiplayer" / settings.server_name
            if world.exists():
                sources.append((world, "Saves/Multiplayer/" + settings.server_name))

        if scope in ("full", "config"):
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

    async def create_backup(
        self,
        custom_name: Optional[str] = None,
        scope: str = "full",
        targets: Optional[List[str]] = None,
        compression: bool = True,
        tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_scope = scope if scope in SCOPE_LABELS else "full"
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            if process_manager.get_status() == "RUNNING":
                try:
                    await process_manager.save_world()
                    await asyncio.sleep(2)
                except Exception:
                    pass

            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_tag = (tag or custom_name or "").strip()
            is_auto = raw_tag.lower() == "auto"
            if raw_tag and not is_auto and raw_tag.lower() != "manual":
                safe = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_tag)
                prefix = f"pz_backup_{safe}_{now_str}"
            elif is_auto:
                prefix = f"pz_backup_auto_{now_str}"
            else:
                prefix = f"pz_backup_{now_str}"
            filename = prefix + ".tar.gz"
            target = self.backup_dir / filename

            sources = self._collect_sources(scope=clean_scope, targets=targets)
            if not sources:
                for f in list(settings.data_dir.rglob("*.ini"))[:2]:
                    sources.append((f, "Server/" + f.name))

            tar_mode = "w:gz" if compression else "w"

            def _write_tar():
                with tarfile.open(target, tar_mode) as tar:
                    for src, arc in sources:
                        try:
                            tar.add(str(src), arcname=arc, recursive=True)
                        except Exception:
                            pass

            await asyncio.to_thread(_write_tar)

            st = target.stat()
            created_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            origin = "auto" if is_auto else "manual"
            meta = self._load_meta()
            meta[filename] = {
                "origin": origin,
                "scope": clean_scope,
                "created_at": created_at,
            }
            self._save_meta(meta)

            size_mb = round(st.st_size / (1024 * 1024), 2)
            size_fmt = format_size(st.st_size)
            await process_manager.broadcast_log(
                f"[PZ-Server] Respaldo creado: {filename} ({size_fmt}, alcance={clean_scope})"
            )
            activity_manager.log("Backups", f"Copia creada: {filename} ({size_fmt})")
            await webhook_manager.notify(
                "backup",
                f"Copia de seguridad creada: **{filename}** ({size_fmt} • {SCOPE_LABELS[clean_scope]})",
            )
            self.prune_backups()
            return {
                "success": True,
                "status": "success",
                "filename": filename,
                "size_bytes": st.st_size,
                "size_mb": size_mb,
                "size_formatted": size_fmt,
                "scope": clean_scope,
                "scope_label": SCOPE_LABELS[clean_scope],
                "origin": origin,
                "is_auto": is_auto,
                "created_at": created_at,
            }
        except Exception as e:
            await process_manager.broadcast_log(f"[PZ-Server] [ERROR] Respaldo fallido: {e}")
            return {"success": False, "error": str(e)}

    def prune_backups(self, max_count: Optional[int] = None) -> int:
        limit = max(1, int(max_count)) if max_count is not None else self._max_count()
        backups = self.list_backups()
        meta = self._load_meta()
        removed = 0
        changed = False
        for old in backups[limit:]:
            try:
                (self.backup_dir / old["filename"]).unlink(missing_ok=True)
                removed += 1
                if old["filename"] in meta:
                    meta.pop(old["filename"], None)
                    changed = True
            except Exception:
                pass
        if changed:
            self._save_meta(meta)
        return removed

    async def restore_backup(self, filename: str) -> Dict[str, Any]:
        path = self._safe_target(filename)
        if not path:
            return {"success": False, "error": "Archivo no encontrado o nombre inválido."}
        if process_manager.get_status() in ("RUNNING", "STARTING", "INSTALLING"):
            return {"success": False, "error": "Detén el servidor antes de restaurar un respaldo."}
        try:
            data = settings.data_dir
            data.mkdir(parents=True, exist_ok=True)
            with tarfile.open(str(path), "r:*") as tar:
                for member in tar.getmembers():
                    if member.issym() or member.islnk():
                        raise ValueError("Entrada de enlace simbólico no permitida.")
                    dest = (data / member.name).resolve()
                    if not self._is_subpath(dest, data):
                        raise ValueError("Entrada fuera del directorio de datos (seguridad).")
                try:
                    tar.extractall(str(data), filter="data")
                except TypeError:
                    tar.extractall(str(data))
            activity_manager.log("Backups", f"Copia restaurada: {filename}")
            await process_manager.broadcast_log(f"[PZ-Server] Respaldo restaurado: {filename}")
            return {"success": True, "status": "success", "message": f"Respaldo {filename} restaurado."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Políticas de Respaldo (estilo Dockraft) ---
    def _default_policy_from_config(self) -> Dict[str, Any]:
        cfg = settings.runtime_config
        scope = cfg.get("backup_scope", "full")
        if scope not in SCOPE_LABELS:
            scope = "full"
        return {
            "id": "default",
            "name": "Respaldo por Defecto",
            "scope": scope,
            "targets": list(cfg.get("backup_targets") or []),
            "compression": bool(cfg.get("backup_compression", True)),
            "stop_server": bool(cfg.get("backup_stop_server", False)),
            "pre_command": str(cfg.get("backup_pre_command") or "").strip(),
            "post_command": str(cfg.get("backup_post_command") or "").strip(),
        }

    def get_policies(self) -> List[Dict[str, Any]]:
        raw = settings.runtime_config.get("backup_policies")
        if isinstance(raw, list) and len(raw) > 0:
            cleaned: List[Dict[str, Any]] = []
            for p in raw:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "").strip() or uuid.uuid4().hex[:8]
                scope = p.get("scope", "full")
                if scope not in SCOPE_LABELS:
                    scope = "full"
                cleaned.append({
                    "id": pid,
                    "name": str(p.get("name") or "Política de Respaldo").strip() or "Política de Respaldo",
                    "scope": scope,
                    "targets": list(p.get("targets") or []),
                    "compression": bool(p.get("compression", True)),
                    "stop_server": bool(p.get("stop_server", False)),
                    "pre_command": str(p.get("pre_command") or "").strip(),
                    "post_command": str(p.get("post_command") or "").strip(),
                })
            if cleaned:
                return cleaned
        return [self._default_policy_from_config()]

    def get_policy(self, policy_id: Optional[str] = None) -> Dict[str, Any]:
        policies = self.get_policies()
        if policy_id:
            for p in policies:
                if p["id"] == policy_id:
                    return p
        return policies[0]

    def save_policy(self, policy_data: Dict[str, Any]) -> Dict[str, Any]:
        policies = self.get_policies()
        pid = str(policy_data.get("id") or "").strip()
        scope = policy_data.get("scope", "full")
        if scope not in SCOPE_LABELS:
            scope = "full"
        name = str(policy_data.get("name") or "").strip() or "Política de Respaldo"
        entry = {
            "id": pid or uuid.uuid4().hex[:8],
            "name": name,
            "scope": scope,
            "targets": list(policy_data.get("targets") or []),
            "compression": bool(policy_data.get("compression", True)),
            "stop_server": bool(policy_data.get("stop_server", False)),
            "pre_command": str(policy_data.get("pre_command") or "").strip(),
            "post_command": str(policy_data.get("post_command") or "").strip(),
        }

        idx = next((i for i, p in enumerate(policies) if p["id"] == entry["id"]), None)
        if idx is not None:
            policies[idx] = entry
        else:
            if len(policies) >= 4:
                raise HTTPException(status_code=400, detail="Solo puedes tener hasta 4 políticas de respaldo.")
            policies.append(entry)

        primary = policies[0]
        settings.save_runtime_config({
            "backup_policies": policies,
            "backup_scope": primary["scope"],
            "backup_targets": primary["targets"],
            "backup_compression": primary["compression"],
            "backup_stop_server": primary["stop_server"],
            "backup_pre_command": primary["pre_command"],
            "backup_post_command": primary["post_command"],
        })
        return entry

    def delete_policy(self, policy_id: str) -> List[Dict[str, Any]]:
        policies = self.get_policies()
        if len(policies) <= 1:
            raise HTTPException(status_code=400, detail="Debe existir al menos una política de respaldo.")
        remaining = [p for p in policies if p["id"] != policy_id]
        if len(remaining) == len(policies):
            raise HTTPException(status_code=404, detail="Política de respaldo no encontrada.")
        primary = remaining[0]
        settings.save_runtime_config({
            "backup_policies": remaining,
            "backup_scope": primary["scope"],
            "backup_targets": primary["targets"],
            "backup_compression": primary["compression"],
            "backup_stop_server": primary["stop_server"],
            "backup_pre_command": primary["pre_command"],
            "backup_post_command": primary["post_command"],
        })
        return remaining

    def delete_backup(self, filename: str) -> bool:
        path = self._safe_target(filename)
        if not path:
            return False
        try:
            path.unlink()
            meta = self._load_meta()
            if filename in meta:
                meta.pop(filename, None)
                self._save_meta(meta)
            return True
        except Exception:
            return False

    def get_backup_path(self, filename: str) -> Optional[Path]:
        return self._safe_target(filename)


backup_manager = BackupManager()
