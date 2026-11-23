// --- Sanitización XSS Global ---
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// Escapa comillas simples para strings inline en HTML onclick="..."
function attrJsStr(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\r/g, '\\r')
        .replace(/\n/g, '\\n')
        .replace(/\u2028/g, '\\u2028')
        .replace(/\u2029/g, '\\u2029')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

window.escapeHtml = escapeHtml;
window.attrJsStr = attrJsStr;

window.formatBytes = function (bytes) {
    const b = Number(bytes || 0);
    if (!Number.isFinite(b) || b <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const idx = Math.min(units.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
    const val = b / Math.pow(1024, idx);
    return `${idx === 0 ? Math.round(val) : val.toFixed(1)} ${units[idx]}`;
};

window.readApiJson = async function (res) {
    const ct = (res.headers.get('content-type') || '').toLowerCase();
    if (ct.includes('application/json')) {
        try {
            return await res.json();
        } catch {
            return {};
        }
    }
    const text = await res.text();
    try {
        return JSON.parse(text);
    } catch {
        return { detail: text || res.statusText || `HTTP ${res.status}` };
    }
};

(function () {
    const _origFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const opts = init ? { ...init } : {};
        if (url.startsWith('/api/') && !opts.cache) {
            opts.cache = 'no-store';
        }
        const res = await _origFetch(input, opts);
        if (res.status === 401 && url.startsWith('/api/')) {
            window.location.href = '/login';
        }
        return res;
    };
})();

// PZ Server Manager Main Client Script
let metricsChart = null;
let currentInstanceId = "main";
let isAutoScroll = true;
let commandHistory = JSON.parse(localStorage.getItem("pz_cmd_history") || localStorage.getItem("ark_cmd_history") || "[]");
let cmdHistoryIndex = -1;
let cmdDraft = "";

// Inicialización
document.addEventListener("DOMContentLoaded", () => {
    // Scroll horizontal con la rueda del ratón en la barra de pestañas
    const navTabsContainer = document.querySelector(".nav-tabs");
    if (navTabsContainer) {
        navTabsContainer.addEventListener("wheel", (e) => {
            if (e.deltaY !== 0) {
                e.preventDefault();
                navTabsContainer.scrollLeft += e.deltaY;
            }
        }, { passive: false });
    }

    initTabs();
    initWebSocket();
    initMetricsPolling();
    initChart();
    loadPlayers();
    loadSettings();
    const wizSteam = document.getElementById("wizard-steam");
    if (wizSteam) onWizardSteamChange(wizSteam.value);
    loadMods();
    initConsoleHistory();

    // Si falta setup o instalación, abrir siempre en el instalador antes de restaurar la última pestaña
    const installerPane = document.getElementById("tab-installer");
    const needsSetup = installerPane && installerPane.dataset.needsSetup === "true";
    if (needsSetup) {
        switchTab("installer");
        fetch("/api/status").then(r => r.json()).then(st => {
            if (st && (st.status === "INSTALLING" || (st.install_progress && st.install_progress.running))) {
                pollInstallerProgress();
            }
        }).catch(() => {});
    } else {
        const hash = window.location.hash ? window.location.hash.substring(1) : "";
        const savedTab = hash || localStorage.getItem("pz_active_tab");
        if (savedTab && savedTab !== "console" && document.getElementById(`tab-${savedTab}`)) {
            switchTab(savedTab);
        }
    }
});

// --- Pestañas ---
function initTabs() {
    const navItems = document.querySelectorAll(".nav-btn, .nav-item");
    navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const tabId = item.getAttribute("data-tab");
            switchTab(tabId);
        });
    });
}

function switchTab(tabId) {
    if (typeof App !== "undefined") {
        App.activeTab = tabId;
    }
    document.querySelectorAll(".nav-btn, .nav-item").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));

    const navLink = document.querySelector(`.nav-btn[data-tab="${tabId}"], .nav-item[data-tab="${tabId}"]`);
    const targetPane = document.getElementById(`tab-${tabId}`);

    if (navLink) navLink.classList.add("active");
    if (targetPane) targetPane.classList.add("active");

    localStorage.setItem("pz_active_tab", tabId);
    if (window.history.replaceState) {
        window.history.replaceState(null, null, `#${tabId}`);
    }

    if (tabId === "metrics") {
        if (!metricsChart) {
            initChart();
        } else {
            metricsChart.resize();
        }
        fetchMetricsOnce();
    }

    if (tabId === "players") {
        loadPlayers();
    }

    if (tabId === "tasks" && typeof Tasks !== "undefined") {
        Tasks.loadTasks();
    }

    if (tabId === "backups" && typeof Backups !== "undefined") {
        Backups.loadBackups();
    }

    if (tabId === "webhooks" && typeof Webhooks !== "undefined") {
        Webhooks.loadConfig();
    }

    if (tabId === "portal") {
        Portal.loadConfig();
    }

    if (tabId === "mods") {
        loadMods();
    }

    if (tabId === "logs") {
        if (typeof Logs !== "undefined" && typeof Logs.loadLogs === "function") {
            Logs.loadLogs(true);
        }
    }

    if (tabId === "files") {
        if (typeof Files !== "undefined") {
            Files.loadDirectory(Files.currentPath || "");
        }
    } else {
        if (typeof Files !== "undefined" && Files.hideContextMenu) {
            Files.hideContextMenu();
        }
    }
}

