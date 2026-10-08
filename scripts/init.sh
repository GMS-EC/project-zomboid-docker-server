#!/bin/bash
# ==============================================================================
# init.sh - Punto de entrada del contenedor pz-server-docker
# ------------------------------------------------------------------------------
# Prepara permisos (PUID/PGID), zona horaria y directorios y arranca SIEMPRE el
# panel web (FastAPI) como usuario `steam`. El panel es el ÚNICO método para
# gestionar el servidor (instalar, iniciar, detener, configurar, consola).
# No existe un "modo solo servidor": todas las variables de juego se configuran
# desde la interfaz web, no por variables de entorno.
# ==============================================================================
set -e

# --- Valores por defecto de entorno (solo infraestructura) ----------------------
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"
export HOME="${HOME:-/home/steam}"
export PZ_SERVER_DIR="${PZ_SERVER_DIR:-/home/steam/steamcmd/pz}"
export PZ_DATA_DIR="${PZ_DATA_DIR:-/home/steam/Zomboid}"
export PZ_BACKUPS_DIR="${PZ_BACKUPS_DIR:-/home/steam/pz-backups}"

echo "================================================="
echo "     pz-server-docker - Project Zomboid Server   "
echo "================================================="

# --- Permisos PUID/PGID ----------------------------------------------------------
if [ -n "${PUID}" ] && [ -n "${PGID}" ]; then
    echo "[PZ-Server] Configurando usuario steam con UID:${PUID} y GID:${PGID}"
    usermod -o -u "${PUID}" steam 2>/dev/null || true
    groupmod -o -g "${PGID}" steam 2>/dev/null || true
fi

# --- Directorios --------------------------------------------------------------
mkdir -p /run/pz "${PZ_SERVER_DIR}" "${PZ_DATA_DIR}" "${PZ_BACKUPS_DIR}" /app /app/data
chmod 0777 /run/pz
chown steam:steam /home/steam /home/steam/steamcmd 2>/dev/null || true
chown -R steam:steam /run/pz /app /app/data "${PZ_BACKUPS_DIR}" 2>/dev/null || true

# Permisos sobre los datos del juego SOLO si el dueño no coincide con PUID
if [ -d "${PZ_DATA_DIR}" ] && [ "$(stat -c '%u' "${PZ_DATA_DIR}" 2>/dev/null)" != "${PUID:-1000}" ]; then
    echo "[PZ-Server] Sincronizando permisos en datos de juego (${PZ_DATA_DIR})..."
    chown -R steam:steam "${PZ_DATA_DIR}" 2>/dev/null || true
fi
if [ -d "${PZ_SERVER_DIR}" ] && [ "$(stat -c '%u' "${PZ_SERVER_DIR}" 2>/dev/null)" != "${PUID:-1000}" ]; then
    echo "[PZ-Server] Sincronizando permisos en archivos del servidor (${PZ_SERVER_DIR})..."
    chown -R steam:steam "${PZ_SERVER_DIR}" 2>/dev/null || true
fi

# --- Zona horaria ---------------------------------------------------------------
if [ -n "${TZ}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    echo "[PZ-Server] Configurando zona horaria del contenedor: ${TZ}"
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

# --- Configuración previa (directorios/estructura) --------------------------------
if [ -f "/home/steam/scripts/generate-config.sh" ]; then
    bash /home/steam/scripts/generate-config.sh
fi

# ==============================================================================
# Arranque del panel web (único método): FastAPI + Uvicorn como usuario steam
# ==============================================================================
echo "[PZ-Server] Lanzando panel web en puerto ${PANEL_PORT:-8080}..."
echo "[PZ-Server] El panel gestiona TODO: instalación, arranque, configuración del juego y consola."
cd /app
exec su -p -s /bin/bash steam -c "export PATH=\"/usr/local/bin:/usr/bin:/bin:/home/steam/bin:\$PATH\"; export HOME=/home/steam; exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port \"${PANEL_PORT:-8080}\""
