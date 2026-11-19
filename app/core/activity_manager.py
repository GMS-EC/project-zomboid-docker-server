import csv
import io
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import deque

from app.config import settings
from app.core.fs_utils import atomic_write_json

MAX_ENTRIES = 1500
RETENTION_DAYS = 7

_CATEGORY_ALIASES = {
    "console": {"console", "consola"},
    "server": {"server", "servidor", "pz", "instalación", "instalacion"},
    "backup": {"backup", "backups", "respaldo", "respaldos"},
    "update": {"update", "updates", "actualización", "actualizacion", "mods", "instalación", "instalacion"},
    "security": {"security", "seguridad"},
    "tasks": {"tasks", "task", "tarea", "tareas"},
    "player": {"player", "players", "jugador", "jugadores"},
    "file": {"file", "files", "archivo", "archivos"},
    "settings": {"settings", "configuración", "configuracion", "ajustes"},
    "webhooks": {"webhooks", "webhook"},
}


def _normalize_category_key(cat: str) -> str:
    low = (cat or "").strip().lower()
    for norm, aliases in _CATEGORY_ALIASES.items():
        if low in aliases:
            return norm
    return low or "general"


class ActivityManager:
    """Bitácora de actividad del panel (Auditoría, consola y eventos del sistema)."""

    def __init__(self, log_file: Optional[Path] = None):
        self.file: Path = Path(log_file) if log_file else (settings.panel_dir / "activity.json")
        self._entries: deque = deque(maxlen=MAX_ENTRIES)
        self._next_id: int = 1
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self.file.exists():
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    normalized: List[Dict[str, Any]] = []
                    max_id = 0
                    for idx, item in enumerate(data[-MAX_ENTRIES:], start=1):
                        if not isinstance(item, dict):
                            continue
                        eid = int(item.get("id") or idx)
                        max_id = max(max_id, eid)
                        detail = str(item.get("detail") or item.get("details") or item.get("message") or "")
                        entry = dict(item)
                        entry["id"] = eid
                        entry.setdefault("detail", detail)
                        entry.setdefault("details", detail)
                        entry.setdefault("message", detail)
                        entry.setdefault("action", entry.get("category", "Evento"))
                        entry.setdefault("user", "Sistema")
                        entry.setdefault("status", "success")
                        normalized.append(entry)
                    self._entries = deque(normalized, maxlen=MAX_ENTRIES)
                    self._next_id = max_id + 1
                    self.prune_expired(RETENTION_DAYS)
            except Exception:
                self._entries = deque(maxlen=MAX_ENTRIES)

    def _persist(self) -> None:
        try:
            atomic_write_json(self.file, list(self._entries), indent=2)
        except Exception:
            pass

    def prune_expired(self, max_age_days: int = RETENTION_DAYS) -> int:
        if max_age_days <= 0:
            return 0
        cutoff = time.time() - (max_age_days * 86400)
        before = len(self._entries)
        kept = []
        for e in self._entries:
            ts_val = e.get("created_at") or e.get("ts")
            if ts_val is not None:
                try:
                    if float(ts_val) >= cutoff:
                        kept.append(e)
                    continue
                except (TypeError, ValueError):
                    pass
            kept.append(e)
        pruned = before - len(kept)
        if pruned > 0:
            self._entries = deque(kept, maxlen=MAX_ENTRIES)
        return pruned

    def log(
        self,
        category: str,
        detail: str,
        user: str = "Sistema",
        action: str = "",
        status: str = "success",
    ) -> Dict[str, Any]:
        with self._lock:
            now = datetime.now()
            now_ts = time.time()
            entry = {
                "id": self._next_id,
                "timestamp": now.strftime("%d/%m/%Y %H:%M:%S"),
                "iso": now.isoformat(),
                "created_at": now_ts,
                "ts": int(now_ts),
                "category": category,
                "action": action or category,
                "detail": detail,
                "details": detail,
                "message": detail,
                "user": user or "Sistema",
                "status": status or "success",
            }
            self._next_id += 1
            self._entries.appendleft(entry)
            self._persist()
            return entry

    def get_logs(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        with self._lock:
            self.prune_expired(RETENTION_DAYS)
            entries = list(self._entries)

            counts: Dict[str, int] = {
                "all": len(entries),
                "console": 0,
                "server": 0,
                "backup": 0,
                "update": 0,
                "security": 0,
                "tasks": 0,
                "player": 0,
                "file": 0,
                "settings": 0,
                "webhooks": 0,
            }
            for e in entries:
                norm = _normalize_category_key(e.get("category", ""))
                if norm in counts:
                    counts[norm] += 1

            filtered = entries
            if category and category != "all":
                target_norm = _normalize_category_key(category)
                filtered = [
                    e for e in filtered
                    if _normalize_category_key(e.get("category", "")) == target_norm
                    or str(e.get("category", "")).lower() == category.lower()
                ]

            if search and search.strip():
                q = search.strip().lower()
                filtered = [
                    e for e in filtered
                    if q in str(e.get("action", "")).lower()
                    or q in str(e.get("detail", "")).lower()
                    or q in str(e.get("message", "")).lower()
                    or q in str(e.get("category", "")).lower()
                    or q in str(e.get("user", "")).lower()
                    or q in str(e.get("timestamp", "")).lower()
                ]

            total = len(filtered)
            paginated = filtered[offset: offset + limit]
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "counts": counts,
                "logs": paginated,
            }

    def clear(self) -> bool:
        with self._lock:
            self._entries.clear()
            self._persist()
            return True

    @staticmethod
    def _csv_safe(val: Any) -> str:
        s = str(val) if val is not None else ""
        if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{s}"
        return s

    def export_csv(self) -> str:
        with self._lock:
            output = io.StringIO()
            output.write("\ufeff")
            writer = csv.writer(output)
            writer.writerow(["id", "timestamp", "category", "action", "detail", "user", "status"])
            for e in self._entries:
                writer.writerow([
                    self._csv_safe(e.get("id", "")),
                    self._csv_safe(e.get("timestamp", "")),
                    self._csv_safe(e.get("category", "")),
                    self._csv_safe(e.get("action", e.get("category", ""))),
                    self._csv_safe(e.get("detail") or e.get("message") or ""),
                    self._csv_safe(e.get("user", "Sistema")),
                    self._csv_safe(e.get("status", "success")),
                ])
            return output.getvalue()

    def export_logs(self, format_type: str = "csv") -> str:
        with self._lock:
            if format_type == "json":
                return json.dumps(list(self._entries), indent=2, ensure_ascii=False)
            if format_type == "csv":
                return self.export_csv()
            lines = [
                "==================================================",
                " PZ SERVER MANAGER - REGISTRO DE AUDITORÍA",
                f" Exportado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
                f" Total de eventos: {len(self._entries)}",
                "==================================================\n",
            ]
            for e in self._entries:
                ts = e.get("timestamp", "")
                cat = str(e.get("category") or "").upper().ljust(10)
                st = str(e.get("status", "info")).upper()
                user = e.get("user", "Sistema")
                detail = e.get("detail") or e.get("message") or ""
                lines.append(f"[{ts}] [{cat}] [{st}] ({user}) {detail}")
            return "\n".join(lines)


activity_manager = ActivityManager()
