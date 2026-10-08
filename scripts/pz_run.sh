#!/bin/bash
# ==============================================================================
# pz_run.sh - Lanzador real del servidor PZ (se ejecuta como usuario `steam`)
# ------------------------------------------------------------------------------
# start.sh delega aquí (vía `su -p steam`) para que el proceso JVM corra con
# el usuario `steam` y las variables de entorno se hereden. Construye la línea
# de argumentos de Project Zomboid, exporta las opciones JVM y ejecuta el
# lanzador del server con su stdin conectado a la FIFO de control.
# ==============================================================================
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"
export HOME="${HOME:-/home/steam}"

cd "${PZ_SERVER_DIR:?PZ_SERVER_DIR no definido}" || exit 1

# --- Argumentos JVM (heap y headless) -------------------------------------------
# JAVA_TOOL_OPTIONS es leída por cualquier JVM que se lance (start-server.sh,
# lanzador nativo o java directo). Si el lanzador hornea -Xmx explícito,
# start.sh ya lo reescribió (OVERRIDE_LAUNCHER_MEMORY=true).
if [ -z "${JAVA_TOOL_OPTIONS:-}" ]; then
    export JAVA_TOOL_OPTIONS="-Djava.awt.headless=true -Xms${SERVER_MEMORY_MIN:-4g} -Xmx${SERVER_MEMORY_MAX:-6g}"
    echo "[PZ-Server] JAVA_TOOL_OPTIONS=${JAVA_TOOL_OPTIONS}"
fi

# --- Argumentos del juego ---------------------------------------------------------
ARGS=(-servername "${SERVER_NAME:-servertest}")
if [ -n "${ADMIN_USERNAME:-}" ]; then
    ARGS+=(-adminusername "${ADMIN_USERNAME}")
fi
if [ -n "${ADMIN_PASSWORD:-}" ]; then
    # Evita el prompt interactivo de creación del admin en el primer arranque
    # (el contenedor no tiene TTY y el stdin es una FIFO, no una consola).
    ARGS+=(-adminpassword "${ADMIN_PASSWORD}")
fi
if [ -n "${PZ_DATA_DIR:-}" ]; then
    # Define dónde vive todo: <Server>/<SERVER_NAME>.ini, Saves/Multiplayer, db.
    # PZ requiere estrictamente el formato -cachedir=<ruta> con signo igual.
    ARGS+=("-cachedir=${PZ_DATA_DIR}")
fi
if [ "${USE_STEAM:-true}" != "true" ]; then
    # Modo No-Steam: desconecta Steamworks para admitir clientes GOG / `-nosteam`.
    ARGS+=(-nosteam)
fi
# Argumentos adicionales definidos por el usuario (separados por espacios)
if [ -n "${ADDITIONAL_ARGS:-}" ]; then
    for a in ${ADDITIONAL_ARGS}; do
        ARGS+=("$a")
    done
fi

echo "[PZ-Server] Argumentos del juego: ${ARGS[*]}"

# --- Permisos de ejecución de respaldo antes del lanzamiento ---
chmod +x ./start-server.sh ./ProjectZomboid64 ./ProjectZomboid32 2>/dev/null || true
find ./jre64/bin ./jre/bin -type f -exec chmod +x {} + 2>/dev/null || true

# --- Selección y ejecución del lanzador ---
# start-server.sh es un script bash; ProjectZomboid64/32 son binarios nativos (no se ejecutan con bash).
if [ -f ./start-server.sh ]; then
    echo "[PZ-Server] Ejecutando: ./start-server.sh ${ARGS[*]}"
    echo "[PZ-Server] La consola del servidor queda enlazada al stdin del proceso."
    exec bash "./start-server.sh" "${ARGS[@]}"
elif [ -f ./ProjectZomboid64 ]; then
    echo "[PZ-Server] Ejecutando binario nativo: ./ProjectZomboid64 ${ARGS[*]}"
    echo "[PZ-Server] La consola del servidor queda enlazada al stdin del proceso."
    exec "./ProjectZomboid64" "${ARGS[@]}"
elif [ -f ./ProjectZomboid32 ]; then
    echo "[PZ-Server] Ejecutando binario nativo: ./ProjectZomboid32 ${ARGS[*]}"
    echo "[PZ-Server] La consola del servidor queda enlazada al stdin del proceso."
    exec "./ProjectZomboid32" "${ARGS[@]}"
else
    echo "[PZ-Server] [ERROR] Lanzador ejecutable no encontrado en $(pwd)" >&2
    exit 1
fi