// --- Portada Pública del Servidor ---
const Portal = {
    async loadConfig() {
        try {
            const res = await fetch("/api/portal");
            const data = await window.readApiJson(res);
            const setVal = (id, v) => {
                const el = document.getElementById(id);
                if (el && v !== undefined && v !== null) el.value = String(v);
            };
            const enabledEl = document.getElementById("portal-landing-enabled");
            if (enabledEl) enabledEl.checked = data.landing_enabled !== false;
            setVal("portal-landing-accent", data.landing_accent || "emerald");
            setVal("portal-landing-subtitle", data.landing_subtitle || "");
            setVal("portal-landing-announcement", data.landing_announcement || "");
            setVal("portal-landing-tags", data.landing_tags || "");
            setVal("portal-landing-discord-url", data.landing_discord_url || "");
            setVal("portal-landing-mods-note", data.landing_mods_note || "");
            setVal("portal-landing-show-players", data.landing_show_players !== false ? "true" : "false");
            setVal("portal-landing-show-online-names", data.landing_show_online_names ? "true" : "false");
            setVal("portal-landing-show-rules", data.landing_show_rules !== false ? "true" : "false");
            setVal("portal-landing-rules", data.landing_rules || "");

            const liveName = document.getElementById("portal-live-server-name");
            const liveAddr = document.getElementById("portal-live-address");
            const livePlayers = document.getElementById("portal-live-players");
            const liveDesc = document.getElementById("portal-live-description");
            const effName = data.public_name || data.server_name || "servertest";
            if (liveName) liveName.textContent = data.public_name && data.public_name !== data.server_name ? `${data.public_name} (${data.server_name})` : effName;
            if (liveAddr) liveAddr.textContent = data.public_address || `${window.location.hostname || "localhost"}:${data.server_port || 16261} (UDP ${data.direct_port || 16262})`;
            if (livePlayers) livePlayers.textContent = `${data.max_players || 16} jugadores`;
            if (liveDesc) liveDesc.textContent = data.public_description || "Sin descripción definida en Ajustes (.ini)";

            this.onToggleEnabled();
        } catch (e) {
            console.error("Error cargando configuración de portada:", e);
        }
    },

    onToggleEnabled() {
        const enabledEl = document.getElementById("portal-landing-enabled");
        const pill = document.getElementById("portal-status-pill");
        const fields = document.getElementById("portal-editor-fields");
        const isEnabled = enabledEl ? enabledEl.checked : true;
        if (pill) {
            pill.textContent = isEnabled ? "Habilitada" : "Deshabilitada (solo login)";
            pill.style.background = isEnabled ? "rgba(60, 163, 116, 0.16)" : "rgba(139, 148, 158, 0.14)";
            pill.style.color = isEnabled ? "#7ee2b4" : "#8b949e";
            pill.style.borderColor = isEnabled ? "rgba(60, 163, 116, 0.35)" : "rgba(139, 148, 158, 0.3)";
        }
        if (fields) {
            fields.style.opacity = isEnabled ? "1" : "0.65";
        }
    },

    async saveConfig() {
        const getVal = (id) => {
            const el = document.getElementById(id);
            return el ? el.value : "";
        };
        const enabledEl = document.getElementById("portal-landing-enabled");
        const payload = {
            landing_enabled: enabledEl ? enabledEl.checked : true,
            landing_accent: getVal("portal-landing-accent") || "emerald",
            landing_subtitle: getVal("portal-landing-subtitle"),
            landing_announcement: getVal("portal-landing-announcement"),
            landing_tags: getVal("portal-landing-tags"),
            landing_discord_url: getVal("portal-landing-discord-url"),
            landing_mods_note: getVal("portal-landing-mods-note"),
            landing_show_players: getVal("portal-landing-show-players") !== "false",
            landing_show_online_names: getVal("portal-landing-show-online-names") === "true",
            landing_show_rules: getVal("portal-landing-show-rules") !== "false",
            landing_rules: getVal("portal-landing-rules"),
        };

        try {
            const res = await fetch("/api/portal", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await window.readApiJson(res);
            if (data.success) {
                showToast("Portada pública guardada correctamente.", "success");
                this.loadConfig();
                loadSettings();
                fetchMetricsOnce();
            } else {
                showToast("No se pudo guardar la portada.", "error");
            }
        } catch (e) {
            showToast("Error de conexión al guardar la portada.", "error");
        }
    },
};

// --- WebSocket de Consola ---
let ws = null;
let wsReconnectTimer = null;
let wsShouldReconnect = true;

function scheduleWsReconnect() {
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(initWebSocket, 3000);
}

function initWebSocket() {
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const instParam = encodeURIComponent(currentInstanceId || "main");
    const wsUrl = `${protocol}//${window.location.host}/ws/console?instance=${instParam}`;
    const consoleOutput = document.getElementById("console-output");

    let socket;
    try {
        socket = new WebSocket(wsUrl);
    } catch (e) {
        scheduleWsReconnect();
        return;
    }
    ws = socket;

    socket.onmessage = (event) => {
        if (!consoleOutput) return;
        const text = event.data;
        // Heartbeat del servidor: no se muestra en la consola
        if (text === "\u200b") return;
        const line = document.createElement("div");
        line.textContent = text;
        consoleOutput.appendChild(line);

        // Optimización: Limitar el DOM a un máximo de 1.000 líneas visibles
        while (consoleOutput.children.length > 1000) {
            consoleOutput.removeChild(consoleOutput.firstChild);
        }

        if (isAutoScroll) {
            consoleOutput.scrollTop = consoleOutput.scrollHeight;
        }
    };

    if (consoleOutput && !consoleOutput.dataset.scrollBound) {
        consoleOutput.dataset.scrollBound = "true";
        consoleOutput.addEventListener("scroll", () => {
            const distanceFromBottom = consoleOutput.scrollHeight - consoleOutput.scrollTop - consoleOutput.clientHeight;
            const btn = document.getElementById("btn-autoscroll");
            const text = document.getElementById("autoscroll-text");
            if (distanceFromBottom > 40) {
                isAutoScroll = false;
                if (btn) {
                    btn.style.borderColor = "#d29922";
                    btn.style.color = "#e3b341";
                }
                if (text) text.textContent = "Auto-scroll: PAUSADO";
            } else {
                isAutoScroll = true;
                if (btn) {
                    btn.style.borderColor = "#238636";
                    btn.style.color = "#3fb950";
                }
                if (text) text.textContent = "Auto-scroll: ON";
            }
        });
    }

    socket.onclose = (ev) => {
        // Evitar reconexiones duplicadas de sockets antiguos
        if (ws !== socket) return;
        ws = null;
        if (ev && ev.code === 1008) {
            wsShouldReconnect = false;
            return;
        }
        if (wsShouldReconnect) {
            scheduleWsReconnect();
        }
    };
}

function toggleAutoScroll() {
    const consoleOutput = document.getElementById("console-output");
    isAutoScroll = !isAutoScroll;
    const btn = document.getElementById("btn-autoscroll");
    const text = document.getElementById("autoscroll-text");
    if (isAutoScroll) {
        if (btn) {
            btn.style.borderColor = "#238636";
            btn.style.color = "#3fb950";
        }
        if (text) text.textContent = "Auto-scroll: ON";
        if (consoleOutput) consoleOutput.scrollTop = consoleOutput.scrollHeight;
    } else {
        if (btn) {
            btn.style.borderColor = "#d29922";
            btn.style.color = "#e3b341";
        }
        if (text) text.textContent = "Auto-scroll: PAUSADO";
    }
}

const PZ_CONSOLE_COMMANDS = {
    players: { template: "players", desc: "Muestra la lista de supervivientes conectados actualmente." },
    servermsg: { template: 'servermsg "<mensaje>"', desc: "Envía un anuncio global visible en pantalla para todos los jugadores." },
    kickuser: { template: 'kickuser "<usuario>" -r "<razón>"', desc: "Expulsa a un jugador conectado indicando una razón opcional." },
    banuser: { template: 'banuser "<usuario>" -ip -r "<razón>"', desc: "Banea al jugador por cuenta y opcionalmente por IP (-ip)." },
    unbanuser: { template: 'unbanuser "<usuario>"', desc: "Revoca el baneo de una cuenta de jugador." },
    setaccesslevel: { template: 'setaccesslevel "<usuario>" <admin|moderator|gm|observer|none>', desc: "Asigna o quita el nivel de acceso/rol dentro del servidor." },
    adduser: { template: 'adduser "<usuario>" "<clave>"', desc: "Crea manualmente una cuenta de usuario en la base de datos del servidor." },
    addalltowhitelist: { template: "addalltowhitelist", desc: "Añade a la whitelist a todos los jugadores conectados en este momento." },
    addusertowhitelist: { template: 'addusertowhitelist "<usuario>"', desc: "Autoriza a un usuario específico en la whitelist del servidor." },
    removeuserfromwhitelist: { template: 'removeuserfromwhitelist "<usuario>"', desc: "Elimina a un usuario de la whitelist del servidor." },
    teleport: { template: 'teleport "<usuario_origen>" "<usuario_destino>"', desc: "Teletransporta al primer jugador hacia la posición del segundo." },
    teleportto: { template: "teleportto <x>,<y>,<z>", desc: "Teletransporta al administrador a las coordenadas indicadas del mapa." },
    godmod: { template: 'godmod "<usuario>" -true', desc: "Activa (-true) o desactiva (-false) la invulnerabilidad para un jugador." },
    invisible: { template: 'invisible "<usuario>" -true', desc: "Vuelve invisible (-true) o visible (-false) al jugador frente a zombis." },
    noclip: { template: 'noclip "<usuario>" -true', desc: "Permite (-true) atravesar paredes y moverse sin colisiones." },
    additem: { template: 'additem "<usuario>" <Base.Katana> 1', desc: "Entrega un ítem del juego al inventario del jugador (ej. Base.Axe)." },
    addxp: { template: 'addxp "<usuario>" <Carpentry=500>', desc: "Suma puntos de experiencia a una habilidad (Carpentry, Aiming, Mechanics...)." },
    addvehicle: { template: 'addvehicle <Base.CarNormal> "<usuario>"', desc: "Genera un vehículo junto al jugador indicado." },
    startrain: { template: "startrain <50>", desc: "Inicia lluvia en el servidor; puedes indicar intensidad opcional (1-100)." },
    stoprain: { template: "stoprain", desc: "Detiene la lluvia actual y despeja el clima." },
    chopper: { template: "chopper", desc: "Activa el evento de helicóptero sobre un jugador aleatorio." },
    gunshot: { template: "gunshot", desc: "Reproduce un sonido de disparo lejano para mover zombis en la zona." },
    alarm: { template: "alarm", desc: "Dispara la alarma de un edificio cercano a los jugadores." },
    lightning: { template: 'lightning "<usuario>"', desc: "Hace caer un rayo cerca de la posición del jugador indicado." },
    thunder: { template: 'thunder "<usuario>"', desc: "Reproduce un trueno en la posición del jugador indicado." },
    createhorde: { template: 'createhorde <50> "<usuario>"', desc: "Genera una horda de N zombis alrededor del jugador indicado." },
    save: { template: "save", desc: "Fuerza el guardado inmediato del estado del mundo en disco." },
    reloadoptions: { template: "reloadoptions", desc: "Recarga los ajustes de Server.ini sin necesidad de reiniciar." },
    showoptions: { template: "showoptions", desc: "Imprime en consola las opciones activas del archivo Server.ini." },
    changeoption: { template: 'changeoption <Clave> "<Valor>"', desc: "Modifica en caliente una clave de configuración de Server.ini." },
    checkModsNeedUpdate: { template: "checkModsNeedUpdate", desc: "Comprueba si existen actualizaciones pendientes en los mods de Workshop." },
    help: { template: "help", desc: "Lista en consola los comandos nativos soportados por el servidor PZ." },
    quit: { template: "quit", desc: "Guarda el mundo y detiene el proceso del servidor de forma segura." }
};

function updateConsoleCommandHint(rawVal) {
    const box = document.getElementById("console-cmd-hint");
    const syntaxEl = document.getElementById("console-cmd-hint-syntax");
    const descEl = document.getElementById("console-cmd-hint-desc");
    if (!box || !syntaxEl || !descEl) return;

    const token = String(rawVal || "").trim().split(/\s+/)[0];
    const entry = PZ_CONSOLE_COMMANDS[token] || Object.entries(PZ_CONSOLE_COMMANDS).find(([k]) => k.toLowerCase() === token.toLowerCase())?.[1];
    if (!entry) {
        box.style.display = "none";
        return;
    }
    syntaxEl.textContent = entry.template;
    descEl.textContent = entry.desc;
    box.style.display = "flex";
}

function clearConsoleCommandHint() {
    const box = document.getElementById("console-cmd-hint");
    if (box) box.style.display = "none";
}

function applyConsoleCommandTemplate(cmdKey) {
    const select = document.getElementById("console-cmd-preset");
    const input = document.getElementById("console-input");
    const entry = PZ_CONSOLE_COMMANDS[cmdKey];
    if (!entry || !input) return;

    input.value = entry.template;
    updateConsoleCommandHint(cmdKey);
    input.focus();

    // Selecciona el primer marcador <...> para agilizar la edición sin borrar el resto
    const start = entry.template.indexOf("<");
    const end = entry.template.indexOf(">", start + 1);
    if (start !== -1 && end !== -1) {
        input.setSelectionRange(start, end + 1);
    } else {
        input.setSelectionRange(entry.template.length, entry.template.length);
    }
    if (select) select.value = "";
}

function initConsoleHistory() {
    const input = document.getElementById("console-input");
    if (!input || input.dataset.historyBound) return;
    input.dataset.historyBound = "true";

    input.addEventListener("input", () => updateConsoleCommandHint(input.value));

    input.addEventListener("keydown", (e) => {
        if (e.key === "ArrowUp") {
            if (commandHistory.length === 0) return;
            e.preventDefault();
            if (cmdHistoryIndex === -1) {
                cmdDraft = input.value;
            }
            if (cmdHistoryIndex < commandHistory.length - 1) {
                cmdHistoryIndex++;
                input.value = commandHistory[commandHistory.length - 1 - cmdHistoryIndex];
                input.setSelectionRange(input.value.length, input.value.length);
                updateConsoleCommandHint(input.value);
            }
        } else if (e.key === "ArrowDown") {
            if (cmdHistoryIndex > 0) {
                e.preventDefault();
                cmdHistoryIndex--;
                input.value = commandHistory[commandHistory.length - 1 - cmdHistoryIndex];
                input.setSelectionRange(input.value.length, input.value.length);
                updateConsoleCommandHint(input.value);
            } else if (cmdHistoryIndex === 0) {
                e.preventDefault();
                cmdHistoryIndex = -1;
                input.value = cmdDraft;
                updateConsoleCommandHint(input.value);
            }
        }
    });
}

async function copyTextToClipboard(text) {
    if (!text) return false;
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) { /* usar fallback textarea */ }
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try {
        ok = document.execCommand("copy");
    } catch (e) {
        ok = false;
    }
    document.body.removeChild(ta);
    return ok;
}

async function copyServerAddress() {
    let port = 16261;
    let publicAddr = (cachedSettingsData && cachedSettingsData.panel && cachedSettingsData.panel.public_address) || "";
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        cachedSettingsData = data;
        if (data.panel && data.panel.public_address) {
            publicAddr = String(data.panel.public_address).trim();
        } else {
            publicAddr = "";
        }
        port = (data.server && data.server.DefaultPort) || (data.panel && data.panel.server_port) || 16261;
    } catch (e) { /* usar valores en caché o por defecto */ }

    const host = window.location.hostname || "127.0.0.1";
    const link = publicAddr || `${host}:${port}`;
    const copied = await copyTextToClipboard(link);
    if (copied) {
        showToast(`Dirección copiada: ${link}`, "success");
    } else {
        showToast(`No se pudo copiar automáticamente. Usa: ${link}`, "error");
    }
}

function sendConsoleCommand() {
    const input = document.getElementById("console-input");
    if (!input || !input.value.trim()) return;
    const cmd = input.value.trim();

    // Guardar comando en historial
    if (commandHistory.length === 0 || commandHistory[commandHistory.length - 1] !== cmd) {
        commandHistory.push(cmd);
        if (commandHistory.length > 50) commandHistory.shift();
        localStorage.setItem("pz_cmd_history", JSON.stringify(commandHistory));
    }
    cmdHistoryIndex = -1;
    cmdDraft = "";

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(cmd);
    } else {
        fetch("/api/server/command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: cmd })
        });
    }
    input.value = "";
    clearConsoleCommandHint();
}

// --- Controles de Servidor (Project Zomboid) ---
function updateControlButtons(status) {
    const st = String(status || "OFFLINE").toUpperCase();
    const btnStart = document.getElementById("btn-server-start");
    const btnStop = document.getElementById("btn-server-stop");
    const btnRestart = document.getElementById("btn-server-restart");
    if (btnStart) btnStart.disabled = st !== "OFFLINE";
    if (btnStop) btnStop.disabled = st !== "RUNNING" && st !== "STARTING";
    if (btnRestart) btnRestart.disabled = st !== "RUNNING";
}

function updateInstallerTabVisibility(isInstalled, isSetupDone) {
    const ready = Boolean(isInstalled && isSetupDone);
    const btn = document.getElementById("tab-btn-installer");
    if (btn) btn.style.display = ready ? "none" : "";
    const instPane = document.getElementById("tab-installer");
    if (instPane) instPane.dataset.needsSetup = ready ? "false" : "true";
}

async function startServer() {
    showToast("Iniciando servidor de Project Zomboid...", "info");
    updateControlButtons("STARTING");
    try {
        const res = await fetch("/api/server/start", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Servidor de PZ arrancando (estado: " + (data.status || "STARTING") + ").", "success");
            fetchMetricsOnce();
        } else {
            showToast(data.error || "No se pudo iniciar el servidor.", "error");
            updateControlButtons("OFFLINE");
            if (data.is_setup_done === false) {
                updateInstallerTabVisibility(false, false);
                switchTab("installer");
            }
        }
    } catch (e) {
        updateControlButtons("OFFLINE");
        showToast("Error de conexión al iniciar el servidor.", "error");
    }
}

async function stopServer() {
    const ok = await App.confirm({
        title: "Detener Servidor",
        message: "¿Deseas detener el servidor de PZ? Se enviará 'save' y luego 'quit' a la consola para un apagado limpio.",
        confirmText: "Detener Servidor",
        danger: true
    });
    if (!ok) return;
    showToast("Deteniendo servidor (save + quit)...", "info");
    updateControlButtons("STOPPING");
    try {
        const res = await fetch("/api/server/stop", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Servidor detenido.", "success");
        }
    } finally {
        fetchMetricsOnce();
    }
}

