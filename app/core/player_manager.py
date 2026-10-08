import sqlite3
from pathlib import Path
from typing import Dict, List, Any

from app.config import settings
from app.core.process_manager import process_manager
from app.core.activity_manager import activity_manager


class PlayerManager:
    """Jugadores de PZ: en línea (vía consola 'players') y persistidos (SQLite).

    PZ guarda cuentas/whitelist en <SERVER_NAME>.db (tablas whitelist, bannedid,
    bannedip). El esquema varía entre builds; aquí se lee de forma tolerante.
    """

    @property
    def db_path(self) -> Path:
        return settings.data_dir / "db" / f"{settings.server_name}.db"

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

    # ------------------------------------------------------------- get
    async def get_online_players(self) -> List[Dict[str, Any]]:
        # El comando 'players' responde por la consola (stdout); el parseo fiable
        # requiere el formato exacto de la build. Por ahora se reporta la lista
        # desde la DB y la consulta en vivo se completa al acoplar RCON/consola.
        return []

    def get_history(self) -> List[Dict[str, Any]]:
        cols = self._columns_of("whitelist")
        rows = self._query("SELECT * FROM whitelist")
        history = []
        for row in rows:
            d = {name: val for name, val in zip(cols, row)}
            username = str(d.get("username") or d.get("steamid") or row[0] if row else "")
            history.append({
                "name": username,
                "steam_id": str(d.get("steamid") or "") if cols else "",
                "access_level": str(d.get("accessLevel") or d.get("accesslevel") or "user"),
                "status": "registered",
                "last_seen": "",
                "banned": False,
            })
        return history

    def get_banned(self) -> List[Dict[str, Any]]:
        banned = []
        for table, field in (("bannedid", "steamid"), ("bannedip", "ip")):
            for row in self._query(f"SELECT * FROM {table}"):
                banned.append({"type": table, field: (row[0] if row else "")})
        return banned

    async def get_players(self) -> Dict[str, Any]:
        online = await self.get_online_players()
        history = self.get_history()
        return {
            "online": online,
            "online_count": len(online),
            "history": history,
            "banned": self.get_banned(),
        }

    # ---------------------------------------------------------- acciones
    async def send_action(self, command: str, label: str) -> str:
        resp = await process_manager.send_command(command)
        activity_manager.log("Jugadores", f"{label}: {command}")
        return resp

    async def kick(self, username: str) -> str:
        return await self.send_action(f'kickuser "{username}"', "Kick")

    async def ban(self, username: str) -> str:
        return await self.send_action(f'banuser "{username}"', "Ban")

    async def unban(self, username: str) -> str:
        return await self.send_action(f'unbanuser "{username}"', "Unban")

    async def message_player(self, username: str, message: str) -> str:
        return await self.send_action(
            f'servermsg "Mensaje privado a {username}: {message}"', "Mensaje privado")


player_manager = PlayerManager()
