# syntax=docker/dockerfile:1
# Project Zomboid Dedicated Server + Panel Web (FastAPI)
FROM cm2network/steamcmd:root

LABEL org.opencontainers.image.title="Project Zomboid Dedicated Server" \
      org.opencontainers.image.description="Project Zomboid Dedicated Server con modo Steam / No-Steam (GOG) y panel web"

# Dependencias del sistema (PZ incluye su propio JRE en ./jre64)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -ex; \
    export DEBIAN_FRONTEND=noninteractive; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    dpkg --add-architecture i386; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        curl \
        unzip \
        bzip2 \
        procps \
        python3 \
        python3-pip \
        tzdata \
        ca-certificates \
        libc6-i386 \
        lib32gcc-s1

# DepotDownloader autocontenido para descarga anónima de AppID 380870
ARG DEPOT_DOWNLOADER_VERSION=3.4.0
RUN curl -fsSL \
    "https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_${DEPOT_DOWNLOADER_VERSION}/DepotDownloader-linux-x64.zip" \
    -o /tmp/dd.zip && \
    mkdir -p /depotdownloader && \
    unzip -q /tmp/dd.zip -d /depotdownloader && \
    chmod -R 755 /depotdownloader && \
    chmod +x /depotdownloader/DepotDownloader && \
    rm -f /tmp/dd.zip

# Variables de entorno (solo infraestructura; juego se configura en el panel web)
ENV HOME=/home/steam \
    PUID=1000 \
    PGID=1000 \
    TZ=UTC \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    PZ_SERVER_DIR="/home/steam/steamcmd/pz" \
    PZ_DATA_DIR="/home/steam/Zomboid" \
    PZ_BACKUPS_DIR="/home/steam/pz-backups" \
    PZ_PANEL_DIR="/app/data" \
    PANEL_PORT=8080 \
    PANEL_USER="admin" \
    PANEL_PASSWORD="adminpassword"

RUN mkdir -p /home/steam/steamcmd/pz /home/steam/Zomboid /home/steam/pz-backups \
             /run/pz /app /app/data && \
    chown -R steam:steam /home/steam/steamcmd/pz /home/steam/Zomboid /home/steam/pz-backups /app /app/data && \
    chmod 0777 /run/pz

WORKDIR /app
RUN --mount=type=bind,source=requirements.txt,target=/tmp/requirements.txt \
    --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages -r /tmp/requirements.txt || \
    pip3 install -r /tmp/requirements.txt

COPY --chown=steam:steam app/ /app/app/
COPY --chown=steam:steam web/ /app/web/
COPY --chown=steam:steam CHANGELOG.md /app/CHANGELOG.md

COPY --chown=steam:steam ./scripts /home/steam/scripts/
RUN sed -i 's/\r$//' /home/steam/scripts/*.sh && \
    chmod +x /home/steam/scripts/*.sh

WORKDIR /home/steam

# 16261-16262/udp: juego PZ | 8080/tcp: panel web
EXPOSE 16261/udp 16262/udp 8080/tcp

HEALTHCHECK --start-period=15m --interval=1m --timeout=20s --retries=5 \
            CMD /home/steam/scripts/healthcheck.sh

ENTRYPOINT ["/home/steam/scripts/init.sh"]
