import json
import uuid
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from app.config import settings
from app.core.fs_utils import atomic_write_json
from app.core.process_manager import process_manager
from app.core.backup_manager import backup_manager
from app.core.webhook_manager import webhook_manager
from app.core.activity_manager import activity_manager

TICK_SECONDS = 15


def _match_cron_field(field: str, value: int, min_v: int, max_v: int) -> bool:
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            return True
        if "/" in part:
            base, _, step_str = part.partition("/")
            try:
                step = max(1, int(step_str))
            except ValueError:
                continue
            if base == "*":
                if (value - min_v) % step == 0:
                    return True
            elif "-" in base:
                lo, _, hi = base.partition("-")
                try:
                    if int(lo) <= value <= int(hi) and (value - int(lo)) % step == 0:
                        return True
                except ValueError:
                    pass
        elif "-" in part:
            lo, _, hi = part.partition("-")
            try:
                if int(lo) <= value <= int(hi):
                    return True
            except ValueError:
                pass
        else:
            try:
                if int(part) == value:
                    return True
            except ValueError:
                pass
    return False


def _next_cron_dt(expr: str, base_dt: datetime) -> Optional[datetime]:
    """Calcula la próxima ejecución cron en Python puro (sin depender de croniter)."""
    try:
        from croniter import croniter  # type: ignore
        if croniter.is_valid(expr):
            return croniter(expr, base_dt).get_next(datetime)
    except Exception:
        pass

    fields = expr.strip().split()
    if len(fields) != 5:
        return None
    f_min, f_hour, f_dom, f_mon, f_dow = fields
    cur = base_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Busca hasta 32 días adelante (suficiente para cualquier cron diario/semanal/mensual común)
    for _ in range(32 * 24 * 60):
        py_dow = (cur.weekday() + 1) % 7  # 0=Domingo..6=Sábado
        if (
            _match_cron_field(f_min, cur.minute, 0, 59)
            and _match_cron_field(f_hour, cur.hour, 0, 23)
            and _match_cron_field(f_dom, cur.day, 1, 31)
            and _match_cron_field(f_mon, cur.month, 1, 12)
            and (_match_cron_field(f_dow, py_dow, 0, 6) or (py_dow == 0 and _match_cron_field(f_dow, 7, 0, 7)))
        ):
            return cur
        cur += timedelta(minutes=1)
    return None


