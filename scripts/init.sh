#!/bin/bash
# Punto de entrada: prepara permisos, zona horaria y arranca el panel FastAPI como usuario steam.
set -e

export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"
export HOME="${HOME:-/home/steam}"
export PZ_SERVER_DIR="${PZ_SERVER_DIR:-/home/steam/steamcmd/pz}"
export PZ_DATA_DIR="${PZ_DATA_DIR:-/home/steam/Zomboid}"
export PZ_BACKUPS_DIR="${PZ_BACKUPS_DIR:-/home/steam/pz-backups}"

echo "[PZ-Server] Iniciando contenedor pz-server-docker..."

if [ -n "${PUID}" ] && [ -n "${PGID}" ]; then
    usermod -o -u "${PUID}" steam 2>/dev/null || true
    groupmod -o -g "${PGID}" steam 2>/dev/null || true
fi

mkdir -p /run/pz "${PZ_SERVER_DIR}" "${PZ_DATA_DIR}" "${PZ_BACKUPS_DIR}" /app /app/data
chmod 0777 /run/pz
chown steam:steam /home/steam /home/steam/steamcmd 2>/dev/null || true
chown -R steam:steam /run/pz /app /app/data "${PZ_BACKUPS_DIR}" 2>/dev/null || true

# Ajustar permisos de volúmenes pesados solo si cambia el UID propietario
if [ -d "${PZ_DATA_DIR}" ] && [ "$(stat -c '%u' "${PZ_DATA_DIR}" 2>/dev/null)" != "${PUID:-1000}" ]; then
    chown -R steam:steam "${PZ_DATA_DIR}" 2>/dev/null || true
fi
if [ -d "${PZ_SERVER_DIR}" ] && [ "$(stat -c '%u' "${PZ_SERVER_DIR}" 2>/dev/null)" != "${PUID:-1000}" ]; then
    chown -R steam:steam "${PZ_SERVER_DIR}" 2>/dev/null || true
fi

if [ -n "${TZ}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

if [ -f "/home/steam/scripts/generate-config.sh" ]; then
    bash /home/steam/scripts/generate-config.sh
fi

echo "[PZ-Server] Lanzando panel web en puerto ${PANEL_PORT:-8080}..."
cd /app
exec su -p -s /bin/bash steam -c "export PATH=\"/usr/local/bin:/usr/bin:/bin:/home/steam/bin:\$PATH\"; export HOME=/home/steam; exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port \"${PANEL_PORT:-8080}\""