async function restartServer() {
    const ok = await App.confirm({
        title: "Reiniciar Servidor",
        message: "¿Deseas reiniciar el servidor de PZ inmediatamente? Se guardará el mundo antes del reinicio.",
        confirmText: "Reiniciar Ahora",
        warning: true
    });
    if (!ok) return;
    showToast("Reiniciando servidor...", "info");
    updateControlButtons("STOPPING");
    try {
        await fetch("/api/server/restart", { method: "POST" });
    } finally {
        fetchMetricsOnce();
    }
}

// --- Acciones Rápidas (consola PZ) ---
async function triggerBroadcast() {
    const msg = await App.prompt({
        title: "Anuncio a Jugadores (servermsg)",
        message: "Escribe el mensaje que se enviará en vivo a todos los jugadores conectados:",
        placeholder: "ej: Reinicio en 10 minutos por mantenimiento...",
        confirmText: "Enviar Anuncio"
    });
    if (!msg || !msg.trim()) return;
    showToast("Enviando servermsg...", "info");
    const res = await fetch("/api/server/broadcast", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg })
    });
    const data = await res.json();
    if (data.success) {
        showToast("Aviso enviado a los jugadores.", "success");
    }
}

// --- Métricas y Gráfico ---
function initChart() {
    const ctx = document.getElementById("metrics-chart");
    if (!ctx) return;

    metricsChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "CPU (%)",
                    borderColor: "#10b981",
                    backgroundColor: "rgba(16, 185, 129, 0.1)",
                    data: [],
                    tension: 0.3,
                    fill: true,
                    pointRadius: 2,
                    pointHoverRadius: 4
                },
                {
                    label: "RAM Servidor (GB)",
                    borderColor: "#06b6d4",
                    backgroundColor: "rgba(6, 182, 212, 0.1)",
                    data: [],
                    tension: 0.3,
                    fill: true,
                    pointRadius: 2,
                    pointHoverRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, grid: { color: "rgba(255,255,255,0.05)" } },
                x: { grid: { display: false } }
            },
            plugins: {
                legend: { labels: { color: "#94a3b8" } }
            }
        }
    });
}

let metricsPollTimer = null;

function onWizardSteamChange(val) {
    const isSteam = String(val) !== "false";
    const section = document.getElementById("wizard-mods-section");
    const input = document.getElementById("wizard-mods");
    if (section) section.style.display = isSteam ? "block" : "none";
    if (input) {
        input.disabled = !isSteam;
        if (!isSteam) input.value = "";
    }
}

function applySteamModeUI(isSteam) {
    const enabled = Boolean(isSteam);
    const tabBtn = document.getElementById("tab-btn-mods");
    if (tabBtn) tabBtn.style.display = enabled ? "" : "none";

    const notice = document.getElementById("mods-nosteam-notice");
    const steamContent = document.getElementById("mods-steam-content");
    if (notice) notice.style.display = enabled ? "none" : "block";
    if (steamContent) {
        steamContent.style.display = enabled ? "" : "none";
        steamContent.querySelectorAll("input, textarea, select, button").forEach(el => {
            el.disabled = !enabled;
        });
    }

    const settingsBadge = document.getElementById("settings-mode-badge");
    if (settingsBadge) {
        settingsBadge.textContent = enabled ? "Versión: Steam (Workshop + VAC)" : "Versión: No-Steam / GOG (-nosteam)";
        settingsBadge.style.background = enabled ? "rgba(56, 139, 253, 0.14)" : "rgba(210, 153, 34, 0.14)";
        settingsBadge.style.color = enabled ? "#79c0ff" : "#e3b341";
        settingsBadge.style.borderColor = enabled ? "rgba(56, 139, 253, 0.35)" : "rgba(210, 153, 34, 0.35)";
    }
    const settingsNotice = document.getElementById("settings-nosteam-notice");
    if (settingsNotice) settingsNotice.style.display = enabled ? "none" : "flex";

    document.querySelectorAll(".steam-only-setting").forEach(wrapper => {
        wrapper.style.display = enabled ? "" : "none";
        wrapper.querySelectorAll("input, select, textarea").forEach(el => {
            el.disabled = !enabled;
        });
    });

    if (!enabled && App.activeTab === "mods") {
        switchTab("settings");
    }
}

async function fetchMetricsOnce() {
    try {
        const res = await fetch("/api/metrics");
        const data = await res.json();
        const curr = data.current;
        const isOffline = curr.status === "OFFLINE";
        updateControlButtons(curr.status);
        if (curr.is_installed !== undefined && curr.is_setup_done !== undefined) {
            updateInstallerTabVisibility(curr.is_installed, curr.is_setup_done);
        }
        if (curr.steam_mode !== undefined) {
            applySteamModeUI(curr.steam_mode);
        }
        const topPortEl = document.getElementById("top-server-port");
        const topPortLabel = document.getElementById("top-server-port-label");
        if (topPortEl && curr.server_port !== undefined) {
            const pub = String(curr.public_address || "").trim();
            topPortEl.textContent = pub || `${curr.server_port} (UDP)`;
            if (topPortLabel) topPortLabel.textContent = pub ? "Dirección Pública:" : "Puerto de Juego:";
        }
        const consoleVerEl = document.getElementById("console-pz-version");
        if (consoleVerEl && (curr.pz_version !== undefined || curr.branch !== undefined)) {
            if (curr.pz_version) {
                consoleVerEl.textContent = `PZ v${curr.pz_version}`;
            } else if (curr.branch) {
                consoleVerEl.textContent = `Rama: ${curr.branch}`;
            } else {
                consoleVerEl.textContent = "PZ Estable";
            }
        }

        // Actualizar Tarjetas de Métricas
        if (document.getElementById("val-cpu")) document.getElementById("val-cpu").textContent = `${curr.cpu_percent}%`;
        if (document.getElementById("val-ram")) document.getElementById("val-ram").textContent = `${curr.ram_used_gb} / ${curr.ram_total_gb} GB`;
        const pzRamGb = curr.pz_ram_gb !== undefined ? curr.pz_ram_gb : (curr.ark_ram_gb || 0.0);
        const valPzRam = document.getElementById("val-pz-ram") || document.getElementById("val-ark-ram");
        if (valPzRam) valPzRam.textContent = `${pzRamGb} GB`;
        if (document.getElementById("val-disk")) document.getElementById("val-disk").textContent = `${curr.disk_used_gb} / ${curr.disk_total_gb} GB`;
        const valDiskPct = document.getElementById("val-disk-pct");
        if (valDiskPct && curr.disk_percent !== undefined) {
            valDiskPct.textContent = `${curr.disk_percent}%`;
        }
        const valRamPct = document.getElementById("val-ram-pct");
        if (valRamPct && curr.ram_percent !== undefined) {
            valRamPct.textContent = `${curr.ram_percent}%`;
        }

        // Actualizar Tarjeta de Supervivientes en Métricas
        const metricPlayers = document.getElementById("val-players-metric");
        if (metricPlayers) {
            const pOnline = curr.players_online !== undefined ? curr.players_online : 0;
            const pMax = curr.max_players || 20;
            metricPlayers.textContent = `${pOnline} / ${pMax}`;
        }

        // Actualizar Banner Superior
        const topStatus = document.getElementById("top-server-status");
        const statusLabel = (curr.status === "INSTALLING" && curr.install_progress && curr.install_progress.percent !== undefined)
            ? `INSTALLING (${Number(curr.install_progress.percent).toFixed(0)}%)`
            : curr.status;
        if (topStatus) {
            topStatus.textContent = statusLabel;
            topStatus.className = `overview-val status-text-inline ${curr.status.toLowerCase()}`;
        }
        const topUptime = document.getElementById("top-server-uptime");
        if (topUptime) topUptime.textContent = curr.uptime_formatted;
        const topCpu = document.getElementById("top-server-cpu");
        if (topCpu) topCpu.textContent = `${isOffline ? 0.0 : curr.cpu_percent} %`;
        const topPzMem = document.getElementById("top-server-pz-memory") || document.getElementById("top-server-ark-memory");
        if (topPzMem) topPzMem.textContent = `${pzRamGb} GB`;
        const topDisk = document.getElementById("top-server-disk");
        if (topDisk) topDisk.textContent = `${curr.disk_used_gb} / ${curr.disk_total_gb} GB`;
        const topPlayers = document.getElementById("top-server-players");
        if (topPlayers) {
            const pOnline = curr.players_online !== undefined ? curr.players_online : 0;
            const pMax = curr.max_players || 20;
            topPlayers.textContent = `${pOnline} / ${pMax}`;
        }

        // Header Status Pill
        const statusPill = document.getElementById("status-pill");
        if (statusPill) statusPill.className = `status-pill ${curr.status.toLowerCase()}`;
        const statusText = document.getElementById("status-text");
        if (statusText) statusText.textContent = curr.status;

        // Stat Boxes de Consola
        const cpuValToDisplay = isOffline ? 0.0 : curr.cpu_percent;
        const statCpuVal = document.getElementById("stat-cpu-val");
        if (statCpuVal) statCpuVal.textContent = `${cpuValToDisplay}%`;
        const statCpuBar = document.getElementById("stat-cpu-bar");
        if (statCpuBar) statCpuBar.style.width = `${Math.min(cpuValToDisplay, 100)}%`;
        const statCpuSub = document.getElementById("stat-cpu-subtext");
        if (statCpuSub) {
            statCpuSub.textContent = isOffline
                ? "Servidor inactivo (0.0%)"
                : `Carga Servidor PZ (Host: ${curr.host_cpu_percent || 0}%)`;
        }
        const valCpuSub = document.getElementById("val-cpu-subtext");
        if (valCpuSub) {
            valCpuSub.textContent = isOffline
                ? "Servidor inactivo (0.0%)"
                : `Carga Servidor PZ (Host: ${curr.host_cpu_percent || 0}%)`;
        }

        const statMemVal = document.getElementById("stat-mem-val");
        if (statMemVal) statMemVal.textContent = `${pzRamGb} GB`;
        const statMemBar = document.getElementById("stat-mem-bar");
        if (statMemBar) statMemBar.style.width = `${curr.ram_percent}%`;

        const statDiskVal = document.getElementById("stat-disk-val");
        if (statDiskVal) statDiskVal.textContent = `${curr.disk_used_gb} / ${curr.disk_total_gb} GB`;
        const statDiskBar = document.getElementById("stat-disk-bar");
        if (statDiskBar) statDiskBar.style.width = `${curr.disk_percent}%`;

        // Actualizar Gráfico
        if (metricsChart && data.history) {
            metricsChart.data.labels = data.history.map(h => h.timestamp);
            metricsChart.data.datasets[0].data = data.history.map(h => h.cpu_percent);
            metricsChart.data.datasets[1].data = data.history.map(h => (h.pz_ram_gb !== undefined ? h.pz_ram_gb : h.ark_ram_gb));
            metricsChart.update("none");
        }
    } catch (e) {}
}

function scheduleNextMetricsPoll() {
    clearTimeout(metricsPollTimer);
    // Page Visibility API: 2.5s activa, 10s en segundo plano o minimizada
    const delay = document.hidden ? 10000 : 2500;
    metricsPollTimer = setTimeout(async () => {
        await fetchMetricsOnce();
        scheduleNextMetricsPoll();
    }, delay);
}

function initMetricsPolling() {
    fetchMetricsOnce();
    scheduleNextMetricsPoll();

    // Reaccionar inmediatamente cuando la pestaña vuelve a ser visible
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            fetchMetricsOnce();
            scheduleNextMetricsPoll();
        }
    });
}

// --- Jugadores & Moderación (Dockraft Enhanced + Roles PZ) ---
let playersCache = { online: [], history: [], banned: [], max_players: 32 };
let activePlayerTab = "online";
let playerSearchQuery = "";

const AVATAR_GRADIENTS = [
    "linear-gradient(135deg, #4f46e5, #06b6d4)",
    "linear-gradient(135deg, #10b981, #059669)",
    "linear-gradient(135deg, #f59e0b, #d97706)",
    "linear-gradient(135deg, #ec4899, #8b5cf6)",
    "linear-gradient(135deg, #3b82f6, #1d4ed8)",
    "linear-gradient(135deg, #8b5cf6, #6366f1)"
];

