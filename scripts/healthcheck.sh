#!/bin/bash
# ==============================================================================
# healthcheck.sh - Verificación de salud del contenedor pz-server-docker
# ------------------------------------------------------------------------------
# Prioridad 1: el panel web responde (uvicorn es el PID 1; el servidor PZ puede
# estar legítimamente OFFLINE hasta que se inicie desde el panel).
# Prioridad 2: si el proceso JVM del servidor PZ (zombie.network.GameServer)
# está vivo, el contenedor también se considera sano.
# ==============================================================================
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"
PANEL_PORT="${PANEL_PORT:-8080}"

# 1. Panel web (por defecto)
if curl -sf "http://127.0.0.1:${PANEL_PORT}/health" > /dev/null 2>&1; then
    exit 0
fi
if curl -sf "http://127.0.0.1:${PANEL_PORT}/login" > /dev/null 2>&1; then
    exit 0
fi

# 2. Proceso JVM del servidor de PZ corriendo (modo solo-servidor)
if pgrep -f "zombie.network.GameServer" > /dev/null 2>&1; then
    exit 0
fi
if pgrep -f "ProjectZomboid64" > /dev/null 2>&1; then
    exit 0
fi

exit 1