class TaskScheduler:
    """Planificador de tareas programadas."""

    def __init__(self, tasks_file: Optional[Path] = None):
        self.tasks_file: Path = Path(tasks_file) if tasks_file else (settings.panel_dir / "tasks.json")
        self.tasks: List[Dict[str, Any]] = self._load_tasks()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.ticks = 0
        self.errors = 0
        self.error_msg = ""
        self._busy: bool = False

    def _load_tasks(self) -> List[Dict[str, Any]]:
        if self.tasks_file.exists():
            try:
                data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def _save_tasks(self) -> None:
        try:
            atomic_write_json(self.tasks_file, self.tasks, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------- tareas programadas
    def calculate_next_run(self, task: Dict[str, Any], from_dt: Optional[datetime] = None) -> Optional[str]:
        if not task.get("enabled", True):
            return None
        base_dt = from_dt or datetime.now()
        stype = task.get("schedule_type", "interval")
        if stype == "cron":
            nxt = _next_cron_dt(str(task.get("cron_expression") or "0 4 * * *"), base_dt)
            return nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None

        val = max(1, int(task.get("interval_value", 1) or 1))
        unit = str(task.get("interval_unit", "hours")).lower()
        mult = 60 if unit == "minutes" else (86400 if unit == "days" else 3600)
        secs = val * mult
        last_str = task.get("last_run")
        if last_str:
            try:
                last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
                nxt = datetime.fromtimestamp(last_dt.timestamp() + secs)
                if nxt > base_dt:
                    return nxt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        return datetime.fromtimestamp(base_dt.timestamp() + secs).strftime("%Y-%m-%d %H:%M:%S")

    def list_tasks(self) -> List[Dict[str, Any]]:
        res = []
        for t in self.tasks:
            copy_t = dict(t)
            copy_t["next_run"] = self.calculate_next_run(copy_t) if copy_t.get("enabled", True) else None
            res.append(copy_t)
        return res

    def create_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        task = {
            "id": uuid.uuid4().hex[:8],
            "name": str(data.get("name") or "Nueva Tarea").strip(),
            "action": str(data.get("action") or "command").strip(),
            "command": str(data.get("command") or "").strip(),
            "backup_policy_id": data.get("backup_policy_id"),
            "schedule_type": str(data.get("schedule_type") or "interval").strip(),
            "interval_value": max(1, int(data.get("interval_value", 1) or 1)),
            "interval_unit": str(data.get("interval_unit") or "hours").strip(),
            "cron_expression": str(data.get("cron_expression") or "0 4 * * *").strip(),
            "enabled": bool(data.get("enabled", True)),
            "last_run": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        task["next_run"] = self.calculate_next_run(task)
        self.tasks.append(task)
        self._save_tasks()
        activity_manager.log("Tareas", f"Tarea creada: {task['name']} ({task['action']})")
        return task

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        for t in self.tasks:
            if t.get("id") == task_id:
                copy_t = dict(t)
                copy_t["next_run"] = self.calculate_next_run(copy_t) if copy_t.get("enabled", True) else None
                return copy_t
        return None

    def update_task(self, task_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for t in self.tasks:
            if t.get("id") == task_id:
                if data.get("name") is not None:
                    t["name"] = str(data["name"]).strip() or t.get("name", "Tarea")
                if data.get("action") is not None:
                    t["action"] = str(data["action"]).strip()
                if data.get("command") is not None:
                    t["command"] = str(data["command"]).strip()
                if "backup_policy_id" in data:
                    t["backup_policy_id"] = data.get("backup_policy_id")
                if data.get("schedule_type") is not None:
                    t["schedule_type"] = str(data["schedule_type"]).strip()
                if data.get("interval_value") is not None:
                    t["interval_value"] = max(1, int(data["interval_value"] or 1))
                if data.get("interval_unit") is not None:
                    t["interval_unit"] = str(data["interval_unit"]).strip()
                if data.get("cron_expression") is not None:
                    t["cron_expression"] = str(data["cron_expression"]).strip()
                if data.get("enabled") is not None:
                    t["enabled"] = bool(data["enabled"])
                t["next_run"] = self.calculate_next_run(t) if t.get("enabled", True) else None
                self._save_tasks()
                activity_manager.log("Tareas", f"Tarea actualizada: {t['name']}")
                return dict(t)
        return None

    def toggle_task(self, task_id: str, enabled: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        for t in self.tasks:
            if t.get("id") == task_id:
                t["enabled"] = (not t.get("enabled", True)) if enabled is None else bool(enabled)
                t["next_run"] = self.calculate_next_run(t)
                self._save_tasks()
                return dict(t)
        return None

    def delete_task(self, task_id: str) -> bool:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.get("id") != task_id]
        if len(self.tasks) < before:
            self._save_tasks()
            activity_manager.log("Tareas", f"Tarea eliminada: {task_id}")
            return True
        return False

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        action = task.get("action", "command")
        tname = task.get("name", task.get("id"))
        res = {"success": True, "action": action, "task_id": task.get("id"), "message": ""}
        try:
            if action == "start":
                if process_manager.get_status() == "OFFLINE":
                    await process_manager.start_server()
                    res["message"] = "Servidor iniciado"
                else:
                    res["message"] = f"Servidor ya estaba {process_manager.get_status()}"
            elif action == "stop":
                if process_manager.get_status() != "OFFLINE":
                    await process_manager.stop_server()
                    res["message"] = "Servidor detenido"
                else:
                    res["message"] = "Servidor ya estaba apagado"
            elif action == "restart":
                await self._safe_restart(2)
                res["message"] = "Reinicio seguro ejecutado"
            elif action == "backup":
                policy = backup_manager.get_policy(task.get("backup_policy_id"))
                was_running = process_manager.get_status() == "RUNNING"
                pre_cmd = str(policy.get("pre_command") or "").strip()
                if was_running and pre_cmd:
                    await process_manager.send_command(pre_cmd)
                if was_running and policy.get("stop_server"):
                    await process_manager.stop_server()
                b = await backup_manager.create_backup(
                    tag="auto",
                    scope=policy.get("scope", "full"),
                    targets=policy.get("targets"),
                    compression=bool(policy.get("compression", True)),
                )
                if was_running and policy.get("stop_server"):
                    await process_manager.start_server()
                post_cmd = str(policy.get("post_command") or "").strip()
                if post_cmd and process_manager.get_status() == "RUNNING":
                    await process_manager.send_command(post_cmd)
                res["success"] = bool(b.get("success"))
                res["message"] = f"Respaldo: {b.get('filename', b.get('error', ''))}"
            elif action == "check_updates":
                if process_manager.get_status() == "OFFLINE":
                    ok = await process_manager.install_server()
                    res["success"] = ok
                    res["message"] = "Binarios actualizados" if ok else "Error comprobando actualizaciones"
                else:
                    res["message"] = "Servidor en ejecución; comprobación omitida"
            elif action == "save":
                msg = await process_manager.save_world()
                res["message"] = msg
            elif action == "command":
                cmd = str(task.get("command") or "").strip()
                if not cmd:
                    res["success"] = False
                    res["message"] = "Sin comando especificado"
                elif process_manager.get_status() == "OFFLINE":
                    res["message"] = f"Servidor apagado; comando '{cmd}' omitido"
                else:
                    res["message"] = await process_manager.send_command(cmd)
            else:
                res["success"] = False
                res["message"] = f"Acción desconocida: {action}"
        except Exception as e:
            res["success"] = False
            res["message"] = str(e)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for t in self.tasks:
            if t.get("id") == task.get("id"):
                t["last_run"] = now_str
                t["next_run"] = self.calculate_next_run(t)
                self._save_tasks()
                break

        activity_manager.log("Tareas", f"Tarea '{tname}' ejecutada: {res['message']}")
        return res

    async def run_task_now(self, task_id: str) -> Dict[str, Any]:
        for t in self.tasks:
            if t.get("id") == task_id:
                return await self.execute_task(t)
        raise ValueError(f"Tarea {task_id} no encontrada")

    # ------------------------------------------------------------- loop
    def start_loop(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())

    def stop_loop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while self._running:
            try:
                self.ticks += 1
                now_dt = datetime.now()
                for t in list(self.tasks):
                    if not t.get("enabled", True):
                        continue
                    next_str = t.get("next_run")
                    if not next_str:
                        t["next_run"] = self.calculate_next_run(t, from_dt=now_dt)
                        next_str = t.get("next_run")
                    if next_str:
                        try:
                            next_dt = datetime.strptime(next_str, "%Y-%m-%d %H:%M:%S")
                            if now_dt >= next_dt:
                                await self.execute_task(t)
                        except Exception:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.errors += 1
                self.error_msg = str(e)
            await asyncio.sleep(TICK_SECONDS)

    # ------------------------------------------------------- acciones
    async def _safe_restart(self, minutes: int = 5):
        if self._busy:
            return
        self._busy = True
        try:
            if process_manager.get_status() in ("RUNNING", "STARTING"):
                await process_manager.broadcast_log(f"[PZ-Server] Reinicio automático en {minutes} minutos.")
                await process_manager.broadcast(f"Reinicio del servidor en {minutes} minutos. Guarda tu progreso.")
                await webhook_manager.notify("restart", f"Reinicio en {minutes} min.")
                for m in range(minutes - 1, 0, -1):
                    await asyncio.sleep(60)
                    await process_manager.broadcast(f"Reinicio en {m} minuto(s).")
            await process_manager.stop_server(grace_seconds=30)
            await asyncio.sleep(3)
            await process_manager.start_server()
        except Exception as e:
            await process_manager.broadcast_log(f"[PZ-Server] [ERROR] Reinicio automático: {e}")
        finally:
            self._busy = False


task_scheduler = TaskScheduler()