const PZ_ROLES = [
    { value: "none", label: "Estándar" },
    { value: "observer", label: "Observer" },
    { value: "gm", label: "GM" },
    { value: "overseer", label: "Overseer" },
    { value: "moderator", label: "Moderador" },
    { value: "admin", label: "Admin" }
];

function getAvatarGradient(name) {
    let hash = 0;
    for (let i = 0; i < (name || "").length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const idx = Math.abs(hash) % AVATAR_GRADIENTS.length;
    return AVATAR_GRADIENTS[idx];
}

async function loadPlayers() {
    try {
        const res = await fetch("/api/players");
        const data = await window.readApiJson(res);
        if (!res.ok) return;

        playersCache = {
            online: data.online || [],
            history: data.history || [],
            banned: data.banned || [],
            max_players: Number(data.max_players || 32)
        };

        const statOnline = document.getElementById("players-online-stat");
        if (statOnline) {
            statOnline.textContent = `${playersCache.online.length} / ${playersCache.max_players}`;
        }
        const statHist = document.getElementById("players-history-stat");
        if (statHist) statHist.textContent = playersCache.history.length;

        const bannedCount = playersCache.banned.length || playersCache.history.filter(p => p.banned).length;
        const statBanned = document.getElementById("players-banned-stat");
        if (statBanned) statBanned.textContent = bannedCount;

        const countOnline = document.getElementById("count-tab-online");
        if (countOnline) countOnline.textContent = playersCache.online.length;
        const countHist = document.getElementById("count-tab-history");
        if (countHist) countHist.textContent = playersCache.history.length;

        renderPlayersList();
    } catch (e) {
        console.error("Error cargando jugadores:", e);
    }
}

async function refreshOnlinePlayers() {
    showToast("Consultando jugadores en consola (players)...", "info");
    try {
        await fetch("/api/players/refresh", { method: "POST" });
        setTimeout(() => loadPlayers(), 650);
    } catch (e) {
        showToast("No se pudo consultar la lista de jugadores.", "error");
    }
}

function switchPlayerTab(tab) {
    activePlayerTab = tab;
    document.querySelectorAll(".player-seg-btn").forEach(btn => btn.classList.remove("active"));
    const activeBtn = document.getElementById(`btn-tab-players-${tab}`);
    if (activeBtn) activeBtn.classList.add("active");
    renderPlayersList();
}

function filterPlayers(query) {
    playerSearchQuery = (query || "").toLowerCase().trim();
    renderPlayersList();
}

function renderPlayersList() {
    const tbody = document.getElementById("players-table-body");
    if (!tbody) return;

    const onlineNames = new Set(playersCache.online.map(p => (p.name || "").toLowerCase()));
    const onlineSteamIds = new Set(playersCache.online.map(p => p.steam_id).filter(Boolean));
    const bannedNames = new Set(playersCache.banned.map(b => (b.username || b.name || "").toLowerCase()));
    const bannedSteamIds = new Set(playersCache.banned.map(b => b.steam_id).filter(Boolean));

    let list = [];
    if (activePlayerTab === "online") {
        list = playersCache.online.map(p => ({
            name: p.name,
            steam_id: p.steam_id || "",
            access_level: p.access_level || "none",
            is_online: true,
            banned: false,
            last_seen: p.last_seen || "En juego ahora"
        }));
    } else {
        list = playersCache.history.map(p => {
            const lowName = (p.name || "").toLowerCase();
            const isOnline = onlineNames.has(lowName) || (p.steam_id && onlineSteamIds.has(p.steam_id));
            const isBanned = Boolean(p.banned) || bannedNames.has(lowName) || (p.steam_id && bannedSteamIds.has(p.steam_id));
            return {
                name: p.name,
                steam_id: p.steam_id || "",
                access_level: p.access_level || "none",
                is_online: isOnline,
                banned: isBanned,
                last_seen: p.last_seen || p.first_seen || "-"
            };
        });
    }

    if (playerSearchQuery) {
        list = list.filter(p =>
            (p.name || "").toLowerCase().includes(playerSearchQuery) ||
            (p.steam_id || "").toLowerCase().includes(playerSearchQuery) ||
            (p.access_level || "").toLowerCase().includes(playerSearchQuery)
        );
    }

    tbody.innerHTML = "";

    if (list.length === 0) {
        const emptyMsg = playerSearchQuery
            ? `No se encontraron supervivientes que coincidan con "${escapeHtml(playerSearchQuery)}".`
            : (activePlayerTab === "online"
                ? "No hay supervivientes conectados actualmente en este servidor."
                : "No hay historial registrado de supervivientes.");

        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; color: var(--text-dim); padding: 40px 20px;">
                    <div style="display: flex; flex-direction: column; align-items: center; gap: 8px;">
                        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#484f58" stroke-width="1.6"><circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>
                        <span style="font-size: 0.88rem; color: #8b949e;">${emptyMsg}</span>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    list.forEach(p => {
        const tr = document.createElement("tr");
        const initial = (p.name || "?").charAt(0).toUpperCase();
        const gradient = getAvatarGradient(p.name);
        const hasValidSteamId = /^\d{15,20}$/.test(String(p.steam_id || ""));

        let statusBadge = "";
        if (p.banned) {
            statusBadge = `<span class="status-pill offline" style="font-size: 0.72rem; padding: 2px 8px; border-color: #f85149; color: #ff7b72;"><span class="status-dot" style="background-color: #f85149; box-shadow: 0 0 6px rgba(248,81,73,0.6);"></span>Baneado</span>`;
        } else if (p.is_online) {
            statusBadge = `<span class="status-pill online" style="font-size: 0.72rem; padding: 2px 8px;"><span class="status-dot online"></span>En línea</span>`;
        } else {
            statusBadge = `<span class="status-pill offline" style="font-size: 0.72rem; padding: 2px 8px; color: #8b949e;"><span class="status-dot offline"></span>Desconectado</span>`;
        }

        const normRole = (!p.access_level || p.access_level === "user") ? "none" : p.access_level;
        const roleOpts = PZ_ROLES.map(r => `<option value="${r.value}" ${normRole === r.value ? "selected" : ""}>${r.label}</option>`).join("");

        tr.innerHTML = `
            <td>
                <div class="player-info-cell">
                    <div class="player-avatar-badge" style="background: ${gradient};">
                        ${escapeHtml(initial)}
                    </div>
                    <div>
                        <div class="player-name-text">
                            <span>${escapeHtml(p.name)}</span>
                            ${p.is_online ? '<span style="width: 6px; height: 6px; border-radius: 50%; background: #3fb950; display: inline-block;" title="Actualmente jugando"></span>' : ''}
                        </div>
                        ${hasValidSteamId ? `
                            <a href="https://steamcommunity.com/profiles/${escapeHtml(p.steam_id)}" target="_blank" rel="noopener noreferrer" class="player-steam-link" title="Ver perfil público en Steam">
                                <span>Perfil de Steam</span>
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                            </a>
                        ` : '<span style="font-size: 0.72rem; color: var(--text-dim);">Usuario PZ / Sin SteamID</span>'}
                    </div>
                </div>
            </td>
            <td>
                <div class="steam-id-pill ${hasValidSteamId ? '' : 'muted'}">
                    <span>${escapeHtml(p.steam_id || "Sin SteamID")}</span>
                    ${hasValidSteamId ? `
                        <button type="button" class="btn-copy-steam" onclick="copySteamId('${attrJsStr(p.steam_id)}')" title="Copiar SteamID al portapapeles">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                        </button>
                    ` : ''}
                </div>
            </td>
            <td>
                <select class="form-select player-role-select" onchange="changePlayerRole('${attrJsStr(p.name)}', this.value)" title="Rol en Project Zomboid (setaccesslevel)">
                    ${roleOpts}
                </select>
            </td>
            <td>
                <div style="font-size: 0.8rem; color: #8b949e; display: flex; align-items: center; gap: 5px; white-space: nowrap;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    <span>${escapeHtml(p.last_seen)}</span>
                </div>
            </td>
            <td>${statusBadge}</td>
            <td style="text-align: right;">
                <div style="display: inline-flex; gap: 6px; align-items: center; justify-content: flex-end; flex-wrap: nowrap;">
                    ${p.is_online ? `
                        <button class="btn btn-outline" style="padding: 4px 10px; font-size: 0.76rem; border-color: #a371f7; color: #d2a8ff;" onclick="openPlayerActionsModal('${attrJsStr(p.name)}')">
                            <span>Acciones</span>
                        </button>
                        <button class="btn btn-outline" style="padding: 4px 10px; font-size: 0.76rem; border-color: #58a6ff; color: #79c0ff;" onclick="messagePlayer('${attrJsStr(p.name)}', '${attrJsStr(p.steam_id)}')">
                            <span>Mensaje</span>
                        </button>
                        <button class="btn btn-danger" style="padding: 4px 10px; font-size: 0.76rem;" onclick="kickPlayer('${attrJsStr(p.name)}', '${attrJsStr(p.steam_id)}')">
                            <span>Expulsar</span>
                        </button>
                    ` : ''}
                    ${!p.banned ? `
                        <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 0.76rem;" onclick="banPlayer('${attrJsStr(p.name)}', '${attrJsStr(p.steam_id)}')">
                            <span>Banear</span>
                        </button>
                    ` : `
                        <button class="btn btn-success" style="padding: 4px 10px; font-size: 0.76rem;" onclick="unbanPlayer('${attrJsStr(p.name)}', '${attrJsStr(p.steam_id)}')">
                            <span>Desbanear</span>
                        </button>
                    `}
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function copySteamId(steamId) {
    if (!steamId) return;
    const copied = await copyTextToClipboard(steamId);
    if (copied) {
        showToast(`SteamID ${steamId} copiado al portapapeles.`, "success");
    } else {
        showToast(`SteamID: ${steamId}`, "info");
    }
}

async function changePlayerRole(name, accessLevel) {
    try {
        const res = await fetch("/api/players/role", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: name, access_level: accessLevel })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(`Rol '${accessLevel}' asignado a ${name}.`, "success");
            loadPlayers();
        } else {
            showToast(data.error || "No se pudo cambiar el rol.", "error");
        }
    } catch (e) {
        showToast("Error asignando rol al jugador.", "error");
    }
}

function openAddPlayerModal() {
    const u = document.getElementById("add-player-username");
    const p = document.getElementById("add-player-password");
    const r = document.getElementById("add-player-role");
    if (u) u.value = "";
    if (p) p.value = "";
    if (r) r.value = "none";
    document.getElementById("modal-add-player")?.classList.add("open");
    setTimeout(() => u?.focus(), 60);
}

async function submitAddPlayer() {
    const username = document.getElementById("add-player-username")?.value.trim() || "";
    const password = document.getElementById("add-player-password")?.value || "";
    const access_level = document.getElementById("add-player-role")?.value || "none";
    if (!username || !password) {
        showToast("Usuario y contraseña requeridos.", "error");
        return;
    }
    try {
        const res = await fetch("/api/players/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password, access_level })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            document.getElementById("modal-add-player")?.classList.remove("open");
            showToast(`Usuario PZ '${username}' creado correctamente.`, "success");
            loadPlayers();
        } else {
            showToast(data.error || "Error creando usuario PZ.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al crear usuario.", "error");
    }
}

async function messagePlayer(name, steamId = "") {
    const msg = await App.prompt({
        title: `Mensaje a ${name}`,
        message: `Escribe el mensaje privado/aviso in-game para "${name}":`,
        placeholder: "ej: Hola, escribe tu mensaje para este jugador...",
        confirmText: "Enviar Mensaje"
    });
    if (!msg || !msg.trim()) return;

    try {
        const res = await fetch("/api/players/message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: name, steam_id: steamId || null, message: msg.trim() })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(`Mensaje enviado a ${name}.`, "success");
        } else {
            showToast(data.error || "Error enviando mensaje.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al enviar mensaje.", "error");
    }
}

async function kickPlayer(name, steamId = "") {
    const ok = await App.confirm({
        title: "Expulsar Superviviente",
        message: `¿Expulsar del servidor al superviviente "${name}"?`,
        confirmText: "Expulsar",
        danger: true
    });
    if (!ok) return;
    try {
        const res = await fetch("/api/players/kick", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: name, steam_id: steamId || null })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(`Superviviente ${name} expulsado.`, "info");
            loadPlayers();
        } else {
            showToast(data.error || "Error al expulsar superviviente.", "error");
        }
    } catch (e) {
        showToast("Error al expulsar superviviente.", "error");
    }
}

async function banPlayer(name, steamId = "") {
    const ok = await App.confirm({
        title: "Banear Superviviente",
        message: `¿Banear permanentemente del servidor al superviviente "${name}"?`,
        confirmText: "Banear",
        danger: true
    });
    if (!ok) return;
    try {
        const res = await fetch("/api/players/ban", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: name, steam_id: steamId || null })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(`Superviviente ${name} baneado.`, "error");
            loadPlayers();
        } else {
            showToast(data.error || "Error al banear superviviente.", "error");
        }
    } catch (e) {
        showToast("Error al banear superviviente.", "error");
    }
}

async function unbanPlayer(name, steamId = "") {
    const ok = await App.confirm({
        title: "Desbanear Superviviente",
        message: `¿Remover la sanción y permitir que "${name}" vuelva a ingresar al servidor?`,
        confirmText: "Desbanear"
    });
    if (!ok) return;
    try {
        const res = await fetch("/api/players/unban", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: name, steam_id: steamId || null })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(`Sanción removida para ${name}.`, "success");
            loadPlayers();
        } else {
            showToast(data.error || "Error al desbanear superviviente.", "error");
        }
    } catch (e) {
        showToast("Error al desbanear superviviente.", "error");
    }
}

function openPlayerActionsModal(username) {
    const modal = document.getElementById("modal-player-actions");
    const hidden = document.getElementById("pa-target-username");
    const title = document.getElementById("pa-target-title");
    if (hidden) hidden.value = username || "";
    if (title) title.textContent = `Acciones In-Game: ${username}`;
    if (modal) modal.classList.add("open");
}

async function submitPlayerAction(action) {
    const username = document.getElementById("pa-target-username")?.value.trim() || "";
    let arg1 = "";
    let arg2 = "";
    if (action === "additem") {
        arg1 = document.getElementById("pa-item-code")?.value.trim() || "";
        arg2 = document.getElementById("pa-item-qty")?.value || "1";
    } else if (action === "addvehicle") {
        arg1 = document.getElementById("pa-vehicle-code")?.value.trim() || "Base.CarNormal";
    } else if (action === "addxp") {
        arg1 = document.getElementById("pa-xp-perk")?.value.trim() || "";
        arg2 = document.getElementById("pa-xp-amount")?.value || "500";
    } else if (action === "teleport") {
        arg1 = document.getElementById("pa-teleport-target")?.value.trim() || "";
    }

    try {
        const res = await fetch("/api/players/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, action, arg1, arg2 })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(`Comando enviado: ${data.command || action}`, "success");
        } else {
            showToast(data.error || "No se pudo ejecutar la acción.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al ejecutar acción.", "error");
    }
}

// --- Configuraciones Integrales de Project Zomboid (Server.ini / SandboxVars.lua / Motor) ---
let currentRawFileType = 'ini';
let cachedSettingsData = null;

function switchSettingsTab(paneId, btn) {
    document.querySelectorAll('.subnav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.settings-subpane').forEach(p => {
        p.style.display = 'none';
        p.classList.remove('active');
    });

    if (btn) btn.classList.add('active');
    const target = document.getElementById(`cfg-pane-${paneId}`);
    if (target) {
        target.style.display = 'block';
        target.classList.add('active');
    }

    if (paneId === 'raw') {
        renderRawFileInEditor();
    }
}

async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const s = await res.json();
        cachedSettingsData = s;

        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (val === undefined || val === null) return;
            el.value = String(val);
        };

        // 1. Opciones de Server.ini
        if (s.server) {
            for (const [k, v] of Object.entries(s.server)) {
                setVal(`cfg-${k}`, v);
            }
        }

        // 2. Opciones de SandboxVars.lua
        if (s.sandbox) {
            for (const [k, v] of Object.entries(s.sandbox)) {
                setVal(`cfg-sandbox-${k}`, v);
            }
        }

        // 3. Opciones de Infraestructura y Motor (Panel)
        if (s.panel) {
            for (const [k, v] of Object.entries(s.panel)) {
                setVal(`cfg-panel-${k}`, v);
            }
            if (s.panel.use_steam !== undefined) {
                applySteamModeUI(s.panel.use_steam);
            }
        }

        // Perfiles detectados (<SERVER_NAME>.ini)
        const dl = document.getElementById("cfg-profiles-list");
        if (dl && Array.isArray(s.profiles)) {
            dl.innerHTML = s.profiles.map(p => `<option value="${escapeHtml(p)}"></option>`).join("");
        }

        renderRawFileInEditor();
    } catch (e) {
        console.error("Error al cargar configuraciones:", e);
    }
}

function renderRawFileInEditor() {
    const textarea = document.getElementById("raw-file-content");
    if (!textarea || !cachedSettingsData) return;
    if (currentRawFileType === 'sandbox') {
        textarea.value = cachedSettingsData.raw_sandbox || "";
    } else if (currentRawFileType === 'spawnregions') {
        textarea.value = cachedSettingsData.raw_spawnregions || "";
    } else {
        textarea.value = cachedSettingsData.raw_ini || "";
    }
}

function toggleRawFileView(type) {
    currentRawFileType = type;
    const mapBtns = {
        ini: document.getElementById("btn-raw-mode-ini"),
        sandbox: document.getElementById("btn-raw-mode-sandbox"),
        spawnregions: document.getElementById("btn-raw-mode-spawnregions"),
    };
    for (const [key, btn] of Object.entries(mapBtns)) {
        if (!btn) continue;
        if (key === type) {
            btn.style.background = 'rgba(56, 189, 248, 0.15)';
            btn.style.borderColor = '#38bdf8';
            btn.style.color = '#38bdf8';
        } else {
            btn.style.background = 'transparent';
            btn.style.borderColor = 'var(--border-color)';
            btn.style.color = 'var(--text-color)';
        }
    }
    renderRawFileInEditor();
}

async function saveRawFileCurrent() {
    const textarea = document.getElementById("raw-file-content");
    if (!textarea) return;
    const labelMap = { sandbox: 'SandboxVars.lua', spawnregions: 'spawnregions.lua', ini: '.ini' };
    const lbl = labelMap[currentRawFileType] || '.ini';
    showToast(`Guardando archivo ${lbl}...`, "info");
    try {
        const res = await fetch("/api/settings/raw", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: currentRawFileType, content: textarea.value })
        });
        const r = await window.readApiJson(res);
        if (r.success) {
            showToast(`Archivo ${lbl} guardado con éxito.`, "success");
            loadSettings();
        } else {
            showToast("Error al guardar archivo.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al guardar archivo raw.", "error");
    }
}

async function saveAllSettings(e) {
    if (e) e.preventDefault();

    const server = {};
    const sandbox = {};
    const panel = {};

    document.querySelectorAll("[id^='cfg-']").forEach(el => {
        if (el.disabled) return;
        const id = el.id;
        const val = el.value;

        if (id.startsWith("cfg-sandbox-")) {
            const key = id.replace("cfg-sandbox-", "");
            if (val === "true") sandbox[key] = true;
            else if (val === "false") sandbox[key] = false;
            else if (!isNaN(val) && val.trim() !== "") {
                sandbox[key] = val.includes(".") ? parseFloat(val) : parseInt(val, 10);
            } else {
                sandbox[key] = val;
            }
        } else if (id.startsWith("cfg-panel-")) {
            const key = id.replace("cfg-panel-", "");
            panel[key] = val;
        } else {
            const key = id.replace("cfg-", "");
            server[key] = val;
        }
    });

    showToast("Guardando configuración del servidor y sandbox...", "info");
    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ server, sandbox, panel })
        });
        const r = await res.json();
        if (r.success) {
            if (panel.use_steam !== undefined) {
                applySteamModeUI(panel.use_steam !== "false");
            }
            const topPortEl = document.getElementById("top-server-port");
            const topPortLabel = document.getElementById("top-server-port-label");
            if (topPortEl) {
                const pub = String(panel.public_address || "").trim();
                const srvPort = server.DefaultPort || (cachedSettingsData && cachedSettingsData.panel && cachedSettingsData.panel.server_port) || 16261;
                topPortEl.textContent = pub || `${srvPort} (UDP)`;
                if (topPortLabel) topPortLabel.textContent = pub ? "Dirección Pública:" : "Puerto de Juego:";
            }
            showToast("Ajustes guardados con éxito en Server.ini y SandboxVars.lua.", "success");
            loadSettings();
        } else {
            showToast("Error al guardar ajustes.", "error");
        }
    } catch (err) {
        showToast("Error de conexión al guardar configuraciones.", "error");
    }
}

async function reloadOptionsHot() {
    showToast("Enviando 'reloadoptions' a la consola del servidor...", "info");
    try {
        const res = await fetch("/api/server/reloadoptions", { method: "POST" });
        const r = await res.json();
        if (r.success) {
            showToast("¡Opciones del .ini recargadas en caliente sin reiniciar!", "success");
        } else {
            showToast("No se pudo recargar en caliente.", "error");
        }
    } catch (e) {
        showToast("Error al solicitar recarga en caliente.", "error");
    }
}

function applyPreset(preset) {
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = String(val);
    };

    if (preset === 'apocalypse') {
        set("cfg-sandbox-zombie_speed", "2");
        set("cfg-sandbox-zombie_transmission", "1");
        set("cfg-sandbox-zombie_strength", "2");
        set("cfg-sandbox-zombie_toughness", "2");
        set("cfg-sandbox-zombie_cognition", "3");
        set("cfg-sandbox-pop_multiplier", "1.0");
        set("cfg-sandbox-loot_food", "2");
        set("cfg-sandbox-loot_weapon", "2");
        set("cfg-sandbox-loot_ammo", "2");
        set("cfg-sandbox-water_shut", "2");
        set("cfg-sandbox-elec_shut", "2");
        set("cfg-sandbox-starter_kit", "false");
        set("cfg-sandbox-multi_hit_zombies", "false");
        set("cfg-sandbox-rear_vulnerability", "3");
        set("cfg-sandbox-zombie_decomp", "1");
        set("cfg-sandbox-darkness", "2");
        showToast("Preset 'Apocalipsis' aplicado a los campos del formulario.", "info");
    } else if (preset === 'survivor') {
        set("cfg-sandbox-zombie_speed", "2");
        set("cfg-sandbox-zombie_transmission", "1");
        set("cfg-sandbox-zombie_strength", "2");
        set("cfg-sandbox-zombie_toughness", "2");
        set("cfg-sandbox-pop_multiplier", "1.0");
        set("cfg-sandbox-loot_food", "3");
        set("cfg-sandbox-loot_weapon", "3");
        set("cfg-sandbox-loot_ammo", "3");
        set("cfg-sandbox-starter_kit", "false");
        set("cfg-sandbox-multi_hit_zombies", "true");
        set("cfg-sandbox-rear_vulnerability", "2");
        set("cfg-sandbox-zombie_decomp", "1");
        set("cfg-sandbox-darkness", "3");
        showToast("Preset 'Superviviente' aplicado a los campos del formulario.", "info");
    } else if (preset === 'sprinters') {
        set("cfg-sandbox-zombie_speed", "1");
        set("cfg-sandbox-zombie_transmission", "1");
        set("cfg-sandbox-zombie_strength", "1");
        set("cfg-sandbox-zombie_toughness", "1");
        set("cfg-sandbox-zombie_cognition", "1");
        set("cfg-sandbox-zombie_sight", "1");
        set("cfg-sandbox-zombie_hearing", "1");
        set("cfg-sandbox-multi_hit_zombies", "false");
        set("cfg-sandbox-rear_vulnerability", "3");
        showToast("Preset 'Corredores Letales' (Sprinters) aplicado.", "warning");
    } else if (preset === 'six_months') {
        set("cfg-sandbox-zombie_speed", "2");
        set("cfg-sandbox-zombie_transmission", "1");
        set("cfg-sandbox-zombie_strength", "2");
        set("cfg-sandbox-zombie_toughness", "2");
        set("cfg-sandbox-pop_multiplier", "2.0");
        set("cfg-sandbox-pop_start_multiplier", "1.5");
        set("cfg-sandbox-loot_food", "1");
        set("cfg-sandbox-loot_canned_food", "1");
        set("cfg-sandbox-loot_weapon", "1");
        set("cfg-sandbox-loot_ammo", "1");
        set("cfg-sandbox-water_shut", "1");
        set("cfg-sandbox-elec_shut", "1");
        set("cfg-sandbox-erosion_speed", "2");
        set("cfg-sandbox-starter_kit", "false");
        set("cfg-sandbox-multi_hit_zombies", "false");
        showToast("Preset '6 Meses Después' aplicado. Pulsa Guardar Ajustes para aplicarlo.", "warning");
    } else if (preset === 'builder') {
        set("cfg-sandbox-zombie_speed", "3");
        set("cfg-sandbox-zombie_transmission", "3");
        set("cfg-sandbox-zombie_strength", "3");
        set("cfg-sandbox-zombie_toughness", "3");
        set("cfg-sandbox-pop_multiplier", "0.5");
        set("cfg-sandbox-loot_food", "4");
        set("cfg-sandbox-loot_weapon", "4");
        set("cfg-sandbox-loot_ammo", "4");
        set("cfg-sandbox-water_shut", "8");
        set("cfg-sandbox-elec_shut", "8");
        set("cfg-sandbox-starter_kit", "true");
        set("cfg-sandbox-free_trait_points", "8");
        set("cfg-sandbox-multi_hit_zombies", "true");
        set("cfg-sandbox-injury_severity", "1");
        set("cfg-sandbox-farming", "2");
        set("cfg-sandbox-plant_abundance", "4");
        showToast("Preset 'Constructor / Fácil' aplicado.", "success");
    }
}

async function wipeWorldNow() {
    const ok = await App.confirm({
        title: "Wipe de Mundo (Reiniciar Mapa al Día 1)",
        message: "Se detendrá el servidor si está activo, se creará una copia de seguridad automática solo del mundo actual y se borrará Saves/Multiplayer/<SERVER_NAME>. Tus ajustes .ini, Sandbox, mods y cuentas se conservarán intactos. ¿Continuar?",
        confirmText: "Confirmar Wipe de Mundo",
        danger: true
    });
    if (!ok) return;

    showToast("Creando respaldo de seguridad y limpiando mundo...", "info");
    try {
        const res = await fetch("/api/server/wipe-world", { method: "POST" });
        const data = await window.readApiJson(res);
        if (res.ok && data.success) {
            showToast(data.message || "Wipe de mundo completado.", "success");
            if (typeof Backups !== "undefined") Backups.loadBackups();
        } else {
            showToast(data.detail || data.error || "No se pudo completar el wipe.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al ejecutar wipe de mundo.", "error");
    }
}


async function runDiagnostics() {
    const modal = document.getElementById("modal-diagnostics");
    const body = document.getElementById("diagnostics-modal-body");
    if (body) body.innerHTML = "<p style='color:var(--text-dim);'>Analizando consola, JVM, Workshop y configuración...</p>";
    if (modal) modal.classList.add("open");

    try {
        const res = await fetch("/api/diagnostics");
        const data = await window.readApiJson(res);
        if (!res.ok) {
            if (body) body.innerHTML = `<p style="color:#ff7b72;">${escapeHtml(data.detail || "No se pudo ejecutar diagnóstico.")}</p>`;
            return;
        }
        const issues = Array.isArray(data.issues)
            ? data.issues
            : (data.has_issue ? [data] : []);

        if (!issues.length) {
            if (body) {
                body.innerHTML = `
                    <div style="padding:14px;background:rgba(63,185,80,0.1);border:1px solid rgba(63,185,80,0.3);border-radius:8px;color:#7ee2b4;">
                        <strong>${escapeHtml(data.title || "Todo en orden")}</strong><br>
                        <span style="font-size:0.84rem;color:var(--text-color);">${escapeHtml(data.recommendation || data.summary || "No se detectaron errores conocidos en los registros recientes.")}</span>
                    </div>
                `;
            }
            return;
        }
        if (body) {
            body.innerHTML = issues.map(it => {
                const sevColor = it.severity === "critical" || it.severity === "error" ? "#ff7b72" : "#f2cc60";
                const excerptHtml = it.excerpt
                    ? `<pre style="margin:8px 0 0 0;padding:8px;background:var(--bg-main);border:1px solid var(--border-color);border-radius:4px;font-family:var(--font-mono);font-size:0.74rem;overflow-x:auto;color:#e6edf3;">${escapeHtml(it.excerpt)}</pre>`
                    : "";
                return `
                    <div style="margin-bottom:12px;padding:12px;background:var(--bg-subtle);border:1px solid var(--border-color);border-left:3px solid ${sevColor};border-radius:6px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px;">
                            <span style="font-weight:700;color:${sevColor};">${escapeHtml(it.title || it.code || "Incidencia")}</span>
                            ${it.source ? `<span class="badge" style="font-size:0.7rem;">${escapeHtml(it.source)}</span>` : ""}
                        </div>
                        <div style="font-size:0.82rem;color:var(--text-color);margin-bottom:6px;"><strong>Causa:</strong> ${escapeHtml(it.cause || it.description || "")}</div>
                        <div style="font-size:0.82rem;color:#7ee2b4;"><strong>Solución recomendada:</strong> ${escapeHtml(it.recommendation || it.solution || "")}</div>
                        ${excerptHtml}
                    </div>
                `;
            }).join("");
        }
    } catch (e) {
        if (body) body.innerHTML = `<p style="color:#ff7b72;">Error al ejecutar diagnóstico: ${escapeHtml(e.message)}</p>`;
    }
}

// --- Sistema de Diálogos Modales y Notificaciones (Dockraft Style) ---
const App = {
  activeTab: 'console',
  escapeHtml,
  attrJsStr,
  showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.style.cssText = 'position:fixed; bottom:20px; right:20px; z-index:9999; display:flex; flex-direction:column; gap:8px;';
      document.body.appendChild(container);
    }
    while (container.children.length >= 4) {
      container.removeChild(container.firstChild);
    }
    const typeStyles = {
      success: { bg: '#238636', border: '#2ea043' },
      danger:  { bg: '#da3633', border: '#f85149' },
      error:   { bg: '#da3633', border: '#f85149' },
      warning: { bg: '#9e6a03', border: '#d29922' },
      info:    { bg: '#1f6feb', border: '#388bfd' },
    };
    const style = typeStyles[type] || typeStyles.info;
    const toast = document.createElement('div');
    toast.style.cssText = `
      background: ${style.bg};
      border: 1px solid ${style.border};
      color: white;
      padding: 10px 16px;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 500;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
      animation: fadeIn 0.15s ease-out;
      max-width: 340px;
      word-break: break-word;
    `;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.25s ease';
      setTimeout(() => toast.remove(), 250);
    }, 3500);
  },

  ensureConfirmModal() {
    let modal = document.getElementById('modal-app-confirm');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.className = 'modal-backdrop modal-dialog-backdrop';
    modal.id = 'modal-app-confirm';
    modal.style.zIndex = '2200';
    modal.innerHTML = `
      <div class="modal-box modal-dialog-box" style="max-width: 480px;">
        <div class="modal-header" style="padding: 16px 20px; border-bottom: 1px solid #30363d;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <div id="modal-confirm-icon" style="width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"></div>
            <h3 id="modal-confirm-title-text" style="font-size: 1.05rem; font-weight: 600; color: #f0f6fc; margin: 0;">Confirmación</h3>
          </div>
          <button class="action-icon-btn" id="modal-confirm-btn-close" type="button" aria-label="Cerrar">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body" style="padding: 20px;">
          <div id="modal-confirm-message" style="font-size: 0.92rem; line-height: 1.6; color: #cbd5e1; white-space: pre-line; word-break: break-word;"></div>
        </div>
        <div class="modal-footer" style="padding: 14px 20px; border-top: 1px solid #30363d; display: flex; justify-content: flex-end; gap: 10px;">
          <button type="button" class="btn btn-outline" id="modal-confirm-btn-cancel">Cancelar</button>
          <button type="button" class="btn btn-danger" id="modal-confirm-btn-ok">Confirmar</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    return modal;
  },

  ensurePromptModal() {
    let modal = document.getElementById('modal-app-prompt');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.className = 'modal-backdrop modal-dialog-backdrop';
    modal.id = 'modal-app-prompt';
    modal.style.zIndex = '2200';
    modal.innerHTML = `
      <div class="modal-box modal-dialog-box" style="max-width: 480px;">
        <div class="modal-header" style="padding: 16px 20px; border-bottom: 1px solid #30363d;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <div id="modal-prompt-icon" style="width: 36px; height: 36px; border-radius: 8px; background: rgba(56, 139, 253, 0.15); border: 1px solid rgba(56, 139, 253, 0.3); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#58a6ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </div>
            <h3 id="modal-prompt-title-text" style="font-size: 1.05rem; font-weight: 600; color: #f0f6fc; margin: 0;">Entrada Requerida</h3>
          </div>
          <button class="action-icon-btn" id="modal-prompt-btn-close" type="button" aria-label="Cerrar">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body" style="padding: 20px;">
          <div id="modal-prompt-message" style="font-size: 0.92rem; line-height: 1.5; color: #cbd5e1; margin-bottom: 14px; white-space: pre-line; word-break: break-word;"></div>
          <div class="form-group" style="margin-bottom: 0;">
            <input type="text" class="form-input" id="modal-prompt-input" autocomplete="off" spellcheck="false" style="font-size: 0.95rem; padding: 9px 12px;">
          </div>
        </div>
        <div class="modal-footer" style="padding: 14px 20px; border-top: 1px solid #30363d; display: flex; justify-content: flex-end; gap: 10px;">
          <button type="button" class="btn btn-outline" id="modal-prompt-btn-cancel">Cancelar</button>
          <button type="button" class="btn btn-primary" id="modal-prompt-btn-ok">Aceptar</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    return modal;
  },

  confirm(options, messageArg, dangerArg) {
    return new Promise((resolve) => {
      const modal = this.ensureConfirmModal();
      const opts = typeof options === 'string'
        ? (messageArg !== undefined ? { title: options, message: messageArg, danger: Boolean(dangerArg) } : { message: options })
        : (options || {});
      const isDanger = Boolean(opts.danger || opts.type === 'danger');
      const isWarning = Boolean(opts.warning || opts.type === 'warning');

      const titleEl = document.getElementById('modal-confirm-title-text');
      const iconEl = document.getElementById('modal-confirm-icon');
      const msgEl = document.getElementById('modal-confirm-message');
      const btnOk = document.getElementById('modal-confirm-btn-ok');
      const btnCancel = document.getElementById('modal-confirm-btn-cancel');
      const btnClose = document.getElementById('modal-confirm-btn-close');

      if (titleEl) titleEl.textContent = opts.title || (isDanger ? 'Confirmación requerida' : 'Confirmar Acción');
      if (msgEl) msgEl.textContent = opts.message || '¿Estás seguro de continuar con esta acción?';

      if (btnOk) {
        btnOk.textContent = opts.confirmText || (isDanger ? 'Eliminar' : 'Confirmar');
        btnOk.className = isDanger ? 'btn btn-danger' : (isWarning ? 'btn btn-warning' : 'btn btn-primary');
      }
      if (btnCancel) {
        btnCancel.textContent = opts.cancelText || 'Cancelar';
      }

      if (iconEl) {
        if (isDanger) {
          iconEl.style.background = 'rgba(248, 81, 73, 0.15)';
          iconEl.style.border = '1px solid rgba(248, 81, 73, 0.3)';
          iconEl.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f85149" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
        } else if (isWarning) {
          iconEl.style.background = 'rgba(210, 153, 34, 0.15)';
          iconEl.style.border = '1px solid rgba(210, 153, 34, 0.3)';
          iconEl.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d29922" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
        } else {
          iconEl.style.background = 'rgba(56, 139, 253, 0.15)';
          iconEl.style.border = '1px solid rgba(56, 139, 253, 0.3)';
          iconEl.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#58a6ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
        }
      }

      let resolved = false;
      const finish = (result) => {
        if (resolved) return;
        resolved = true;
        modal.classList.remove('open');
        window.removeEventListener('keydown', onKeyDown);
        resolve(result);
      };

      const onKeyDown = (e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          finish(false);
        } else if (e.key === 'Enter') {
          if (document.activeElement === btnCancel) {
            e.preventDefault();
            finish(false);
          } else {
            e.preventDefault();
            finish(true);
          }
        }
      };

      if (btnOk) btnOk.onclick = () => finish(true);
      if (btnCancel) btnCancel.onclick = () => finish(false);
      if (btnClose) btnClose.onclick = () => finish(false);
      modal.onclick = (e) => {
        if (e.target === modal) finish(false);
      };

      window.addEventListener('keydown', onKeyDown);
      modal.classList.add('open');

      if (isDanger && btnCancel) {
        btnCancel.focus();
      } else if (btnOk) {
        btnOk.focus();
      }
    });
  },

  prompt(options, messageArg, defaultArg) {
    return new Promise((resolve) => {
      const modal = this.ensurePromptModal();
      const opts = typeof options === 'string'
        ? (messageArg !== undefined ? { title: options, message: messageArg, defaultValue: defaultArg ?? '' } : { message: options })
        : (options || {});
      const titleEl = document.getElementById('modal-prompt-title-text');
      const msgEl = document.getElementById('modal-prompt-message');
      const inputEl = document.getElementById('modal-prompt-input');
      const btnOk = document.getElementById('modal-prompt-btn-ok');
      const btnCancel = document.getElementById('modal-prompt-btn-cancel');
      const btnClose = document.getElementById('modal-prompt-btn-close');

      if (titleEl) titleEl.textContent = opts.title || 'Entrada Requerida';
      if (msgEl) msgEl.textContent = opts.message || '';
      if (inputEl) {
        inputEl.placeholder = opts.placeholder || '';
        inputEl.value = opts.defaultValue || '';
      }
      if (btnOk) btnOk.textContent = opts.confirmText || 'Aceptar';
      if (btnCancel) btnCancel.textContent = opts.cancelText || 'Cancelar';

      let resolved = false;
      const finish = (result) => {
        if (resolved) return;
        resolved = true;
        modal.classList.remove('open');
        window.removeEventListener('keydown', onKeyDown);
        resolve(result);
      };

      const onKeyDown = (e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          finish(null);
        } else if (e.key === 'Enter') {
          e.preventDefault();
          finish(inputEl ? inputEl.value : '');
        }
      };

      if (btnOk) btnOk.onclick = () => finish(inputEl ? inputEl.value : '');
      if (btnCancel) btnCancel.onclick = () => finish(null);
      if (btnClose) btnClose.onclick = () => finish(null);
      modal.onclick = (e) => {
        if (e.target === modal) finish(null);
      };

      window.addEventListener('keydown', onKeyDown);
      modal.classList.add('open');

      if (inputEl) {
        setTimeout(() => {
          inputEl.focus();
          inputEl.select();
        }, 50);
      }
    });
  }
};

window.App = App;
function showToast(message, type = "info") {
  App.showToast(message, type);
}

// --- Asistente de Configuración Inicial & Descarga ---
let installerPollTimer = null;

function pollInstallerProgress() {
    clearTimeout(installerPollTimer);
    const card = document.getElementById("installer-progress-card");
    const bar = document.getElementById("installer-progress-bar");
    const pctEl = document.getElementById("installer-progress-pct");
    const stepEl = document.getElementById("installer-progress-step");
    const logEl = document.getElementById("installer-progress-log");
    if (card) card.style.display = "block";

    const tick = async () => {
        try {
            const res = await fetch("/api/status");
            const st = await window.readApiJson(res);
            const prog = st.install_progress || {};
            const pct = Number(prog.percent || 0);
            if (bar) bar.style.width = `${Math.max(2, Math.min(100, pct))}%`;
            if (pctEl) pctEl.textContent = `${pct.toFixed(0)}%`;
            if (stepEl && prog.step) stepEl.textContent = prog.step;
            if (logEl && prog.last_line) logEl.textContent = prog.last_line;

            const topStatus = document.getElementById("top-server-status");
            if (topStatus && st.status === "INSTALLING") {
                topStatus.textContent = `INSTALLING (${pct.toFixed(0)}%)`;
                topStatus.className = "overview-val status-text-inline installing";
            }

            if (st.status === "INSTALLING" || prog.running) {
                installerPollTimer = setTimeout(tick, 1500);
            } else if (st.status === "RUNNING" || st.status === "STARTING") {
                showToast("¡Servidor instalado e iniciándose!", "success");
                updateControlButtons(st.status);
                setTimeout(() => {
                    updateInstallerTabVisibility(st.is_installed, st.is_setup_done);
                    switchTab("console");
                }, 900);
            } else if (st.is_installed && st.is_setup_done) {
                showToast("Descarga de binarios finalizada.", "success");
                updateInstallerTabVisibility(true, true);
            }
        } catch (e) {
            installerPollTimer = setTimeout(tick, 2000);
        }
    };
    tick();
}

async function startServerInstallation(e) {
    if (e) e.preventDefault();
    const ok = await App.confirm({
        title: "Configuración Inicial del Servidor Project Zomboid",
        message: "¿Deseas guardar esta configuración inicial y arrancar el servidor dedicado de PZ?",
        confirmText: "Guardar e Iniciar"
    });
    if (!ok) return;

    const useSteam = document.getElementById("wizard-steam") ? document.getElementById("wizard-steam").value === "true" : true;
    const payload = {
        use_steam: useSteam,
        server_name: document.getElementById("wizard-session-name") ? document.getElementById("wizard-session-name").value.trim() : "servertest",
        server_password: document.getElementById("wizard-server-pass") ? document.getElementById("wizard-server-pass").value : "",
        admin_password: document.getElementById("wizard-admin-pass") ? document.getElementById("wizard-admin-pass").value : "adminpass",
        max_players: document.getElementById("wizard-max-players") ? parseInt(document.getElementById("wizard-max-players").value, 10) || 16 : 16,
        pvp: document.getElementById("wizard-mode") ? document.getElementById("wizard-mode").value === "pvp" : false,
        memory_min: document.getElementById("wizard-mem-min") ? document.getElementById("wizard-mem-min").value : "4g",
        memory_max: document.getElementById("wizard-mem-max") ? document.getElementById("wizard-mem-max").value : "6g",
        branch: document.getElementById("wizard-branch") ? document.getElementById("wizard-branch").value : "",
        mod_ids: useSteam && document.getElementById("wizard-mods") ? document.getElementById("wizard-mods").value : ""
    };

    showToast("Guardando configuración inicial...", "info");
    try {
        const res = await fetch("/api/server/install", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            applySteamModeUI(useSteam);
            showToast(data.message || "Configuración completada.", "success");
            const instPane = document.getElementById("tab-installer");
            if (instPane && !data.installing) {
                instPane.dataset.needsSetup = "false";
            }
            if (data.installing) {
                pollInstallerProgress();
            } else {
                updateInstallerTabVisibility(true, true);
                fetchMetricsOnce();
                setTimeout(() => switchTab("console"), 900);
            }
        } else {
            showToast(data.error || "Error al iniciar la instalación.", "error");
        }
    } catch (err) {
        showToast("Error de conexión al iniciar instalación.", "error");
    }
}

async function updateServerBinaries() {
    const ok = await App.confirm({
        title: "Actualizar / Validar Binarios (AppID 380870)",
        message: "Se ejecutará DepotDownloader/SteamCMD para validar o actualizar los archivos del servidor PZ. El servidor debe estar detenido. ¿Continuar?",
        confirmText: "Actualizar Binarios",
        warning: true
    });
    if (!ok) return;

    try {
        const res = await fetch("/api/server/update", { method: "POST" });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(data.message || "Actualización iniciada.", "success");
            pollInstallerProgress();
        } else {
            showToast(data.error || data.detail || "No se pudo actualizar binarios.", "error");
        }
    } catch (e) {
        showToast("Error al solicitar actualización de binarios.", "error");
    }
}

// --- Gestor de Mods PZ ---
let activeModsState = {
    workshop_items: [],
    mod_ids: [],
    map_folders: ["Muldraugh, KY"],
    catalog: [],
    standalone_mods: [],
    local_mods: []
};

function _extractWorkshopId(raw) {
    const val = String(raw || "").trim();
    if (!val) return "";
    if (/^\d+$/.test(val)) return val;
    const match = val.match(/[?&]id=(\d+)/);
    return match ? match[1] : "";
}

async function loadMods() {
    try {
        const res = await fetch("/api/mods");
        const data = await window.readApiJson(res);
        if (!res.ok) return;

        if (data.steam_mode !== undefined) {
            applySteamModeUI(data.steam_mode);
            if (!data.steam_mode) return;
        }

        activeModsState = {
            workshop_items: data.workshop_items || data.mods || [],
            mod_ids: data.mod_ids || [],
            map_folders: data.map_folders || ["Muldraugh, KY"],
            catalog: data.catalog || [],
            standalone_mods: data.standalone_mods || [],
            local_mods: data.local_mods || []
        };

        const elWCount = document.getElementById("mods-count-val");
        if (elWCount) elWCount.textContent = activeModsState.workshop_items.length;

        const elMCount = document.getElementById("mods-ids-count-val");
        if (elMCount) elMCount.textContent = activeModsState.mod_ids.length;

        const elMapsVal = document.getElementById("mods-maps-count-val");
        if (elMapsVal) elMapsVal.textContent = data.map_raw || "Muldraugh, KY";

        const directW = document.getElementById("mods-direct-workshop");
        if (directW) directW.value = data.workshop_items_raw || "";
        const directM = document.getElementById("mods-direct-ids");
        if (directM) directM.value = data.mods_names_raw || "";
        const directMap = document.getElementById("mods-direct-map");
        if (directMap) directMap.value = data.map_raw || "Muldraugh, KY";

        const listContainer = document.getElementById("active-mods-list");
        if (listContainer) {
            if (!activeModsState.catalog.length && !activeModsState.standalone_mods.length) {
                listContainer.innerHTML = `
                    <div style="text-align: center; padding: 24px; color: var(--text-dim); font-size: 0.85rem;">
                        No hay mods configurados en <code>WorkshopItems=</code> ni <code>Mods=</code>.<br>
                        Añade un ID o URL de Steam Workshop arriba para detectarlo automáticamente.
                    </div>`;
            } else {
                const cardsHtml = activeModsState.catalog.map((entry, idx) => {
                    const wid = entry.workshop_id;
                    const midsText = (entry.mod_ids && entry.mod_ids.length)
                        ? entry.mod_ids.join("; ")
                        : "<span style='color:#f2cc60;'>Sin Mod ID detectado (pulsa Detectar Mod IDs)</span>";
                    const mapsText = (entry.map_folders && entry.map_folders.length)
                        ? `<div style="font-size:0.74rem;color:#7ee2b4;margin-top:2px;">Mapas: ${escapeHtml(entry.map_folders.join("; "))}</div>`
                        : "";
                    const thumb = entry.preview_url
                        ? `<img src="${escapeHtml(entry.preview_url)}" alt="" style="width:44px;height:44px;border-radius:6px;object-fit:cover;border:1px solid var(--border-color);flex-shrink:0;">`
                        : `<div style="width:44px;height:44px;border-radius:6px;background:var(--bg-main);border:1px solid var(--border-color);display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--text-dim);flex-shrink:0;">#${idx + 1}</div>`;
                    const srcBadge = entry.installed_locally
                        ? '<span class="badge badge-success" style="font-size:0.68rem;">Local + Workshop</span>'
                        : `<span class="badge" style="font-size:0.68rem;">${escapeHtml(entry.source || "manual")}</span>`;

                    return `
                        <div class="mod-card" style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 14px;background:var(--bg-subtle);border:1px solid var(--border-color);border-radius:8px;">
                            <div style="display:flex;align-items:center;gap:12px;min-width:0;flex:1;">
                                ${thumb}
                                <div style="min-width:0;">
                                    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                                        <strong style="font-size:0.9rem;color:#e6edf3;">${escapeHtml(entry.title || ("Workshop #" + wid))}</strong>
                                        ${srcBadge}
                                    </div>
                                    <div style="font-size:0.76rem;color:#79c0ff;font-family:var(--font-mono);margin-top:2px;">
                                        Workshop ID: ${escapeHtml(wid)}
                                    </div>
                                    <div style="font-size:0.76rem;color:var(--text-muted);font-family:var(--font-mono);word-break:break-all;">
                                        Mod IDs: ${midsText}
                                    </div>
                                    ${mapsText}
                                    <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=${escapeHtml(wid)}" target="_blank" rel="noopener noreferrer" style="font-size:0.73rem;color:#58a6ff;text-decoration:none;display:inline-flex;align-items:center;gap:4px;margin-top:3px;">
                                        <span>Ver en Steam Workshop</span>
                                    </a>
                                </div>
                            </div>
                            <div style="display:flex;gap:5px;align-items:center;flex-shrink:0;">
                                <button type="button" class="btn btn-outline" onclick="moveModOrder('${attrJsStr(wid)}', -1)" title="Subir prioridad de carga" style="padding:4px 8px;font-size:0.78rem;" ${idx === 0 ? "disabled" : ""}>↑</button>
                                <button type="button" class="btn btn-outline" onclick="moveModOrder('${attrJsStr(wid)}', 1)" title="Bajar prioridad de carga" style="padding:4px 8px;font-size:0.78rem;" ${idx === activeModsState.catalog.length - 1 ? "disabled" : ""}>↓</button>
                                <button type="button" class="btn btn-outline" onclick="removeMod('${attrJsStr(wid)}')" title="Quitar mod" style="padding:4px 10px;font-size:0.78rem;border-color:#f85149;color:#ff7b72;">
                                    <span>Quitar</span>
                                </button>
                            </div>
                        </div>
                    `;
                }).join("");

                const standaloneHtml = activeModsState.standalone_mods.length ? `
                    <div style="padding:10px 14px;background:rgba(210,153,34,0.08);border:1px solid rgba(210,153,34,0.3);border-radius:8px;">
                        <div style="font-size:0.8rem;font-weight:600;color:#f2cc60;margin-bottom:6px;">Mod IDs adicionales en <code>Mods=</code>:</div>
                        <div style="display:flex;flex-wrap:wrap;gap:6px;">
                            ${activeModsState.standalone_mods.map(mid => `
                                <span class="badge" style="font-family:var(--font-mono);font-size:0.74rem;display:inline-flex;align-items:center;gap:6px;">
                                    ${escapeHtml(mid)}
                                    <button type="button" style="background:none;border:none;color:#ff7b72;cursor:pointer;font-weight:700;padding:0;" onclick="removeStandaloneMod('${attrJsStr(mid)}')" title="Quitar Mod ID">×</button>
                                </span>
                            `).join("")}
                        </div>
                    </div>
                ` : "";

                listContainer.innerHTML = cardsHtml + standaloneHtml;
            }
        }

        const localBox = document.getElementById("local-mods-detected");
        if (localBox) {
            if (!activeModsState.local_mods.length) {
                localBox.innerHTML = '<span style="color:var(--text-dim);">No se encontraron archivos <code>mod.info</code> locales aún (se descargan cuando SteamCMD/servidor arranque).</span>';
            } else {
                localBox.innerHTML = activeModsState.local_mods.map(lm => `
                    <div style="padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.06);display:flex;justify-content:space-between;gap:8px;align-items:center;">
                        <div>
                            <div style="font-weight:600;color:#e6edf3;">${escapeHtml(lm.name || lm.mod_id)}</div>
                            <div style="font-family:var(--font-mono);font-size:0.75rem;color:#7ee2b4;">id=${escapeHtml(lm.mod_id)}${lm.workshop_id ? ` • workshop=${escapeHtml(lm.workshop_id)}` : ""}</div>
                        </div>
                        <button type="button" class="btn btn-outline btn-sm" style="padding:3px 8px;font-size:0.72rem;" onclick="enableLocalModId('${attrJsStr(lm.mod_id)}', '${attrJsStr((lm.map_folders || []).join(';'))}')">Activar</button>
                    </div>
                `).join("");
            }
        }
    } catch (e) {
        console.error("Error cargando mods:", e);
    }
}

