import time
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from app.config import settings
from app.core.process_manager import process_manager
from app.core.backup_manager import backup_manager
from app.core.webhook_manager import webhook_manager
from app.core.activity_manager import activity_manager

TICK_SECONDS = 15


def _cfg() -> Dict[str, Any]:
    c = settings.runtime_config
    return {
        "schedule_enabled": bool(c.get("schedule_enabled", False)),
        "schedule_start": c.get("schedule_start", "20:00"),
        "schedule_stop": c.get("schedule_stop", "00:00"),
        "schedule_warn_mins": int(c.get("schedule_warn_mins", 10) or 10),
        "auto_backup_enabled": bool(c.get("auto_backup_enabled", True)),
        "auto_backup_interval_hours": int(c.get("auto_backup_interval_hours", 6) or 6),
        "backup_max_count": int(c.get("backup_max_count", 10) or 10),
        "auto_restart_hours": int(c.get("auto_restart_hours", 0) or 0),
        "restart_warn_mins": int(c.get("restart_warn_mins", 5) or 5),
    }


class TaskScheduler:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.ticks = 0
        self.errors = 0
        self.error_msg = ""
        self._last_backup_ts: float = time.time()
        self._last_restart_ts: float = time.time()
        self._busy: bool = False

    # ------------------------------------------------------------- api
    def get_config(self) -> Dict[str, Any]:
        return _cfg()

    def save_config(self, payload: Dict[str, Any]) -> None:
        allowed = set(_cfg().keys())
        updates = {k: v for k, v in payload.items() if k in allowed}
        settings.save_runtime_config(updates)

    def get_status(self) -> Dict[str, Any]:
        c = _cfg()
        sched = "Desactivado"
        if c["schedule_enabled"]:
            sched = f"{c['schedule_start']}–{c['schedule_stop']}"
        return {
            "running": self._running,
            "ticks": self.ticks,
            "errors": self.errors,
            "schedule": sched,
            "backup": f"Cada {c['auto_backup_interval_hours']}h" if c["auto_backup_enabled"] else "Off",
            "restart": f"Cada {c['auto_restart_hours']}h" if c["auto_restart_hours"] else "Off",
            "error_msg": self.error_msg,
        }

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
        last_sched_state: Optional[bool] = None
        while self._running:
            try:
                self.ticks += 1
                c = _cfg()

                # Respaldo automático
                if c["auto_backup_enabled"] and c["auto_backup_interval_hours"] > 0:
                    if time.time() - self._last_backup_ts >= c["auto_backup_interval_hours"] * 3600:
                        self._last_backup_ts = time.time()
                        await backup_manager.create_backup("auto")

                # Reinicio automático (cada N horas)
                if c["auto_restart_hours"] and c["auto_restart_hours"] > 0:
                    if time.time() - self._last_restart_ts >= c["auto_restart_hours"] * 3600:
                        self._last_restart_ts = time.time()
                        asyncio.create_task(self._safe_restart(c["restart_warn_mins"]))

                # Power schedule (encendido/apagado diario)
                if c["schedule_enabled"]:
                    now_h, now_m = datetime.now().hour, datetime.now().minute
                    now_min = now_h * 60 + now_m
                    start = self._parse_hhmm(c["schedule_start"], 20 * 60)
                    stop = self._parse_hhmm(c["schedule_stop"], 0)
                    in_window = (start <= stop and start <= now_min < stop) or (start > stop and (now_min >= start or now_min < stop))
                    if last_sched_state is not None and in_window != last_sched_state:
                        if in_window:
                            if process_manager.get_status() == "OFFLINE":
                                await process_manager.start_server()
                                await webhook_manager.notify("start")
                        else:
                            # Fuera de la ventana: avisar y apagar con guardado
                            asyncio.create_task(self._safe_stop(c["schedule_warn_mins"]))
                    last_sched_state = in_window

            except Exception as e:
                self.errors += 1
                self.error_msg = str(e)
            await asyncio.sleep(TICK_SECONDS)

    @staticmethod
    def _parse_hhmm(val: str, default: int) -> int:
        try:
            h, m = val.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return default

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
            await webhook_manager.notify("start")
        except Exception as e:
            await process_manager.broadcast_log(f"[PZ-Server] [ERROR] Reinicio automático: {e}")
        finally:
            self._busy = False

    async def _safe_stop(self, warn_minutes: int = 10):
        if self._busy:
            return
        self._busy = True
        try:
            if process_manager.get_status() != "RUNNING":
                return
            await process_manager.broadcast(
                f"El servidor se apagará en {warn_minutes} minutos (horario). Guarda tu progreso.")
            await asyncio.sleep(min(warn_minutes, 15) * 60)
            await process_manager.stop_server(grace_seconds=30)
            await webhook_manager.notify("shutdown")
        except Exception as e:
            await process_manager.broadcast_log(f"[PZ-Server] [ERROR] Apagado por horario: {e}")
        finally:
            self._busy = False

    async def trigger_safe_restart(self, minutes: int = 5):
        asyncio.create_task(self._safe_restart(minutes))
        return True


task_scheduler = TaskScheduler()
