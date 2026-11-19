#!/bin/bash
# Lanzador del servidor dedicado PZ como usuario steam con memoria JVM y argumentos configurados.
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"
export HOME="${HOME:-/home/steam}"

cd "${PZ_SERVER_DIR:?PZ_SERVER_DIR no definido}" || exit 1

if [ -z "${JAVA_TOOL_OPTIONS:-}" ]; then
    export JAVA_TOOL_OPTIONS="-Djava.awt.headless=true -Xms${SERVER_MEMORY_MIN:-4g} -Xmx${SERVER_MEMORY_MAX:-6g}"
    echo "[PZ-Server] JAVA_TOOL_OPTIONS=${JAVA_TOOL_OPTIONS}"
fi

ARGS=(-servername "${SERVER_NAME:-servertest}")
if [ -n "${ADMIN_USERNAME:-}" ]; then
    ARGS+=(-adminusername "${ADMIN_USERNAME}")
fi
if [ -n "${ADMIN_PASSWORD:-}" ]; then
    # Evita el prompt interactivo del primer arranque cuando no hay TTY
    ARGS+=(-adminpassword "${ADMIN_PASSWORD}")
fi
if [ -n "${PZ_DATA_DIR:-}" ]; then
    # PZ requiere el formato exacto -cachedir=<ruta>
    ARGS+=("-cachedir=${PZ_DATA_DIR}")
fi
if [ "${USE_STEAM:-true}" != "true" ]; then
    ARGS+=(-nosteam)
fi
if [ -n "${ADDITIONAL_ARGS:-}" ]; then
    for a in ${ADDITIONAL_ARGS}; do
        ARGS+=("$a")
    done
fi

chmod +x ./start-server.sh ./ProjectZomboid64 ./ProjectZomboid32 2>/dev/null || true
find ./jre64/bin ./jre/bin -type f -exec chmod +x {} + 2>/dev/null || true

# start-server.sh requiere bash; ProjectZomboid64/32 son binarios nativos
if [ -f ./start-server.sh ]; then
    echo "[PZ-Server] Ejecutando: ./start-server.sh ${ARGS[*]}"
    exec bash "./start-server.sh" "${ARGS[@]}"
elif [ -f ./ProjectZomboid64 ]; then
    echo "[PZ-Server] Ejecutando: ./ProjectZomboid64 ${ARGS[*]}"
    exec "./ProjectZomboid64" "${ARGS[@]}"
elif [ -f ./ProjectZomboid32 ]; then
    echo "[PZ-Server] Ejecutando: ./ProjectZomboid32 ${ARGS[*]}"
    exec "./ProjectZomboid32" "${ARGS[@]}"
else
    echo "[PZ-Server] [ERROR] Lanzador ejecutable no encontrado en $(pwd)" >&2
    exit 1
fi