async function addModManual() {
    const input = document.getElementById("new-mod-id");
    const modTextInput = document.getElementById("new-mod-text-id");
    const mapInput = document.getElementById("new-mod-map-folder");
    if (!input) return;

    const rawVal = input.value.trim();
    const wid = _extractWorkshopId(rawVal);
    const manualModId = (modTextInput?.value || "").trim();
    const manualMap = (mapInput?.value || "").trim();

    if (!wid && !manualModId) {
        showToast("Ingresa un Workshop ID numérico, URL de Steam (?id=...), o un Mod ID manual.", "error");
        return;
    }

    const wItems = [...activeModsState.workshop_items];
    if (wid) {
        if (wItems.includes(wid) && !manualModId && !manualMap) {
            showToast(`El Workshop ID ${wid} ya está configurado.`, "warning");
            return;
        }
        if (!wItems.includes(wid)) wItems.push(wid);
    }

    const mIds = [...activeModsState.mod_ids];
    if (manualModId) {
        manualModId.split(/[;,]/).map(s => s.trim()).filter(Boolean).forEach(m => {
            if (!mIds.includes(m)) mIds.push(m);
        });
    }

    const maps = [...activeModsState.map_folders];
    if (manualMap) {
        manualMap.split(/[;]/).map(s => s.trim()).filter(Boolean).forEach(mf => {
            if (!maps.includes(mf)) {
                const kyIdx = maps.indexOf("Muldraugh, KY");
                if (kyIdx >= 0) maps.splice(kyIdx, 0, mf);
                else maps.unshift(mf);
            }
        });
    }

    const catalog_hints = {};
    if (wid && (manualModId || manualMap)) {
        catalog_hints[wid] = {
            mod_ids: manualModId ? manualModId.split(/[;,]/).map(s => s.trim()).filter(Boolean) : [],
            map_folders: manualMap ? manualMap.split(/[;]/).map(s => s.trim()).filter(Boolean) : [],
            source: "manual"
        };
    }

    showToast("Guardando mod y consultando Steam Workshop...", "info");
    try {
        const res = await fetch("/api/mods", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workshop_items: wItems.join(";"),
                mods_names_raw: mIds.join(";"),
                map_raw: maps.join(";"),
                catalog_hints,
                auto_resolve: true
            })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            input.value = "";
            if (modTextInput) modTextInput.value = "";
            if (mapInput) mapInput.value = "";
            showToast("Mod guardado y catálogo sincronizado.", "success");
            loadMods();
        } else {
            showToast("Error al guardar mod.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al guardar mod.", "error");
    }
}

