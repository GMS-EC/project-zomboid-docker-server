#!/bin/bash
# ==============================================================================
# generate-config.sh - Preparación previa al primer arranque (Fase 1)
# ------------------------------------------------------------------------------
# A diferencia de ARK (que necesita un arkmanager.cfg), el servidor dedicado de
# Project Zomboid AUTO-GENERA su configuración en el primer arranque:
#   $PZ_DATA_DIR/Server/<SERVER_NAME>.ini
#   $PZ_DATA_DIR/Server/<SERVER_NAME>_SandboxVars.lua
#   $PZ_DATA_DIR/Server/<SERVER_NAME>_spawnregions.lua  (+ _spawnpoints.lua)
#   $PZ_DATA_DIR/db/<SERVER_NAME>.db
# Por eso aquí solo aseguramos directorios y documentamos el flujo. A partir de
# la Fase 4, un pz_settings_manager.py leerá/escribirá esos archivos desde el
# panel web.
# ==============================================================================
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"

export PZ_SERVER_DIR="${PZ_SERVER_DIR:-/home/steam/steamcmd/pz}"
export PZ_DATA_DIR="${PZ_DATA_DIR:-/home/steam/Zomboid}"
SERVER_NAME="${SERVER_NAME:-servertest}"

# Directorios que PZ crea bajo el cachedir
mkdir -p "${PZ_DATA_DIR}/Server" \
         "${PZ_DATA_DIR}/db" \
         "${PZ_DATA_DIR}/Saves/Multiplayer" \
         "${PZ_DATA_DIR}/Logs"

chown -R steam:steam "${PZ_DATA_DIR}" 2>/dev/null || true

INI="${PZ_DATA_DIR}/Server/${SERVER_NAME}.ini"
if [ -f "${INI}" ]; then
    echo "[PZ-Server] Configuración existente detectada: ${INI}"
    echo "[PZ-Server] El servidor se iniciará con la configuración ya generada (usa 'reloadoptions' para cambios en caliente)."
else
    echo "[PZ-Server] No existe aún ${INI}."
    echo "[PZ-Server] En el PRIMER arranque el servidor la generará con valores por defecto."
    echo "[PZ-Server] El usuario admin '${ADMIN_USERNAME:-admin}' se creará sin prompt gracias a -adminpassword."
fi

echo "[PZ-Server] Entorno preparado. Toda la configuración del juego se hace desde la interfaz web."
