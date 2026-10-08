import json
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from collections import deque

from app.config import settings
from app.core.fs_utils import atomic_write_json

MAX_ENTRIES = 500

class ActivityManager:
    """Bitácora de actividad del panel (para la pestaña Auditoría)."""

    def __init__(self):
        self.file: Path = settings.panel_dir / "activity.json"
        self._entries: deque = deque(maxlen=MAX_ENTRIES)
        self._load()

    def _load(self) -> None:
        if self.file.exists():
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._entries = deque(data[-MAX_ENTRIES:], maxlen=MAX_ENTRIES)
            except Exception:
                self._entries = deque(maxlen=MAX_ENTRIES)

    def _persist(self) -> None:
        try:
            atomic_write_json(self.file, list(self._entries), indent=2)
        except Exception:
            pass

    def log(self, category: str, detail: str, user: str = "Sistema") -> None:
        entry = {
            "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "ts": int(time.time()),
            "category": category,
            "user": user,
            "detail": detail,
        }
        self._entries.appendleft(entry)
        self._persist()

    def get_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        return list(self._entries)[:limit]


activity_manager = ActivityManager()