async function enableLocalModId(modId, mapsStr = "") {
    const mIds = [...activeModsState.mod_ids];
    if (!mIds.includes(modId)) mIds.push(modId);
    const maps = [...activeModsState.map_folders];
    if (mapsStr) {
        mapsStr.split(";").map(s => s.trim()).filter(Boolean).forEach(mf => {
            if (!maps.includes(mf)) maps.unshift(mf);
        });
    }
    const res = await fetch("/api/mods", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            workshop_items: activeModsState.workshop_items.join(";"),
            mods_names_raw: mIds.join(";"),
            map_raw: maps.join(";")
        })
    });
    const data = await window.readApiJson(res);
    if (data.success) {
        showToast(`Mod ID '${modId}' activado en Mods=`, "success");
        loadMods();
    }
}

async function removeMod(wid) {
    const ok = await App.confirm({
        title: "Quitar Mod",
        message: `¿Deseas quitar el Workshop ID ${wid} (y sus Mod IDs asociados) del servidor?`,
        confirmText: "Quitar Mod",
        warning: true
    });
    if (!ok) return;
    const nextW = activeModsState.workshop_items.filter(id => id !== wid);
    const res = await fetch("/api/mods", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workshop_items: nextW.join(";") })
    });
    const data = await window.readApiJson(res);
    if (data.success) {
        showToast(`Mod ${wid} eliminado del .ini.`, "info");
        loadMods();
    }
}

