#!/bin/bash
# ==============================================================================
# AVISO: "modo solo servidor" eliminado.
# El panel web (init.sh) es el ÚNICO método soportado para gestionar el servidor.
# Este script ya no se utiliza: se conserva como recordatorio y aborta.
# ==============================================================================
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"

echo "[PZ-Server] [ERROR] El modo 'solo servidor' fue eliminado."
echo "[PZ-Server] Usa el panel web (uvicorn/app.main) para iniciar y administrar el servidor."
echo "[PZ-Server] Toda la configuración del juego se hace desde la interfaz web."
exit 1
