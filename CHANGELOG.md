# Changelog

Todos los cambios relevantes de **PZ Server Manager (`pz-server-docker`)** se documentan en este archivo.
El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el proyecto sigue [Versionado Semántico](https://semver.org/lang/es/).

## [0.1.0-dev] - En desarrollo

> Versión inicial en desarrollo activo (pre-release, aún sin lanzamiento estable publicado).

### Añadido
- **Infraestructura Docker dedicada (`1 Contenedor = 1 Servidor`)**: contenedor basado en `cm2network/steamcmd` con descarga automática de binarios de Project Zomboid (AppID `380870`) vía DepotDownloader/SteamCMD, ajuste de permisos `PUID`/`PGID`, ejecución sin `root` (`steam`), apagado seguro (`save` + `quit`) y lectura automática de versión desde `CHANGELOG.md`.
- **Asistente Inicial (Setup / Instalador)**: configuración guiada del perfil (`SERVER_NAME`), plataforma (**Steam** o **No-Steam / GOG `-nosteam`**), contraseñas, memoria JVM (`-Xms` / `-Xmx`), rama (`Estable`, `unstable`, `legacy41`) y progreso de descarga en vivo; se oculta automáticamente al completar la instalación.
- **Consola Interactiva y Control de Servidor**: terminal en tiempo real vía WebSocket con filtrado de logs, descarga de `console.txt`, analizador de **Diagnóstico**, historial de comandos (`↑`/`↓`), desplegable categorizado `Plantillas PZ...` con explicación de sintaxis en vivo y botones **Iniciar / Detener / Reiniciar** sincronizados con el estado del proceso.
- **Métricas en Tiempo Real y Conexión**: monitoreo de CPU, RAM del servidor/JVM, disco y jugadores conectados, junto al banner superior con botón **IP:Puerto** compatible con direcciones personalizadas (**Playit.gg / VPN / Dominio**).
- **Gestión de Supervivientes y Moderación**: vista en línea e historial con columnas independientes de `SteamID` (con copia en 1 clic) y `Rol` (`setaccesslevel`), mensajes directos, anuncios globales (`servermsg`), expulsión (`kick`), baneo/desbaneo y acciones administrativas.
- **Editor Completo de Ajustes y Sandbox**: configuración visual de `<SERVER_NAME>.ini`, `*_SandboxVars.lua`, `spawnregions.lua`, plantillas rápidas de Sandbox, recarga en caliente (`reloadoptions`), editor Raw directo, **Wipe de Mundo (Día 1)** y adaptación automática por versión (**No-Steam / GOG** oculta y deshabilita opciones exclusivas de Steam como `Public`, `SteamVAC`, `SteamScoreboard` y Workshop).
- **Gestor de Mods de Steam Workshop**: resolución de ítems y colecciones de Workshop con sincronización separada de `WorkshopItems=` y `Mods=` (deshabilitado automáticamente en modo No-Steam/GOG).
- **Gestor de Archivos (`/Zomboid`)**: explorador con subida múltiple (arrastrar y soltar), creación/edición/renombrado/duplicado/eliminación de archivos y carpetas y compresión/extracción `.zip`.
- **Respaldos Selectivos y Tareas Programadas**: copias de seguridad manuales o programadas por ámbito (`Saves`, `Server`, `db`) en `.tar.gz` o directorio con políticas de retención (`max_keep`, `max_days`), automatización por intervalos, expresiones **Cron** en Python puro, horario de encendido/apagado y avisos previos en partida.
- **Webhooks Multicanal y Auditoría**: alertas configurables para **Discord**, **Telegram** y **Email (SMTP)** con pruebas por canal, además de registros de actividad filtrables y exportables a **CSV**.
- **Portada Pública Personalizable (`Portada`)**: página inicial con datos automáticos del servidor (`PublicName`/`SERVER_NAME`, `PublicDescription`, capacidad y dirección `IP:Puerto`), personalizable en tema/acento, aviso destacado, etiquetas, normas, enlace a Discord y visibilidad de jugadores conectados, activable o desactivable desde el panel con el acceso de administración en la parte inferior.
- **Seguridad del Panel**: cookies de sesión firmadas con HMAC y nonce único, protección contra fuerza bruta (`429`), cabeceras HTTP de seguridad (CSP, `X-Frame-Options`, `X-Content-Type-Options`) y validación de rutas en el gestor de archivos.