async function moveModOrder(wid, delta) {
    const list = [...activeModsState.workshop_items];
    const idx = list.indexOf(wid);
    const targetIdx = idx + delta;
    if (idx < 0 || targetIdx < 0 || targetIdx >= list.length) return;
    const tmp = list[idx];
    list[idx] = list[targetIdx];
    list[targetIdx] = tmp;

    // Reordenar Mod IDs conocidos siguiendo el nuevo orden de WorkshopItems
    const catalogMap = {};
    (activeModsState.catalog || []).forEach(c => { catalogMap[c.workshop_id] = c; });
    const orderedModIds = [];
    list.forEach(w => {
        const mids = (catalogMap[w] && catalogMap[w].mod_ids) || [];
        mids.forEach(m => { if (!orderedModIds.includes(m)) orderedModIds.push(m); });
    });
    (activeModsState.standalone_mods || []).forEach(m => {
        if (!orderedModIds.includes(m)) orderedModIds.push(m);
    });

    const res = await fetch("/api/mods", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            workshop_items: list.join(";"),
            mods_names_raw: orderedModIds.length ? orderedModIds.join(";") : undefined
        })
    });
    const data = await window.readApiJson(res);
    if (data.success) {
        loadMods();
    }
}

async function importWorkshopCollection() {
    const input = document.getElementById("new-collection-id");
    const raw = (input?.value || "").trim();
    if (!raw) {
        showToast("Pega el ID o URL de una colección de Steam Workshop.", "error");
        return;
    }
    showToast("Importando colección de Steam Workshop (esto puede tardar unos segundos)...", "info");
    try {
        const res = await fetch("/api/mods/collection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ collection: raw })
        });
        const data = await window.readApiJson(res);
        if (res.ok && data.success) {
            if (input) input.value = "";
            showToast(`Colección #${data.collection_id} importada (${data.imported_count} mods).`, "success");
            loadMods();
        } else {
            showToast(data.error || data.detail || "No se pudo importar la colección.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al importar colección.", "error");
    }
}

