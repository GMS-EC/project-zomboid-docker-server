#!/bin/bash
# Prepara la estructura de directorios de Zomboid antes del primer arranque.
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"

export PZ_SERVER_DIR="${PZ_SERVER_DIR:-/home/steam/steamcmd/pz}"
export PZ_DATA_DIR="${PZ_DATA_DIR:-/home/steam/Zomboid}"
SERVER_NAME="${SERVER_NAME:-servertest}"

mkdir -p "${PZ_DATA_DIR}/Server" \
         "${PZ_DATA_DIR}/db" \
         "${PZ_DATA_DIR}/Saves/Multiplayer" \
         "${PZ_DATA_DIR}/Logs"

chown -R steam:steam "${PZ_DATA_DIR}" 2>/dev/null || true

INI="${PZ_DATA_DIR}/Server/${SERVER_NAME}.ini"
if [ -f "${INI}" ]; then
    echo "[PZ-Server] Configuración detectada: ${INI}"
else
    echo "[PZ-Server] ${INI} se generará automáticamente en el primer arranque."
fi
