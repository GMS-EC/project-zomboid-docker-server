# ==============================================================================
# pz-server-docker - Project Zomboid Dedicated Server (Docker)
# Fase 1: Imagen base, entorno Java + Python y scripts de arranque.
#
# Modo Steam  : instalación/actualización vía SteamCMD (AppID 380870) y arranque
#                con integración Steam (USE_STEAM=true).
# Modo No-Steam: NO se ejecuta SteamCMD y el servidor se lanza con el argumento
#                oficial `-nosteam` (USE_STEAM=false) para clientes GOG/no-Steam.
# ==============================================================================
FROM cm2network/steamcmd:root

LABEL org.opencontainers.image.title="Project Zomboid Dedicated Server" \
      org.opencontainers.image.description="Project Zomboid Dedicated Server con modo Steam / No-Steam (GOG), consola por FIFO y panel web en fases posteriores"

# --- Dependencias del sistema -------------------------------------------------
# Java: PZ es un servidor JVM. La build 42 incluye su propio JRE en la carpeta
# del server, pero dejamos openjdk en la imagen como respaldo para builds
# (legacy41 y scripts del lanzador que llaman a `java` del PATH).
RUN set -ex; \
    dpkg --add-architecture i386; \
    apt-get update; \
    if ! apt-get install -y --no-install-recommends openjdk-17-jre-headless; then \
        apt-get install -y --no-install-recommends openjdk-21-jre-headless; \
    fi; \
    apt-get install -y --no-install-recommends \
        curl \
        lsof \
        unzip \
        libc6-i386 \
        lib32gcc-s1 \
        bzip2 \
        gettext-base \
        procps \
        jq \
        python3 \
        python3-pip \
        python3-venv \
        tzdata \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- DepotDownloader (descarga anónima fiable del AppID 380870) -------------------
# SteamCMD a veces falla con 'Failed to install app 380870 (Missing configuration)'
# para este servidor; DepotDownloader (el mismo que usa la referencia
# indifferentbroccoli/projectzomboid-server-docker) descarga sin problema.
RUN curl -sL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh && \
    chmod +x /tmp/dotnet-install.sh && \
    /tmp/dotnet-install.sh --channel 8.0 --runtime dotnet --install-dir /usr/share/dotnet && \
    ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet && \
    rm /tmp/dotnet-install.sh

ARG DEPOT_DOWNLOADER_VERSION=3.4.0
RUN curl -sL \
    "https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_${DEPOT_DOWNLOADER_VERSION}/DepotDownloader-linux-x64.zip" \
    -o /tmp/dd.zip && \
    mkdir -p /depotdownloader && \
    unzip /tmp/dd.zip -d /depotdownloader && \
    chmod -R 755 /depotdownloader && \
    chmod +x /depotdownloader/DepotDownloader && \
    rm /tmp/dd.zip

# --- Variables de entorno: SOLO INFRAESTRUCTURA --------------------------------
# Toda la configuración del JUEGO (nombre, memoria, modos Steam/No-Steam,
# credenciales, rama, mods, horarios...) se gestiona desde la interfaz web
# (Setup/Ajustes) y se persiste en el volumen /app/data.
ENV HOME=/home/steam \
    PUID=1000 \
    PGID=1000 \
    TZ=UTC \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    \
    # --- Rutas de volumen (infra) ---
    PZ_SERVER_DIR="/home/steam/steamcmd/pz" \
    PZ_DATA_DIR="/home/steam/Zomboid" \
    PZ_BACKUPS_DIR="/home/steam/pz-backups" \
    PZ_PANEL_DIR="/app/data" \
    \
    # --- Panel Web (único método de gestión; sin "modo solo servidor") ---
    PANEL_PORT=8080 \
    PANEL_USER="admin" \
    PANEL_PASSWORD="adminpassword"

# --- Directorios ----------------------------------------------------------------
RUN mkdir -p /home/steam/steamcmd/pz /home/steam/Zomboid /home/steam/pz-backups \
             /run/pz /app /app/data && \
    chown -R steam:steam /home/steam/steamcmd/pz /home/steam/Zomboid /home/steam/pz-backups /app /app/data && \
    chmod 0777 /run/pz

# --- Backend del panel web (FastAPI) ----------------------------------------------
WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt || \
    pip3 install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/app/
COPY web/ /app/web/
RUN chown -R steam:steam /app

# --- Scripts de gestión -----------------------------------------------------------
COPY ./scripts /home/steam/scripts/
RUN sed -i 's/\r$//' /home/steam/scripts/*.sh && \
    chmod +x /home/steam/scripts/*.sh && \
    chown -R steam:steam /home/steam/scripts

WORKDIR /home/steam

# Puertos de red Project Zomboid:
#   16261/udp -> Juego (handshake / conexión)
#   16262/udp -> Puerto de conexión directa y listado
#   8080/tcp  -> Panel web (backend FastAPI, Fase 2+)
#   PZ NO expone un servicio RCON tipo Source: la administración es por consola
#   (stdin del proceso), gestionada por el ProcessManager del panel.
EXPOSE 16261/udp 16262/udp 8080/tcp

HEALTHCHECK --start-period=15m --interval=1m --timeout=20s --retries=5 \
            CMD /home/steam/scripts/healthcheck.sh

ENTRYPOINT ["/home/steam/scripts/init.sh"]