async function removeStandaloneMod(modId) {
    const nextMods = activeModsState.mod_ids.filter(id => id !== modId);
    const res = await fetch("/api/mods", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            workshop_items: activeModsState.workshop_items.join(";"),
            mods_names_raw: nextMods.join(";")
        })
    });
    const data = await window.readApiJson(res);
    if (data.success) {
        showToast(`Mod ID '${modId}' quitado de Mods=.`, "info");
        loadMods();
    }
}

async function resolveModsCatalog() {
    showToast("Escaneando mod.info locales y consultando Steam Workshop...", "info");
    try {
        const res = await fetch("/api/mods/resolve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sync_to_ini: true })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast(`Catálogo actualizado (${data.count || 0} mods procesados).`, "success");
            loadMods();
        } else {
            showToast("No se pudo resolver el catálogo de mods.", "error");
        }
    } catch (e) {
        showToast("Error consultando Steam Workshop.", "error");
    }
}

async function saveDirectModsIni() {
    const workshop_items = document.getElementById("mods-direct-workshop")?.value.trim() || "";
    const mods_names_raw = document.getElementById("mods-direct-ids")?.value.trim() || "";
    const map_raw = document.getElementById("mods-direct-map")?.value.trim() || "Muldraugh, KY";
    try {
        const res = await fetch("/api/mods", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workshop_items, mods_names_raw, map_raw })
        });
        const data = await window.readApiJson(res);
        if (data.success) {
            showToast("Líneas WorkshopItems=, Mods= y Map= guardadas en .ini.", "success");
            loadMods();
        } else {
            showToast("Error al guardar configuración exacta de mods.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al guardar .ini de mods.", "error");
    }
}

// --- Filtro de consola en vivo ---
function filterConsoleLogs(term) {
    const consoleOutput = document.getElementById("console-output");
    if (!consoleOutput) return;
    const cleanTerm = (term || "").toLowerCase().trim();
    const lines = consoleOutput.children;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (!cleanTerm) {
            line.style.display = "";
        } else {
            const matches = line.textContent.toLowerCase().includes(cleanTerm);
            line.style.display = matches ? "" : "none";
        }
    }
}
