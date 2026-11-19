#!/bin/bash
# Healthcheck: comprueba el panel web (uvicorn) o el proceso JVM de Project Zomboid.
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"
PANEL_PORT="${PANEL_PORT:-8080}"

if curl -sf "http://127.0.0.1:${PANEL_PORT}/health" > /dev/null 2>&1; then
    exit 0
fi
if curl -sf "http://127.0.0.1:${PANEL_PORT}/login" > /dev/null 2>&1; then
    exit 0
fi
if pgrep -f "zombie.network.GameServer" > /dev/null 2>&1 || pgrep -f "ProjectZomboid64" > /dev/null 2>&1; then
    exit 0
fi

exit 1
