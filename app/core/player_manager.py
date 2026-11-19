import re
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.config import settings
from app.core.fs_utils import atomic_write_json
from app.core.process_manager import process_manager
from app.core.activity_manager import activity_manager

VALID_ACCESS_LEVELS = ("admin", "moderator", "overseer", "gm", "observer", "none")
_CTRL_CHARS_RE = re.compile(r"[\r\n\x00-\x1f\x7f]")


def _clean_text(val: Optional[str], max_len: int = 120) -> str:
    if not val:
        return ""
    cleaned = _CTRL_CHARS_RE.sub(" ", str(val)).strip()
    return re.sub(r"\s{2,}", " ", cleaned)[:max_len]


def _sanitize_username(val: Optional[str]) -> str:
    clean = _clean_text(val, max_len=64).replace('"', "").replace("'", "")
    return clean


class PlayerManager:
    """Jugadores de PZ: en línea (parseo consola + players), SQLite y caché JSON persistente."""

    @property
    def db_path(self) -> Path:
        return settings.data_dir / "db" / f"{settings.server_name}.db"

    @property
    def history_file(self) -> Path:
        return settings.panel_dir / "players_history.json"

    def _load_local_history(self) -> Dict[str, Dict[str, Any]]:
        if not self.history_file.exists():
            return {}
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_local_history(self, data: Dict[str, Dict[str, Any]]) -> None:
        try:
            atomic_write_json(self.history_file, data, indent=2)
        except Exception:
            pass

    def _query(self, sql: str) -> List[tuple]:
        if not self.db_path.exists():
            return []
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2)
            try:
                cur = con.execute(sql)
                return cur.fetchall()
            finally:
                con.close()
        except Exception:
            return []

    def _columns_of(self, table: str) -> List[str]:
        if not self.db_path.exists():
            return []
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2)
            try:
                cur = con.execute(f"PRAGMA table_info({table})")
                return [row[1] for row in cur.fetchall()]
            finally:
                con.close()
        except Exception:
            return []

    # ------------------------------------------------------------- eventos
    def record_join(self, username: str, steam_id: str = "") -> None:
        name = _sanitize_username(username)
        if not name:
            return
        hist = self._load_local_history()
        key = name.lower()
        entry = hist.get(key, {})
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        entry["name"] = name
        if steam_id:
            entry["steam_id"] = str(steam_id).strip()
        entry.setdefault("access_level", "user")
        entry["last_seen"] = now_str
        entry["banned"] = bool(entry.get("banned", False))
        hist[key] = entry
        self._save_local_history(hist)
        activity_manager.log("Jugadores", f"Superviviente conectado: {name}", action="player_join")

    def record_leave(self, username: str) -> None:
        name = _sanitize_username(username)
        if not name:
            return
        hist = self._load_local_history()
        key = name.lower()
        entry = hist.get(key, {"name": name})
        entry["name"] = entry.get("name") or name
        entry["last_seen"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        hist[key] = entry
        self._save_local_history(hist)

    # ------------------------------------------------------------- lectura
    async def get_online_players(self) -> List[Dict[str, Any]]:
        hist = self._load_local_history()
        online: List[Dict[str, Any]] = []
        for key, info in process_manager.online_players.items():
            h = hist.get(key, {})
            name = info.get("name") or h.get("name") or key
            sid = info.get("steam_id") or h.get("steam_id") or ""
            online.append({
                "name": name,
                "steam_id": sid,
                "access_level": str(h.get("access_level") or "user"),
                "status": "online",
                "last_seen": "En juego ahora",
                "banned": False,
            })
        online.sort(key=lambda p: p["name"].lower())
        return online

    def get_banned(self) -> List[Dict[str, Any]]:
        banned: List[Dict[str, Any]] = []
        seen = set()
        for table, field in (("bannedid", "steamid"), ("bannedip", "ip")):
            cols = self._columns_of(table)
            for row in self._query(f"SELECT * FROM {table}"):
                d = {name: val for name, val in zip(cols, row)} if cols else {}
                val = str(d.get(field) or (row[0] if row else "")).strip()
                if val:
                    seen.add(val.lower())
                    banned.append({
                        "type": table,
                        field: val,
                        "username": str(d.get("username") or ""),
                        "reason": str(d.get("reason") or ""),
                    })
        hist = self._load_local_history()
        for key, entry in hist.items():
            if entry.get("banned"):
                name = entry.get("name") or key
                sid = str(entry.get("steam_id") or "")
                if name.lower() not in seen and (not sid or sid.lower() not in seen):
                    banned.append({
                        "type": "local",
                        "username": name,
                        "steamid": sid,
                        "reason": str(entry.get("ban_reason") or ""),
                    })
        return banned

    def get_history(self) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        local_hist = self._load_local_history()
        banned_list = self.get_banned()
        banned_names = {str(b.get("username") or "").lower() for b in banned_list if b.get("username")}
        banned_sids = {str(b.get("steamid") or "").lower() for b in banned_list if b.get("steamid")}

        # 1. Base de datos SQLite de PZ (whitelist)
        cols = self._columns_of("whitelist")
        rows = self._query("SELECT * FROM whitelist")
        for row in rows:
            d = {name: val for name, val in zip(cols, row)}
            username = str(d.get("username") or d.get("steamid") or (row[0] if row else "")).strip()
            if not username:
                continue
            sid = str(d.get("steamid") or "").strip()
            access = str(d.get("accessLevel") or d.get("accesslevel") or "user")
            key = username.lower()
            is_banned = (key in banned_names) or (bool(sid) and sid.lower() in banned_sids)
            merged[key] = {
                "name": username,
                "steam_id": sid,
                "access_level": access,
                "status": "banned" if is_banned else "registered",
                "last_seen": str(d.get("lastConnection") or local_hist.get(key, {}).get("last_seen") or ""),
                "banned": is_banned,
            }

        # 2. Historial local (conexiones en consola, sanciones y registros manuales)
        for key, entry in local_hist.items():
            name = str(entry.get("name") or key).strip()
            if not name:
                continue
            sid = str(entry.get("steam_id") or "").strip()
            is_banned = bool(entry.get("banned")) or (key in banned_names) or (bool(sid) and sid.lower() in banned_sids)
            if key in merged:
                if sid and not merged[key]["steam_id"]:
                    merged[key]["steam_id"] = sid
                if entry.get("last_seen") and not merged[key]["last_seen"]:
                    merged[key]["last_seen"] = entry["last_seen"]
                if entry.get("access_level") and merged[key]["access_level"] == "user":
                    merged[key]["access_level"] = entry["access_level"]
                merged[key]["banned"] = merged[key]["banned"] or is_banned
                if merged[key]["banned"]:
                    merged[key]["status"] = "banned"
            else:
                merged[key] = {
                    "name": name,
                    "steam_id": sid,
                    "access_level": str(entry.get("access_level") or "user"),
                    "status": "banned" if is_banned else "registered",
                    "last_seen": str(entry.get("last_seen") or ""),
                    "banned": is_banned,
                }

        # 3. Jugadores conectados ahora que aún no tuvieran ficha previa
        for key, info in process_manager.online_players.items():
            name = info.get("name") or key
            if key not in merged:
                merged[key] = {
                    "name": name,
                    "steam_id": info.get("steam_id", ""),
                    "access_level": "user",
                    "status": "online",
                    "last_seen": "En juego ahora",
                    "banned": False,
                }
            else:
                merged[key]["status"] = "online"
                merged[key]["last_seen"] = "En juego ahora"

        result = list(merged.values())
        result.sort(key=lambda p: (p["status"] != "online", p["name"].lower()))
        return result

    async def get_players(self) -> Dict[str, Any]:
        online = await self.get_online_players()
        history = self.get_history()
        return {
            "online": online,
            "online_count": len(online),
            "max_players": settings.max_players,
            "server_online": process_manager.get_status() == "RUNNING",
            "history": history,
            "banned": self.get_banned(),
        }

    # ---------------------------------------------------------- utilidades
    def _resolve_username(self, username: Optional[str] = None, steam_id: Optional[str] = None) -> str:
        u = _sanitize_username(username)
        if u:
            return u
        sid = _clean_text(steam_id, max_len=64)
        if not sid:
            return ""
        for info in process_manager.online_players.values():
            if str(info.get("steam_id") or "") == sid:
                return str(info.get("name") or "")
        for entry in self._load_local_history().values():
            if str(entry.get("steam_id") or "") == sid:
                return str(entry.get("name") or "")
        for item in self.get_history():
            if str(item.get("steam_id") or "") == sid:
                return str(item.get("name") or "")
        return ""

    # ---------------------------------------------------------- acciones
    async def send_action(self, command: str, label: str) -> str:
        resp = await process_manager.send_command(command)
        activity_manager.log("Jugadores", f"{label}: {command}", action=label.lower().replace(" ", "_"))
        return resp

    async def refresh_online(self) -> str:
        return await process_manager.players()

    async def kick(self, username: Optional[str] = None, steam_id: Optional[str] = None, reason: str = "") -> str:
        target = self._resolve_username(username, steam_id)
        if not target:
            raise ValueError("Usuario requerido para expulsar.")
        clean_reason = _clean_text(reason).replace('"', "'")
        cmd = f'kickuser "{target}" -r "{clean_reason}"' if clean_reason else f'kickuser "{target}"'
        resp = await self.send_action(cmd, "Kick")
        process_manager.online_players.pop(target.lower(), None)
        return resp

    async def ban(self, username: Optional[str] = None, steam_id: Optional[str] = None, reason: str = "") -> str:
        target = self._resolve_username(username, steam_id)
        sid = _clean_text(steam_id, max_len=64)
        clean_reason = _clean_text(reason).replace('"', "'")
        if not target and not sid:
            raise ValueError("Usuario o SteamID requerido para banear.")

        if target:
            cmd = f'banuser "{target}" -r "{clean_reason}"' if clean_reason else f'banuser "{target}"'
            resp = await self.send_action(cmd, "Ban")
            hist = self._load_local_history()
            entry = hist.get(target.lower(), {"name": target})
            entry["name"] = target
            if sid:
                entry["steam_id"] = sid
            entry["banned"] = True
            if clean_reason:
                entry["ban_reason"] = clean_reason
            hist[target.lower()] = entry
            self._save_local_history(hist)
            process_manager.online_players.pop(target.lower(), None)
            return resp
        return await self.send_action(f"banid {sid}", "Ban SteamID")

    async def unban(self, username: Optional[str] = None, steam_id: Optional[str] = None) -> str:
        target = self._resolve_username(username, steam_id)
        sid = _clean_text(steam_id, max_len=64)
        if not target and not sid:
            raise ValueError("Usuario o SteamID requerido para desbanear.")

        resp = ""
        if target:
            resp = await self.send_action(f'unbanuser "{target}"', "Unban")
            hist = self._load_local_history()
            if target.lower() in hist:
                hist[target.lower()]["banned"] = False
                hist[target.lower()].pop("ban_reason", None)
                self._save_local_history(hist)
        if sid:
            resp2 = await self.send_action(f"unbanid {sid}", "Unban SteamID")
            resp = resp or resp2
        return resp

    async def message_player(self, username: Optional[str] = None, message: str = "", steam_id: Optional[str] = None) -> str:
        target = self._resolve_username(username, steam_id)
        msg = _clean_text(message, max_len=240).replace('"', "'")
        if not msg:
            raise ValueError("Mensaje requerido.")
        if target:
            return await self.send_action(
                f'servermsg "Mensaje a {target}: {msg}"',
                "Mensaje privado",
            )
        return await self.send_action(f'servermsg "{msg}"', "Anuncio global")

    async def set_access_level(self, username: str, level: str) -> Dict[str, Any]:
        target = _sanitize_username(username)
        lvl = (level or "").strip().lower()
        if not target:
            return {"success": False, "error": "Nombre de usuario requerido."}
        if lvl not in VALID_ACCESS_LEVELS:
            return {"success": False, "error": f"Nivel inválido. Permitidos: {', '.join(VALID_ACCESS_LEVELS)}"}
        resp = await self.send_action(f'setaccesslevel "{target}" "{lvl}"', "Rol de usuario")
        hist = self._load_local_history()
        entry = hist.get(target.lower(), {"name": target})
        entry["name"] = target
        entry["access_level"] = "user" if lvl == "none" else lvl
        hist[target.lower()] = entry
        self._save_local_history(hist)
        return {"success": True, "response": resp, "access_level": entry["access_level"]}

    async def add_user(self, username: str, password: str, access_level: str = "none") -> Dict[str, Any]:
        target = _sanitize_username(username)
        pwd = _clean_text(password, max_len=64).replace('"', "")
        lvl = (access_level or "none").strip().lower()
        if not target or not pwd:
            return {"success": False, "error": "Usuario y contraseña requeridos."}
        resp = await self.send_action(f'adduser "{target}" "{pwd}"', "Crear usuario")
        if lvl in VALID_ACCESS_LEVELS and lvl != "none":
            await self.send_action(f'setaccesslevel "{target}" "{lvl}"', "Rol de usuario")
        hist = self._load_local_history()
        hist[target.lower()] = {
            "name": target,
            "steam_id": hist.get(target.lower(), {}).get("steam_id", ""),
            "access_level": "user" if lvl == "none" else lvl,
            "last_seen": hist.get(target.lower(), {}).get("last_seen", "Registrado manualmente"),
            "banned": False,
        }
        self._save_local_history(hist)
        return {"success": True, "response": resp}

    async def admin_action(
        self,
        username: str,
        action: str,
        arg1: str = "",
        arg2: str = "",
    ) -> Dict[str, Any]:
        """Ejecuta acciones administrativas in-game sobre un jugador conectado."""
        target = _sanitize_username(username)
        act = (action or "").strip().lower()
        clean_a1 = _clean_text(arg1, max_len=120).replace('"', "").replace("'", "")
        clean_a2 = _clean_text(arg2, max_len=40).replace('"', "").replace("'", "")

        if not target and not (act == "teleport" and re.match(r"^\d+,\d+(?:,\d+)?$", clean_a1)):
            return {"success": False, "error": "Nombre de usuario requerido."}

        if act == "godmode_on":
            cmd, label = f'godmod "{target}" -true', "Godmode activado"
        elif act == "godmode_off":
            cmd, label = f'godmod "{target}" -false', "Godmode desactivado"
        elif act == "invisible_on":
            cmd, label = f'invisible "{target}" -true', "Invisibilidad activada"
        elif act == "invisible_off":
            cmd, label = f'invisible "{target}" -false', "Invisibilidad desactivada"
        elif act == "teleport":
            if not clean_a1:
                return {"success": False, "error": "Destino de teletransporte requerido (jugador o x,y,z)."}
            if re.match(r"^\d+,\d+(?:,\d+)?$", clean_a1):
                cmd, label = f"teleportto {clean_a1}", "Teletransporte a coordenadas"
            else:
                cmd, label = f'teleport "{target}" "{clean_a1}"', "Teletransporte a jugador"
        elif act == "additem":
            if not clean_a1:
                return {"success": False, "error": "Código de ítem requerido (ej: Base.Axe)."}
            try:
                qty = max(1, min(500, int(clean_a2 or "1")))
            except ValueError:
                qty = 1
            cmd, label = f'additem "{target}" "{clean_a1}" {qty}', f"Entregar ítem ({clean_a1} x{qty})"
        elif act == "addvehicle":
            veh = clean_a1 or "Base.CarNormal"
            cmd, label = f'addvehicle "{veh}" "{target}"', f"Spawnear vehículo ({veh})"
        elif act == "addxp":
            if not clean_a1:
                return {"success": False, "error": "Habilidad requerida (ej: Carpentry)."}
            try:
                xp = max(1, min(1000000, int(clean_a2 or "500")))
            except ValueError:
                xp = 500
            cmd, label = f'addxp "{target}" {clean_a1}={xp}', f"Otorgar XP ({clean_a1}={xp})"
        else:
            return {"success": False, "error": f"Acción administrativa desconocida: {action}"}

        resp = await self.send_action(cmd, label)
        return {"success": True, "command": cmd, "response": resp}


player_manager = PlayerManager()
