"""
Simulador de servidor de Project Zomboid para desarrollo/validación sin binarios.
Emula el flujo de la consola: escribe líneas de arranque, lee comandos del stdin
y responde como lo haría el servidor real (sin mundo ni red).
"""

import sys
import time
import signal

def _log(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

def _handle_quit(*_args) -> None:
    _log("[PZ-Sim] Señal recibida. Cerrando simulación...")
    sys.exit(0)

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
    _log("[PZ-Sim] Servidor listo. Escribe comandos (save, players, quit...) para validar la consola.")

    for raw in sys.stdin:
        cmd = raw.strip()
        if not cmd:
            continue
        _log(f"> {cmd}")
        low = cmd.lower()
        if low in ("quit", "exit"):
            _log("[PZ-Sim] Guardando y cerrando... (quit)")
            break
        elif low == "save":
            _log("[PZ-Sim] Mundo guardado (simulación).")
        elif low in ("players", "list"):
            _log("Players: (0 en línea) [simulación]")
        elif low.startswith("servermsg") or low.startswith("say"):
            _log("[PZ-Sim] Mensaje difundido a 0 jugadores.")
        elif low.startswith("help"):
            _log("Comandos útiles: save, quit, players, servermsg \"texto\", banuser, kickuser, teleport, ...")
        else:
            _log(f"[PZ-Sim] Comando ejecutado: {cmd}")

    _log("[PZ-Sim] Simulación finalizada.")
    sys.exit(0)

if __name__ == "__main__":
    main()
