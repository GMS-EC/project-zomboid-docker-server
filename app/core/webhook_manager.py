import asyncio
import html
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger("pz-panel.webhooks")

SECRET_MASK = "••••••••••••"

LANG = {
    "es": {
        "start": "Servidor PZ 100% Online",
        "server_start": "Servidor PZ 100% Online",
        "starting": "El servidor PZ está arrancando...",
        "shutdown": "El servidor PZ se ha detenido",
        "server_stop": "El servidor PZ se ha detenido",
        "shutdown_warn": "Aviso de apagado programado",
        "restart": "Reinicio programado del servidor PZ",
        "save": "Guardado del mundo completado",
        "backup": "Copia de seguridad completada",
        "backup_created": "Copia de seguridad completada",
        "players_join": "Superviviente conectado",
        "players_leave": "Superviviente desconectado",
        "crash": "Caída o fallo detectado en el servidor",
        "server_crash": "Caída o fallo detectado en el servidor",
        "test": "Conexión verificada exitosamente. Las notificaciones automáticas están activas.",
    },
    "en": {
        "start": "PZ Server 100% Online",
        "server_start": "PZ Server 100% Online",
        "starting": "PZ server is starting...",
        "shutdown": "PZ server stopped",
        "server_stop": "PZ server stopped",
        "shutdown_warn": "Scheduled shutdown notice",
        "restart": "Scheduled PZ server restart",
        "save": "World save completed",
        "backup": "Backup completed",
        "backup_created": "Backup completed",
        "players_join": "Survivor joined",
        "players_leave": "Survivor left",
        "crash": "Server crash or failure detected",
        "server_crash": "Server crash or failure detected",
        "test": "Connection verified successfully. Automatic notifications are active.",
    },
}

EVENT_COLORS = {
    "start": 0x3FB950,
    "server_start": 0x3FB950,
    "starting": 0xF0883E,
    "shutdown": 0xF85149,
    "server_stop": 0xF85149,
    "shutdown_warn": 0xE3B341,
    "restart": 0xBC8CFF,
    "save": 0xD29922,
    "backup": 0x58A6FF,
    "backup_created": 0x58A6FF,
    "players_join": 0x79C0FF,
    "players_leave": 0x8B949E,
    "crash": 0xDA3633,
    "server_crash": 0xDA3633,
    "test": 0x5865F2,
}

DEFAULT_EVENT_STATE: Dict[str, bool] = {
    "server_start": True,
    "starting": True,
    "server_stop": True,
    "server_crash": True,
    "backup_created": True,
    "save": True,
    "restart": True,
    "shutdown_warn": True,
    "player_join": False,
    "player_leave": False,
}

_EVENT_LOOKUP: Dict[str, tuple] = {
    "start": ("server_start", "start"),
    "server_start": ("server_start", "start"),
    "starting": ("starting",),
    "shutdown": ("server_stop", "shutdown"),
    "server_stop": ("server_stop", "shutdown"),
    "crash": ("server_crash", "crash"),
    "server_crash": ("server_crash", "crash"),
    "shutdown_warn": ("shutdown_warn",),
    "backup": ("backup_created", "backup"),
    "backup_created": ("backup_created", "backup"),
    "save": ("save",),
    "restart": ("restart",),
    "players_join": ("player_join", "players"),
    "player_join": ("player_join", "players"),
    "players_leave": ("player_leave", "players"),
    "player_leave": ("player_leave", "players"),
}


