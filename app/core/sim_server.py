"""
Simulador de servidor de Project Zomboid para desarrollo/validación sin binarios.
Emula el flujo de la consola: escribe líneas de arranque, lee comandos del stdin
y responde como lo haría el servidor real (sin mundo ni red).
"""

import re
import sys
import signal
from typing import Dict


ONLINE_PLAYERS: Dict[str, str] = {}


def _log(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _handle_quit(*_args) -> None:
    _log("[PZ-Sim] Señal recibida. Cerrando simulación...")
    sys.exit(0)


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]
    return val


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_quit)
    signal.signal(signal.SIGINT, _handle_quit)

    _log("=" * 60)
    _log(" [Project Zomboid SIMULACIÓN] Servidor virtual (sin binarios)")
    _log(" Usa este modo solo para pruebas del panel: no crea mundo ni abre puertos.")
    _log("=" * 60)
    _log("PZ > Loading...")
    _log("PZ > Creando mundo de prueba (simulación)")
    _log("PZ > SERVER STARTED (simulación)")
    _log("[PZ-Sim] Servidor listo. Comandos: save, players, simjoin <nombre> [steamid], simleave <nombre>, quit...")

    for raw in sys.stdin:
        cmd = raw.strip()
        if not cmd:
            continue
        _log(f"> {cmd}")
        low = cmd.lower()
        if low in ("quit", "exit"):
            ONLINE_PLAYERS.clear()
            _log("[PZ-Sim] Guardando y cerrando... (quit)")
            break
        elif low == "save":
            _log("[PZ-Sim] Mundo guardado (simulación).")
        elif low in ("players", "list"):
            _log(f"Players connected ({len(ONLINE_PLAYERS)}):")
            for pname in ONLINE_PLAYERS:
                _log(f"-{pname}")
        elif low.startswith("simjoin "):
            parts = cmd.split()
            if len(parts) >= 2:
                pname = _strip_quotes(parts[1])
                sid = parts[2] if len(parts) >= 3 else "76561198000000001"
                ONLINE_PLAYERS[pname] = sid
                _log(f"[PZ-Sim] Jugador conectado: {pname} (SteamID: {sid})")
        elif low.startswith("simleave "):
            pname = _strip_quotes(cmd[len("simleave "):])
            ONLINE_PLAYERS.pop(pname, None)
            _log(f"[PZ-Sim] Jugador desconectado: {pname}")
        elif low.startswith("kickuser "):
            m = re.match(r'^kickuser\s+"?([^"\s]+)"?', cmd, re.IGNORECASE)
            pname = m.group(1) if m else _strip_quotes(cmd[len("kickuser "):])
            ONLINE_PLAYERS.pop(pname, None)
            _log(f"User {pname} kicked.")
            _log(f"[PZ-Sim] Jugador desconectado: {pname}")
        elif low.startswith("banuser "):
            m = re.match(r'^banuser\s+"?([^"\s]+)"?', cmd, re.IGNORECASE)
            pname = m.group(1) if m else _strip_quotes(cmd[len("banuser "):])
            ONLINE_PLAYERS.pop(pname, None)
            _log(f"User {pname} is now banned")
            _log(f"[PZ-Sim] Jugador desconectado: {pname}")
        elif low.startswith("unbanuser "):
            m = re.match(r'^unbanuser\s+"?([^"\s]+)"?', cmd, re.IGNORECASE)
            pname = m.group(1) if m else _strip_quotes(cmd[len("unbanuser "):])
            _log(f"User {pname} is no longer banned")
        elif low.startswith("setaccesslevel "):
            _log(f"[PZ-Sim] Nivel de acceso actualizado: {cmd}")
        elif low.startswith("adduser "):
            _log(f"[PZ-Sim] Usuario creado en whitelist: {cmd}")
        elif low == "reloadoptions":
            _log("[PZ-Sim] Opciones recargadas en caliente (Server.ini).")
        elif low == "startrain":
            _log("[PZ-Sim] Lluvia activada.")
        elif low == "stoprain":
            _log("[PZ-Sim] Lluvia detenida.")
        elif low == "chopper":
            _log("[PZ-Sim] Evento de helicóptero activado.")
        elif low == "gunshot":
            _log("[PZ-Sim] Evento de disparo lejano lanzado.")
        elif low == "alarm":
            _log("[PZ-Sim] Evento de alarma de edificio lanzado.")
        elif low.startswith("createhorde"):
            _log(f"[PZ-Sim] Horda generada: {cmd}")
        elif low.startswith("godmod "):
            _log(f"[PZ-Sim] Godmode actualizado: {cmd}")
        elif low.startswith("invisible "):
            _log(f"[PZ-Sim] Invisibilidad actualizada: {cmd}")
        elif low.startswith("teleport"):
            _log(f"[PZ-Sim] Teletransporte ejecutado: {cmd}")
        elif low.startswith("additem "):
            _log(f"[PZ-Sim] Ítem entregado: {cmd}")
        elif low.startswith("addvehicle "):
            _log(f"[PZ-Sim] Vehículo generado: {cmd}")
        elif low.startswith("addxp "):
            _log(f"[PZ-Sim] Experiencia otorgada: {cmd}")
        elif low.startswith("servermsg") or low.startswith("say"):
            _log(f"[PZ-Sim] Mensaje difundido a {len(ONLINE_PLAYERS)} jugador(es).")
        elif low.startswith("help"):
            _log("Comandos útiles: save, quit, players, simjoin <user> [id], simleave <user>, servermsg \"texto\", banuser, kickuser, setaccesslevel, reloadoptions")
        else:
            _log(f"[PZ-Sim] Comando ejecutado: {cmd}")

    _log("[PZ-Sim] Simulación finalizada.")
    sys.exit(0)


if __name__ == "__main__":
    main()
