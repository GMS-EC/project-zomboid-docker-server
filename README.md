# Project Zomboid Dedicated Server (Docker + Panel Web)

[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg?logo=docker)](https://www.docker.com/)
[![Project Zomboid](https://img.shields.io/badge/Project%20Zomboid-Build%2042%20%7C%2041-red.svg)](https://projectzomboid.com/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)

Servidor dedicado de **Project Zomboid** en contenedor Docker con **Panel Web de Administracion** integrado (FastAPI + Diseno Moderno). Soporta modos **Steam** y **No-Steam (GOG / -nosteam)**, gestion de mundo, consola interactiva, metricas en tiempo real, respaldos automaticos y notificaciones a Discord.

---

## Caracteristicas Principales

- **Panel Web de Gestion Integrado**:
  - **Asistente de Bienvenida (Setup)**: Configura el nombre del servidor, credenciales de administracion, memoria y modo de conexion antes del primer arranque.
  - **Consola Interactiva**: Visualizacion de registros en vivo mediante WebSocket y envio de comandos de consola/RCON con botones rapidos.
  - **Editor Completo de Ajustes**: Control granular de todas las variables de Server.ini y SandboxVars.lua (dificultad, zombis, botin, vehiculos, etc.) sin editar archivos manualmente.
  - **Metricas del Sistema**: Monitoreo en tiempo real de uso de CPU, RAM JVM (Xms/Xmx), espacio en disco y tiempo activo (*uptime*).
  - **Gestion de Jugadores**: Lista de supervivientes conectados y desconectados con acciones para expulsar (*kick*), banear (*ban*) y enviar mensajes globales.
  - **Programador de Tareas**: Reinicios automaticos periodicos, guardados forzados de mundo y horario de encendido/apagado (*Power Schedule*).
  - **Gestor de Respaldos**: Creacion de copias de seguridad manuales y programadas con restauracion en un clic.
  - **Webhooks de Discord**: Alertas en canales de Discord para eventos clave (servidor online, apagado, reinicio, respaldos, guardados).
- **Soporte Dual Steam & No-Steam**:
  - Descarga anonima y fiable mediante **DepotDownloader** o SteamCMD (AppID 380870).
  - Admite clientes de Steam (con descarga de mods de Workshop) y clientes No-Steam/GOG con bandera -nosteam.
- **Arquitectura Limpia**:
  - Docker se encarga estrictamente de la **infraestructura** (puertos, memoria RAM, volumenes y credenciales del panel).
  - Todo el juego se administra desde la **interfaz web**, persistiendo su estado en volumenes dedicados.

---

## Puertos y Red

| Puerto | Protocolo | Descripcion |
|---|---|---|
| 16261 | UDP | Handshake principal y conexion de jugadores |
| 16262 | UDP | Conexion directa y listado de servidores |
| 8580 | TCP (mapeado a 8080) | Panel Web de Administracion |

---

## Despliegue Rapido

### 1. Clonar el repositorio
`ash
git clone https://github.com/GMS-EC/project-zomboid-docker-server.git
cd project-zomboid-docker-server
`

### 2. Configurar variables de entorno
Copia la plantilla de variables:
`ash
cp .env.example .env
`

Edita .env para ajustar las credenciales del panel web y el limite de memoria del contenedor:
`env
MEM_LIMIT=7g
PANEL_USER=admin
PANEL_PASSWORD=tu_contraseña_segura
TZ=America/Guayaquil
PUID=1000
PGID=1000
`

### 3. Iniciar el contenedor
`ash
docker compose up -d
`

### 4. Configuracion Inicial (Setup)
1. Abre tu navegador e ingresa a: **http://localhost:8580**
2. Inicia sesion con las credenciales definidas en PANEL_USER y PANEL_PASSWORD.
3. Completa el **Asistente de Setup**:
   - Nombre del servidor (SERVER_NAME).
   - Plataforma (Steam o No-Steam).
   - Contrasena de administrador del juego y contrasena de acceso opcional.
   - Memoria RAM JVM (-Xms y -Xmx).
   - Modo de juego (PvE / PvP) y Mods iniciales de Workshop.
4. Presiona **Guardar Configuracion e Iniciar Servidor**. ¡El servidor arrancara con tus preferencias!

---

## Estructura de Volumenes

Los datos se conservan en volumenes persistentes en la raiz del proyecto:

- ./steamcmd/pz/: Binarios y ejecutables del servidor dedicado de PZ.
- ./pz-data/: Datos del mundo, partidas guardadas (Saves/Multiplayer), configuraciones (Server/*.ini, *_SandboxVars.lua) y base de datos SQLite.
- ./pz-backups/: Archivos comprimidos .tar.gz de las copias de seguridad.
- ./pz-config/: Configuracion persistente del panel web (pz_panel_config.json).