class WebhookManager:
    """Notificaciones multi-canal a Discord, Telegram y Correo SMTP."""

    SECRET_MASK = SECRET_MASK

    def _config(self) -> Dict[str, Any]:
        cfg = settings.runtime_config
        discord_url = str(cfg.get("discord_webhook_url", "") or "").strip()
        discord_enabled = cfg.get("discord_enabled")
        if discord_enabled is None:
            discord_enabled = bool(discord_url)

        raw_email = cfg.get("webhook_email") if isinstance(cfg.get("webhook_email"), dict) else {}
        email_cfg = {
            "enabled": bool(raw_email.get("enabled", False)),
            "smtp_host": str(raw_email.get("smtp_host", "") or "").strip(),
            "smtp_port": int(raw_email.get("smtp_port", 587) or 587),
            "smtp_user": str(raw_email.get("smtp_user", "") or "").strip(),
            "smtp_password": str(raw_email.get("smtp_password", "") or ""),
            "smtp_use_tls": raw_email.get("smtp_use_tls", True) is not False,
            "from_email": str(raw_email.get("from_email", "") or "").strip(),
            "to_emails": str(raw_email.get("to_emails", "") or "").strip(),
        }

        raw_events = cfg.get("discord_events") or {}
        events = {
            "server_start": bool(raw_events.get("server_start", raw_events.get("start", True))),
            "starting": bool(raw_events.get("starting", True)),
            "server_stop": bool(raw_events.get("server_stop", raw_events.get("shutdown", True))),
            "server_crash": bool(raw_events.get("server_crash", raw_events.get("crash", True))),
            "backup_created": bool(raw_events.get("backup_created", raw_events.get("backup", True))),
            "save": bool(raw_events.get("save", True)),
            "restart": bool(raw_events.get("restart", True)),
            "shutdown_warn": bool(raw_events.get("shutdown_warn", True)),
            "player_join": bool(raw_events.get("player_join", raw_events.get("players", False))),
            "player_leave": bool(raw_events.get("player_leave", raw_events.get("players", False))),
        }

        return {
            "url": discord_url,
            "discord_enabled": bool(discord_enabled),
            "language": str(cfg.get("discord_language", "es") or "es"),
            "raw_events": raw_events,
            "events": events,
            "telegram_enabled": bool(cfg.get("telegram_enabled", False)),
            "telegram_bot_token": str(cfg.get("telegram_bot_token", "") or "").strip(),
            "telegram_chat_id": str(cfg.get("telegram_chat_id", "") or "").strip(),
            "email": email_cfg,
        }

    def get_sanitized_config(self) -> Dict[str, Any]:
        """Devuelve la configuración estructurada con secretos enmascarados."""
        c = self._config()
        tg_tok = c["telegram_bot_token"]
        email_cfg = dict(c["email"])
        if email_cfg.get("smtp_password"):
            email_cfg["smtp_password"] = self.SECRET_MASK

        return {
            "language": c["language"],
            "discord": {
                "enabled": c["discord_enabled"],
                "webhook_url": c["url"],
            },
            "telegram": {
                "enabled": c["telegram_enabled"],
                "bot_token": self.SECRET_MASK if tg_tok else "",
                "chat_id": c["telegram_chat_id"],
            },
            "email": email_cfg,
            "events": c["events"],
        }

    def save_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Actualiza parcialmente la configuración multi-canal en runtime_config."""
        cfg = settings.runtime_config
        updates: Dict[str, Any] = {}

        if "language" in new_config and new_config["language"] in ("es", "en"):
            updates["discord_language"] = new_config["language"]

        if isinstance(new_config.get("discord"), dict):
            d = new_config["discord"]
            if "enabled" in d:
                updates["discord_enabled"] = bool(d["enabled"])
            if "webhook_url" in d:
                url_val = str(d["webhook_url"] or "").strip()
                if url_val != self.SECRET_MASK:
                    updates["discord_webhook_url"] = url_val
                    if "enabled" not in d and url_val and cfg.get("discord_enabled") is None:
                        updates["discord_enabled"] = True

        if isinstance(new_config.get("telegram"), dict):
            tg = new_config["telegram"]
            if "enabled" in tg:
                updates["telegram_enabled"] = bool(tg["enabled"])
            if "bot_token" in tg:
                tok = str(tg["bot_token"] or "").strip()
                if tok != self.SECRET_MASK:
                    updates["telegram_bot_token"] = tok
            if "chat_id" in tg:
                updates["telegram_chat_id"] = str(tg["chat_id"] or "").strip()

        if isinstance(new_config.get("email"), dict):
            cur_email = dict(cfg.get("webhook_email") or {})
            em = dict(new_config["email"])
            if em.get("smtp_password") == self.SECRET_MASK:
                em.pop("smtp_password", None)
            if "smtp_port" in em:
                try:
                    em["smtp_port"] = int(em["smtp_port"] or 587)
                except (TypeError, ValueError):
                    em["smtp_port"] = 587
            cur_email.update(em)
            updates["webhook_email"] = cur_email

        if isinstance(new_config.get("events"), dict):
            cur_events = dict(cfg.get("discord_events") or {})
            ev = new_config["events"]
            cur_events.update(ev)
            # Sincronizar claves legacy con claves Dockraft
            sync_pairs = [
                ("server_start", "start"),
                ("server_stop", "shutdown"),
                ("server_crash", "crash"),
                ("backup_created", "backup"),
            ]
            for dk, leg in sync_pairs:
                if dk in ev:
                    cur_events[leg] = bool(ev[dk])
                elif leg in ev:
                    cur_events[dk] = bool(ev[leg])
            if "player_join" in ev or "player_leave" in ev:
                pj = bool(cur_events.get("player_join", cur_events.get("players", False)))
                pl = bool(cur_events.get("player_leave", cur_events.get("players", False)))
                cur_events["players"] = pj or pl
            elif "players" in ev:
                cur_events["player_join"] = bool(ev["players"])
                cur_events["player_leave"] = bool(ev["players"])
            updates["discord_events"] = cur_events

        if updates:
            settings.save_runtime_config(updates)
        return self.get_sanitized_config()

    @staticmethod
    def _esc_md(val: str) -> str:
        return str(val).replace("[", "\\[").replace("]", "\\]")

    def _build_fields(self, event: str, extra_fields: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        if extra_fields is not None:
            return extra_fields
        mode_str = "Steam" if settings.use_steam else "No-Steam (-nosteam)"
        return [
            {"name": "Servidor", "value": f"`{settings.server_name}`", "inline": True},
            {"name": "Mundo / Modo", "value": f"`{settings.world_label} ({mode_str})`", "inline": True},
            {"name": "Puerto", "value": f"`{settings.server_port}/UDP`", "inline": True},
        ]

    def _is_event_enabled(self, event: str, raw_events: Dict[str, Any]) -> bool:
        if event == "test":
            return True
        keys = _EVENT_LOOKUP.get(event, (event,))
        for k in keys:
            if k in raw_events:
                return bool(raw_events[k])
        if event in ("players_join", "players_leave", "player_join", "player_leave"):
            return False
        return True

    async def _post_discord(
        self,
        url: str,
        title: str,
        message: str,
        color: int = 0x388BFD,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not url:
            raise ValueError("URL de Discord Webhook no configurada.")
        now_local = datetime.now().strftime("%d/%m/%Y %H:%M")
        safe_fields = [
            {
                "name": self._esc_md(f.get("name", "")),
                "value": self._esc_md(f.get("value", "")),
                "inline": bool(f.get("inline", True)),
            }
            for f in (fields or [])
        ]
        embed = {
            "title": self._esc_md(title),
            "description": self._esc_md(message) if message else "",
            "color": color,
            "fields": safe_fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": f"PZ Server Manager • {now_local}"},
        }
        payload = {
            "username": (settings.server_name or "PZ Server Manager")[:80],
            "allowed_mentions": {"parse": []},
            "embeds": [embed],
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"Discord devolvió código {resp.status_code}")

    async def _post_telegram(
        self,
        bot_token: str,
        chat_id: str,
        title: str,
        message: str,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Bot Token o Chat ID de Telegram no configurados.")
        lines = [f"<b>{html.escape(title)}</b>"]
        if message:
            lines.extend(["", html.escape(message)])
        if fields:
            lines.append("")
            for f in fields:
                fname = html.escape(str(f.get("name", "")))
                fval = html.escape(str(f.get("value", "")).replace("`", ""))
                lines.append(f"{fname}: <code>{fval}</code>")
        lines.extend(["", f"<i>{datetime.now().strftime('%d/%m/%Y %H:%M')} • PZ Server Manager</i>"])
        payload = {
            "chat_id": chat_id,
            "text": "\n".join(lines),
            "parse_mode": "HTML",
        }
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"Telegram devolvió código {resp.status_code}")

    def _send_email_sync(
        self,
        email_cfg: Dict[str, Any],
        subject: str,
        body: str,
        color: int = 0x388BFD,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        host = str(email_cfg.get("smtp_host", "") or "").strip()
        port = int(email_cfg.get("smtp_port", 587) or 587)
        user = str(email_cfg.get("smtp_user", "") or "").strip()
        pwd = str(email_cfg.get("smtp_password", "") or "")
        use_tls = email_cfg.get("smtp_use_tls", True) is not False
        from_email = str(email_cfg.get("from_email", "") or "").strip() or user
        to_raw = str(email_cfg.get("to_emails", "") or "").strip()

        if not host or not to_raw:
            raise ValueError("Host SMTP o destinatarios de correo no configurados.")
        recipients = [e.strip() for e in to_raw.replace(";", ",").split(",") if e.strip()]
        if not recipients:
            raise ValueError("No hay destinatarios de correo válidos.")

        server_name = settings.server_name
        color_hex = f"#{color:06x}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{server_name}] {subject}"
        msg["From"] = from_email
        msg["To"] = ", ".join(recipients)

        plain_lines = [f"=== {subject} ===", f"Servidor: {server_name}", f"Fecha: {now_str}", "", body, ""]
        for f in (fields or []):
            plain_lines.append(f"  * {f.get('name', '')}: {str(f.get('value', '')).replace('`', '')}")
        body_plain = "\n".join(plain_lines)

        fields_rows = ""
        for f in (fields or []):
            fname = html.escape(str(f.get("name", "")))
            fval = html.escape(str(f.get("value", "")).replace("`", ""))
            fields_rows += (
                f"<tr><td style=\"padding:10px 14px;border-bottom:1px solid #21262d;font-size:13px;"
                f"font-weight:600;color:#8b949e;width:38%;\">{fname}</td>"
                f"<td style=\"padding:10px 14px;border-bottom:1px solid #21262d;font-size:13px;color:#f0f6fc;\">"
                f"<code style=\"background:rgba(110,118,129,0.2);padding:2px 6px;border-radius:4px;\">{fval}</code>"
                f"</td></tr>"
            )
        fields_table = (
            f"<table width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background:#0d1117;"
            f"border:1px solid #21262d;border-radius:8px;overflow:hidden;\">{fields_rows}</table>"
            if fields_rows else ""
        )
        safe_subject = html.escape(subject)
        safe_server = html.escape(server_name)
        body_html = html.escape(body or "").replace("\n", "<br>")

        html_doc = (
            f"<!DOCTYPE html><html lang=\"es\"><body style=\"margin:0;padding:24px 12px;background:#0b0f17;"
            f"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#e6edf3;\">"
            f"<table width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:560px;margin:0 auto;"
            f"background:#161b22;border:1px solid #30363d;border-radius:12px;overflow:hidden;\">"
            f"<tr><td style=\"padding:16px 22px;background:#111622;border-bottom:1px solid #30363d;\">"
            f"<strong style=\"color:#58a6ff;font-size:13px;\">PZ SERVER MANAGER</strong>"
            f"<span style=\"float:right;color:#8b949e;font-size:12px;\">{safe_server}</span></td></tr>"
            f"<tr><td style=\"height:3px;background:{color_hex};\"></td></tr>"
            f"<tr><td style=\"padding:22px;\"><h2 style=\"margin:0 0 12px 0;color:#f0f6fc;font-size:18px;\">{safe_subject}</h2>"
            f"<div style=\"background:#0d1117;border-left:3px solid {color_hex};padding:12px 14px;margin-bottom:16px;"
            f"color:#cbd5e1;font-size:14px;line-height:1.5;\">{body_html}</div>{fields_table}</td></tr>"
            f"<tr><td style=\"padding:12px 22px;background:#0d1117;border-top:1px solid #21262d;text-align:center;"
            f"font-size:11px;color:#8b949e;\">{now_str} • {safe_server}</td></tr></table></body></html>"
        )

        msg.attach(MIMEText(body_plain, "plain", "utf-8"))
        msg.attach(MIMEText(html_doc, "html", "utf-8"))

        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.starttls()

        try:
            if user and pwd:
                server.login(user, pwd)
            server.sendmail(from_email, recipients, msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass

    async def send_discord(
        self,
        url: str,
        title: str,
        message: str,
        color: int = 0x388BFD,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        try:
            await self._post_discord(url, title, message, color=color, fields=fields)
            return True
        except Exception:
            return False

    async def send_telegram(
        self,
        bot_token: str,
        chat_id: str,
        title: str,
        message: str,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        try:
            await self._post_telegram(bot_token, chat_id, title, message, fields=fields)
            return True
        except Exception:
            return False

    async def notify(
        self,
        event: str,
        text: str = "",
        extra_fields: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        conf = self._config()
        if not self._is_event_enabled(event, conf["raw_events"]):
            return False

        lang = LANG.get(conf["language"], LANG["es"])
        title = lang.get(event, event)
        color = EVENT_COLORS.get(event, 0x388BFD)
        fields = self._build_fields(event, extra_fields)

        sent_any = False
        if conf["discord_enabled"] and conf["url"]:
            ok = await self.send_discord(conf["url"], title, text, color=color, fields=fields)
            sent_any = sent_any or ok

        if conf["telegram_enabled"] and conf["telegram_bot_token"] and conf["telegram_chat_id"]:
            ok_tg = await self.send_telegram(
                conf["telegram_bot_token"],
                conf["telegram_chat_id"],
                title,
                text,
                fields=fields,
            )
            sent_any = sent_any or ok_tg

        email_cfg = conf["email"]
        if email_cfg.get("enabled") and email_cfg.get("smtp_host") and email_cfg.get("to_emails"):
            try:
                await asyncio.to_thread(self._send_email_sync, email_cfg, title, text or title, color, fields)
                sent_any = True
            except Exception as e:
                logger.warning("Error enviando email de notificación: %s", e)

        return sent_any

    async def test_channel(self, channel: str) -> Dict[str, Any]:
        """Prueba individual para un canal (discord, telegram o email)."""
        conf = self._config()
        lang = LANG.get(conf["language"], LANG["es"])
        title = "Prueba de Notificación" if conf["language"] == "es" else "Test Notification"
        message = lang["test"]
        fields = self._build_fields("test")

        try:
            if channel == "discord":
                await self._post_discord(conf["url"], title, message, color=0x5865F2, fields=fields)
            elif channel == "telegram":
                await self._post_telegram(
                    conf["telegram_bot_token"], conf["telegram_chat_id"], title, message, fields=fields
                )
            elif channel == "email":
                await asyncio.to_thread(self._send_email_sync, conf["email"], title, message, 0x5865F2, fields)
            else:
                return {"status": "error", "message": f"Canal desconocido: '{channel}'"}
            return {
                "status": "success",
                "success": True,
                "message": f"Notificación de prueba enviada a {channel.capitalize()} correctamente.",
            }
        except Exception as e:
            logger.warning("Error probando canal '%s': %s", channel, e)
            return {
                "status": "error",
                "success": False,
                "message": f"No se pudo enviar la prueba a {channel.capitalize()}: {e}",
            }


webhook_manager = WebhookManager()
