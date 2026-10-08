import httpx

from app.config import settings

LANG = {
    "es": {
        "start": "Servidor PZ 100% Online",
        "starting": "El servidor PZ está arrancando...",
        "shutdown": "El servidor PZ se ha detenido",
        "restart": "Reinicio programado del servidor PZ",
        "save": "Guardado del mundo completado",
        "backup": "Copia de seguridad",
        "players_join": "Jugador conectado",
        "players_leave": "Jugador desconectado",
        "test": "Notificación de prueba",
    },
    "en": {
        "start": "PZ Server 100% Online",
        "starting": "PZ server is starting...",
        "shutdown": "PZ server stopped",
        "restart": "Scheduled PZ server restart",
        "save": "World save completed",
        "backup": "Backup",
        "players_join": "Player joined",
        "players_leave": "Player left",
        "test": "Test notification",
    },
}


class WebhookManager:
    """Notificaciones a Discord usando la configuración persistida del panel."""

    def _config(self) -> dict:
        cfg = settings.runtime_config
        return {
            "url": cfg.get("discord_webhook_url", "").strip(),
            "language": cfg.get("discord_language", "es"),
            "events": cfg.get("discord_events", {}) or {},
        }

    async def notify(self, event: str, text: str = "") -> bool:
        conf = self._config()
        url = conf["url"]
        if not url:
            return False
        events = conf["events"]
        enabled = events.get(event)
        if enabled is False:
            return False
        lang = LANG.get(conf["language"], LANG["es"])
        title = lang.get(event, event)
        content = f"**{title}**\n{text}" if text else f"**{title}**"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(url, json={"content": content})
                return r.status_code in (200, 204)
        except Exception:
            return False

    async def test(self) -> bool:
        conf = self._config()
        lang = LANG.get(conf["language"], LANG["es"])
        return await self.notify("test", lang["test"])


webhook_manager = WebhookManager()
