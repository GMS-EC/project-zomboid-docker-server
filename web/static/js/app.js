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

// Escapa una cadena para insertarla DENTRO de un string de JS delimitado por
// comillas simples, dentro de un atributo HTML onclick="...". Previene que datos
// externos (p. ej. nombres de jugadores) rompan el atributo o inyecten código.
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

// PZ Server Manager Main Client Script
let metricsChart = null;
let currentInstanceId = "main";
let isAutoScroll = true;
let commandHistory = JSON.parse(localStorage.getItem("ark_cmd_history") || "[]");
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
    loadBackups();
    loadSettings();
    loadTaskSettings();
    loadMods();
    loadActivityLogs();
    initConsoleHistory();
    if (typeof Files !== "undefined" && Files.init) {
        Files.init();
    }

    // Restaurar pestaña activa guardada
    const hash = window.location.hash ? window.location.hash.substring(1) : "";
    const savedTab = hash || localStorage.getItem("ark_active_tab");
    if (savedTab && savedTab !== "console" && document.getElementById(`tab-${savedTab}`)) {
        switchTab(savedTab);
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
    document.querySelectorAll(".nav-btn, .nav-item").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));

    const navLink = document.querySelector(`.nav-btn[data-tab="${tabId}"], .nav-item[data-tab="${tabId}"]`);
    const targetPane = document.getElementById(`tab-${tabId}`);

    if (navLink) navLink.classList.add("active");
    if (targetPane) targetPane.classList.add("active");

    localStorage.setItem("ark_active_tab", tabId);
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

    if (tabId === "tasks") {
        loadTaskSettings();
        pollTasksStatusIfActive();
    } else {
        stopTasksStatusPolling();
    }

    if (tabId === "webhooks") {
        loadWebhookSettings();
    }

    if (tabId === "mods") {
        loadMods();
    }

    if (tabId === "console") {
        loadActivityLogs();
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
        // Solo reconectar si este socket sigue siendo el actual (evita sockets huérfanos
        // duplicados al cambiar de nodo o al reconectar).
        if (ws !== socket) return;
        ws = null;
        // Cierre por sesión expirada / no autorizado: no reintentar en bucle infinito.
        if (ev && ev.code === 1008) {
            wsShouldReconnect = false;
            return;
        }
        if (wsShouldReconnect) {
            scheduleWsReconnect();
        }
    };
}

function sendQuickCommand(cmd) {
    const input = document.getElementById("console-input");
    if (input) {
        input.value = cmd;
        sendConsoleCommand();
    }
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

function initConsoleHistory() {
    const input = document.getElementById("console-input");
    if (!input || input.dataset.historyBound) return;
    input.dataset.historyBound = "true";

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
            }
        } else if (e.key === "ArrowDown") {
            if (cmdHistoryIndex > 0) {
                e.preventDefault();
                cmdHistoryIndex--;
                input.value = commandHistory[commandHistory.length - 1 - cmdHistoryIndex];
                input.setSelectionRange(input.value.length, input.value.length);
            } else if (cmdHistoryIndex === 0) {
                e.preventDefault();
                cmdHistoryIndex = -1;
                input.value = cmdDraft;
            }
        }
    });
}

async function copyServerAddress() {
    // Project Zomboid: los clientes se conectan por IP:puerto (Direct Connect),
    // tanto en la versión Steam como en la No-Steam (GOG).
    let port = 16261;
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        port = (data.network && data.network.server_port) || 16261;
    } catch (e) { /* puerto por defecto */ }
    const host = window.location.hostname || "127.0.0.1";
    const link = `${host}:${port}`;
    try {
        await navigator.clipboard.writeText(link);
        showToast(`Dirección copiada: ${link}`, "success");
    } catch (e) {
        showToast("No se pudo copiar la dirección.", "error");
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
        localStorage.setItem("ark_cmd_history", JSON.stringify(commandHistory));
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
}

// --- Controles de Servidor (Project Zomboid) ---
async function startServer() {
    showToast("Iniciando servidor de Project Zomboid...", "info");
    const res = await fetch("/api/server/start", { method: "POST" });
    const data = await res.json();
    if (data.success) {
        showToast("Servidor de PZ arrancando (estado: " + (data.status || "STARTING") + ").", "success");
    } else {
        showToast(data.error || "No se pudo iniciar el servidor.", "error");
        if (data.is_setup_done === false) {
            switchTab("installer");
        }
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
    const res = await fetch("/api/server/stop", { method: "POST" });
    const data = await res.json();
    if (data.success) {
        showToast("Servidor detenido.", "success");
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
    await fetch("/api/server/restart", { method: "POST" });
}

// --- Acciones Rápidas (consola PZ) ---
async function triggerReloadOptions() {
    const ok = await App.confirm({
        title: "Recargar Configuración",
        message: "¿Enviar 'reloadoptions'? Las opciones de <ServerName>.ini se aplicarán en caliente.",
        confirmText: "Recargar Opciones",
        warning: true
    });
    if (!ok) return;
    showToast("Enviando reloadoptions...", "info");
    await sendCommandOrWs("reloadoptions");
    showToast("reloadoptions enviado a la consola.", "success");
}

async function saveGameNow() {
    showToast("Guardando estado del mundo (save)...", "info");
    const res = await fetch("/api/server/save", { method: "POST" });
    const data = await res.json();
    if (data.success) {
        showToast("Comando save enviado a la consola.", "success");
    }
}

async function sendCommandOrWs(command) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(command);
        return;
    }
    await fetch("/api/server/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: command })
    });
}

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

async function fetchMetricsOnce() {
    try {
        const res = await fetch("/api/metrics");
        const data = await res.json();
        const curr = data.current;
        const isOffline = curr.status === "OFFLINE";

        // Actualizar Tarjetas de Métricas
        if (document.getElementById("val-cpu")) document.getElementById("val-cpu").textContent = `${curr.cpu_percent}%`;
        if (document.getElementById("val-ram")) document.getElementById("val-ram").textContent = `${curr.ram_used_gb} / ${curr.ram_total_gb} GB`;
        if (document.getElementById("val-ark-ram")) document.getElementById("val-ark-ram").textContent = `${curr.ark_ram_gb} GB`;
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
        if (topStatus) {
            topStatus.textContent = curr.status;
            topStatus.className = `overview-val status-text-inline ${curr.status.toLowerCase()}`;
        }
        const topUptime = document.getElementById("top-server-uptime");
        if (topUptime) topUptime.textContent = curr.uptime_formatted;
        const topCpu = document.getElementById("top-server-cpu");
        if (topCpu) topCpu.textContent = `${isOffline ? 0.0 : curr.cpu_percent} %`;
        const topArkMem = document.getElementById("top-server-ark-memory");
        if (topArkMem) topArkMem.textContent = `${curr.ark_ram_gb} GB`;
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
        if (statMemVal) statMemVal.textContent = `${curr.ark_ram_gb} GB`;
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
            metricsChart.data.datasets[1].data = data.history.map(h => h.ark_ram_gb);
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

// --- Jugadores & Moderación (Dockraft Enhanced) ---
let playersCache = { online: [], history: [] };
let activePlayerTab = "online";
let playerSearchQuery = "";

// Paleta de gradientes atractivos para avatares de supervivientes
const AVATAR_GRADIENTS = [
    "linear-gradient(135deg, #4f46e5, #06b6d4)",
    "linear-gradient(135deg, #10b981, #059669)",
    "linear-gradient(135deg, #f59e0b, #d97706)",
    "linear-gradient(135deg, #ec4899, #8b5cf6)",
    "linear-gradient(135deg, #3b82f6, #1d4ed8)",
    "linear-gradient(135deg, #8b5cf6, #6366f1)"
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
        const data = await res.json();
        playersCache = {
            online: data.online || [],
            history: data.history || []
        };

        // 1. Actualizar métricas del banner superior de jugadores
        const statOnline = document.getElementById("players-online-stat");
        if (statOnline) {
            const maxP = (metricsChart && metricsChart.data && metricsChart.data.max_players) || 20;
            statOnline.textContent = `${playersCache.online.length}`;
        }
        const statHist = document.getElementById("players-history-stat");
        if (statHist) statHist.textContent = playersCache.history.length;

        const bannedCount = playersCache.history.filter(p => p.banned).length;
        const statBanned = document.getElementById("players-banned-stat");
        if (statBanned) statBanned.textContent = bannedCount;

        // 2. Actualizar contadores en selector segmentado
        const countOnline = document.getElementById("count-tab-online");
        if (countOnline) countOnline.textContent = playersCache.online.length;
        const countHist = document.getElementById("count-tab-history");
        if (countHist) countHist.textContent = playersCache.history.length;

        renderPlayersList();
    } catch (e) {
        console.error("Error cargando jugadores:", e);
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

    let list = [];
    if (activePlayerTab === "online") {
        list = playersCache.online.map(p => ({
            name: p.name,
            steam_id: p.steam_id,
            is_online: true,
            banned: false,
            last_seen: p.last_seen || "En juego ahora"
        }));
    } else {
        // En historial, cruzar con online para marcar los que estén activos
        const onlineSteamIds = new Set(playersCache.online.map(p => p.steam_id));
        list = playersCache.history.map(p => ({
            name: p.name,
            steam_id: p.steam_id,
            is_online: onlineSteamIds.has(p.steam_id),
            banned: !!p.banned,
            last_seen: p.last_seen || p.first_seen || "-"
        }));
    }

    if (playerSearchQuery) {
        list = list.filter(p =>
            p.name.toLowerCase().includes(playerSearchQuery) ||
            p.steam_id.toLowerCase().includes(playerSearchQuery)
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
                <td colspan="5" style="text-align: center; color: var(--text-dim); padding: 40px 20px;">
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
        const hasValidSteamId = p.steam_id && p.steam_id !== "N/A" && p.steam_id !== "Desconocido";

        let statusBadge = "";
        if (p.banned) {
            statusBadge = `<span class="status-pill offline" style="font-size: 0.72rem; padding: 2px 8px; border-color: #f85149; color: #ff7b72;"><span class="status-dot" style="background-color: #f85149; box-shadow: 0 0 6px rgba(248,81,73,0.6);"></span>Baneado</span>`;
        } else if (p.is_online) {
            statusBadge = `<span class="status-pill online" style="font-size: 0.72rem; padding: 2px 8px;"><span class="status-dot online"></span>En línea</span>`;
        } else {
            statusBadge = `<span class="status-pill offline" style="font-size: 0.72rem; padding: 2px 8px; color: #8b949e;"><span class="status-dot offline"></span>Desconectado</span>`;
        }

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
                        ` : '<span style="font-size: 0.72rem; color: var(--text-dim);">Consulta local</span>'}
                    </div>
                </div>
            </td>
            <td>
                <div class="steam-id-pill">
                    <span>${escapeHtml(p.steam_id)}</span>
                    ${hasValidSteamId ? `
                        <button type="button" class="btn-copy-steam" onclick="copySteamId('${attrJsStr(p.steam_id)}')" title="Copiar SteamID al portapapeles">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                        </button>
                    ` : ''}
                </div>
            </td>
            <td>
                <div style="font-size: 0.8rem; color: #8b949e; display: flex; align-items: center; gap: 5px;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    <span>${escapeHtml(p.last_seen)}</span>
                </div>
            </td>
            <td>${statusBadge}</td>
            <td style="text-align: right;">
                <div style="display: inline-flex; gap: 6px; align-items: center; justify-content: flex-end;">
                    ${p.is_online && hasValidSteamId ? `
                        <button class="btn btn-outline" style="padding: 4px 10px; font-size: 0.76rem; border-color: #58a6ff; color: #79c0ff;" onclick="messagePlayer('${attrJsStr(p.steam_id)}', '${attrJsStr(p.name)}')">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                            <span>Mensaje</span>
                        </button>
                    ` : ''}
                    ${p.is_online && hasValidSteamId ? `
                        <button class="btn btn-danger" style="padding: 4px 10px; font-size: 0.76rem;" onclick="kickPlayer('${attrJsStr(p.steam_id)}', '${attrJsStr(p.name)}')">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
                            <span>Expulsar</span>
                        </button>
                    ` : ''}
                    ${!p.banned && hasValidSteamId ? `
                        <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 0.76rem;" onclick="banPlayer('${attrJsStr(p.steam_id)}', '${attrJsStr(p.name)}')">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                            <span>Banear</span>
                        </button>
                    ` : ''}
                    ${p.banned && hasValidSteamId ? `
                        <button class="btn btn-success" style="padding: 4px 10px; font-size: 0.76rem;" onclick="unbanPlayer('${attrJsStr(p.steam_id)}', '${attrJsStr(p.name)}')">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>
                            <span>Desbanear</span>
                        </button>
                    ` : ''}
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function copySteamId(steamId) {
    if (!steamId) return;
    navigator.clipboard.writeText(steamId).then(() => {
        showToast(`SteamID ${steamId} copiado al portapapeles.`, "success");
    }).catch(() => {
        showToast(`SteamID: ${steamId}`, "info");
    });
}

async function messagePlayer(steamId, name) {
    const msg = await App.prompt({
        title: `Mensaje a ${name}`,
        message: `Escribe el mensaje privado in-game que se enviará en vivo a este jugador:`,
        placeholder: "ej: Hola, escribe tu mensaje para este jugador...",
        confirmText: "Enviar Mensaje"
    });
    if (!msg || !msg.trim()) return;

    try {
        const res = await fetch("/api/players/message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ steam_id: steamId, message: msg.trim() })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Mensaje enviado a ${name}.`, "success");
        } else {
            showToast("Error enviando mensaje privado.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al enviar mensaje.", "error");
    }
}

async function kickPlayer(steamId, name) {
    const ok = await App.confirm({
        title: "Expulsar Superviviente",
        message: `¿Expulsar del servidor al superviviente "${name}" (SteamID: ${steamId})?`,
        confirmText: "Expulsar",
        danger: true
    });
    if (!ok) return;
    try {
        await fetch("/api/players/kick", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ steam_id: steamId })
        });
        showToast(`Superviviente ${name} expulsado.`, "info");
        loadPlayers();
    } catch (e) {
        showToast("Error al expulsar superviviente.", "error");
    }
}

async function banPlayer(steamId, name) {
    const ok = await App.confirm({
        title: "Banear Superviviente",
        message: `¿Banear permanentemente del servidor al superviviente "${name}" (SteamID: ${steamId})?`,
        confirmText: "Banear",
        danger: true
    });
    if (!ok) return;
    try {
        await fetch("/api/players/ban", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ steam_id: steamId })
        });
        showToast(`Superviviente ${name} baneado.`, "error");
        loadPlayers();
    } catch (e) {
        showToast("Error al banear superviviente.", "error");
    }
}

async function unbanPlayer(steamId, name) {
    const ok = await App.confirm({
        title: "Desbanear Superviviente",
        message: `¿Remover la sanción y permitir que "${name}" (SteamID: ${steamId}) vuelva a ingresar al servidor?`,
        confirmText: "Desbanear"
    });
    if (!ok) return;
    try {
        await fetch("/api/players/unban", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ steam_id: steamId })
        });
        showToast(`Sanción removida para ${name}.`, "success");
        loadPlayers();
    } catch (e) {
        showToast("Error al desbanear superviviente.", "error");
    }
}

// --- Backups ---
async function loadBackups() {
    try {
        const res = await fetch("/api/backups");
        const data = await res.json();
        const tbody = document.getElementById("backups-table-body");
        if (!tbody) return;
        tbody.innerHTML = "";

        if (data.backups.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color: var(--text-dim);">No existen copias de seguridad aún.</td></tr>`;
            return;
        }

        data.backups.forEach(b => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${escapeHtml(b.filename)}</strong></td>
                <td>${b.size_mb} MB</td>
                <td>${b.created_at}</td>
                <td>
                    <div style="display: inline-flex; align-items: center; gap: 6px;">
                        <a href="/api/backups/download/${encodeURIComponent(b.filename)}" class="btn btn-outline" title="Descargar copia de seguridad" download style="padding: 4px 8px; font-size: 11px; display: inline-flex; align-items: center; justify-content: center; color: #58a6ff; border-color: rgba(56, 189, 248, 0.4); background: rgba(56, 189, 248, 0.08); text-decoration: none; border-radius: 6px;">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                        </a>
                        <button class="btn btn-warning" style="padding: 4px 10px; font-size: 11px;" onclick="restoreBackup('${attrJsStr(b.filename)}')">Restaurar</button>
                        <button class="btn btn-danger" style="padding: 4px 10px; font-size: 11px;" onclick="deleteBackup('${attrJsStr(b.filename)}')">Eliminar</button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {}
}

async function createBackupNow() {
    const name = await App.prompt({
        title: "Crear Copia de Seguridad",
        message: "Nombre descriptivo para identificar este respaldo (opcional):",
        placeholder: "ej: antes_del_boss",
        confirmText: "Crear Copia"
    });
    if (name === null) return;
    showToast("Comprimiendo mundo guardado...", "info");
    const res = await fetch("/api/backups/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name || null })
    });
    const data = await res.json();
    if (data.success) {
        showToast("Copia de seguridad generada con éxito.", "success");
        loadBackups();
    } else {
        showToast(`Error creando backup: ${data.error}`, "error");
    }
}

async function restoreBackup(filename) {
    const ok = await App.confirm({
        title: "Restaurar Copia de Seguridad",
        message: `¿Restaurar '${filename}'?\n\nLos datos actuales del mundo serán reemplazados (se creará una salvaguarda automática antes) y el servidor se reiniciará.`,
        confirmText: "Restaurar Respaldo",
        danger: true
    });
    if (!ok) return;
    showToast("Restaurando copia...", "info");
    const res = await fetch("/api/backups/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: filename })
    });
    const data = await res.json();
    if (data.success) {
        showToast("Mundo restaurado con éxito.", "success");
    } else {
        showToast(`Error al restaurar: ${data.error}`, "error");
    }
}

async function deleteBackup(filename) {
    const ok = await App.confirm({
        title: "Eliminar Copia de Seguridad",
        message: `¿Estás seguro de eliminar permanentemente la copia '${filename}'?`,
        confirmText: "Eliminar",
        danger: true
    });
    if (!ok) return;
    await fetch("/api/backups/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: filename })
    });
    showToast("Copia eliminada.", "info");
    loadBackups();
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
    } else {
        textarea.value = cachedSettingsData.raw_ini || "";
    }
}

function toggleRawFileView(type) {
    currentRawFileType = type;
    const btnIni = document.getElementById("btn-raw-mode-ini");
    const btnSandbox = document.getElementById("btn-raw-mode-sandbox");
    if (btnIni && btnSandbox) {
        if (type === 'ini') {
            btnIni.style.background = 'rgba(56, 189, 248, 0.15)';
            btnIni.style.borderColor = '#38bdf8';
            btnIni.style.color = '#38bdf8';
            btnSandbox.style.background = 'transparent';
            btnSandbox.style.borderColor = 'var(--border-color)';
            btnSandbox.style.color = 'var(--text-color)';
        } else {
            btnSandbox.style.background = 'rgba(56, 189, 248, 0.15)';
            btnSandbox.style.borderColor = '#38bdf8';
            btnSandbox.style.color = '#38bdf8';
            btnIni.style.background = 'transparent';
            btnIni.style.borderColor = 'var(--border-color)';
            btnIni.style.color = 'var(--text-color)';
        }
    }
    renderRawFileInEditor();
}

async function saveRawFileCurrent() {
    const textarea = document.getElementById("raw-file-content");
    if (!textarea) return;
    showToast(`Guardando archivo ${currentRawFileType === 'sandbox' ? 'SandboxVars.lua' : '.ini'}...`, "info");
    try {
        const res = await fetch("/api/settings/raw", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: currentRawFileType, content: textarea.value })
        });
        const r = await res.json();
        if (r.success) {
            showToast(`Archivo ${currentRawFileType === 'sandbox' ? 'SandboxVars.lua' : '.ini'} guardado con éxito.`, "success");
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
            showToast("Ajustes guardados con éxito en Server.ini y SandboxVars.lua.", "success");
            loadSettings();
        } else {
            showToast("Error al guardar ajustes.", "error");
        }
    } catch (err) {
        showToast("Error de conexión al guardar configuraciones.", "error");
    }
}

const saveSettings = saveAllSettings;

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


// --- Automatizaciones del servidor PZ ---
async function loadTaskSettings() {
    try {
        const res = await fetch("/api/tasks/config");
        const cfg = await res.json();
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
        setVal("task-schedule-enabled", String(!!cfg.schedule_enabled));
        setVal("task-schedule-start", cfg.schedule_start || "20:00");
        setVal("task-schedule-stop", cfg.schedule_stop || "00:00");
        setVal("task-schedule-warn", cfg.schedule_warn_mins || 10);
        setVal("task-backup-enabled", String(cfg.auto_backup_enabled !== false));
        setVal("task-backup-hours", cfg.auto_backup_interval_hours || 6);
        setVal("task-backup-max-count", cfg.backup_max_count || 10);
        setVal("task-restart-hours", cfg.auto_restart_hours || 0);
        setVal("task-restart-warn", cfg.restart_warn_mins || 10);
    } catch (e) {
        console.error("Error al cargar configuración de tareas:", e);
    }
}

async function saveTaskSettings() {
    const getVal = (id, fb) => { const el = document.getElementById(id); return el ? el.value : fb; };
    const payload = {
        schedule_enabled: getVal("task-schedule-enabled", "false") === "true",
        schedule_start: getVal("task-schedule-start", "20:00"),
        schedule_stop: getVal("task-schedule-stop", "00:00"),
        schedule_warn_mins: parseInt(getVal("task-schedule-warn", "10")) || 10,
        auto_backup_enabled: getVal("task-backup-enabled", "true") === "true",
        auto_backup_interval_hours: parseInt(getVal("task-backup-hours", "6")) || 6,
        backup_max_count: parseInt(getVal("task-backup-max-count", "10")) || 10,
        auto_restart_hours: parseInt(getVal("task-restart-hours", "0")) || 0,
        restart_warn_mins: parseInt(getVal("task-restart-warn", "10")) || 10
    };
    try {
        const res = await fetch("/api/tasks/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const r = await res.json();
        if (r.success) showToast("Horarios y tareas guardados.", "success");
        else showToast("Error al guardar tareas.", "error");
    } catch (e) {
        showToast("Error de conexión al guardar tareas.", "error");
    }
}

// --- Estado en tiempo real del planificador ---
let tasksStatusTimer = null;
async function pollTasksStatusIfActive() {
    try {
        const res = await fetch("/api/tasks/status");
        const st = await res.json();
        const txt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v === undefined || v === null) ? "--" : v; };
        txt("ts-running", st.running ? "Activo" : "Detenido");
        txt("ts-ticks", st.ticks || 0);
        txt("ts-errors", st.errors || 0);
        txt("ts-schedule", st.schedule || "--");
        txt("ts-backup", st.backup || "--");
        txt("ts-restart", st.restart || "--");
        txt("ts-error-msg", st.error_msg || "");
        const dot = document.getElementById("ts-status-dot");
        if (dot) dot.style.background = st.running ? "#3fb950" : "#8b949e";
    } catch (e) { /* ignorar */ }
    tasksStatusTimer = setTimeout(pollTasksStatusIfActive, 5000);
}
function stopTasksStatusPolling() { if (tasksStatusTimer) clearTimeout(tasksStatusTimer); }

async function triggerRestartSafeModal() {
    const ok = await App.confirm({
        title: "Reinicio Seguro (5 minutos)",
        message: "¿Programar el reinicio del servidor PZ en 5 minutos? Se enviarán avisos in-game (servermsg) y un guardado antes de apagar.",
        confirmText: "Programar Reinicio",
        warning: true
    });
    if (!ok) return;
    try {
        const res = await fetch("/api/server/restart_safe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ minutes: 5 })
        });
        const r = await res.json();
        if (r.success) showToast("Reinicio programado en 5 minutos.", "success");
        else showToast("No se pudo programar el reinicio.", "error");
    } catch (e) {
        showToast("Error al programar reinicio.", "error");
    }
}

// --- Sistema de Diálogos Modales y Notificaciones (Dockraft Style) ---
const App = {
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

  confirm(options) {
    return new Promise((resolve) => {
      const modal = this.ensureConfirmModal();
      const opts = typeof options === 'string' ? { message: options } : (options || {});
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

  prompt(options) {
    return new Promise((resolve) => {
      const modal = this.ensurePromptModal();
      const opts = typeof options === 'string' ? { message: options } : (options || {});
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
async function startServerInstallation(e) {
    if (e) e.preventDefault();
    const ok = await App.confirm({
        title: "Configuración Inicial del Servidor Project Zomboid",
        message: "¿Deseas guardar esta configuración inicial y arrancar el servidor dedicado de PZ?",
        confirmText: "Guardar e Iniciar"
    });
    if (!ok) return;

    const payload = {
        use_steam: document.getElementById("wizard-steam") ? document.getElementById("wizard-steam").value === "true" : true,
        server_name: document.getElementById("wizard-session-name") ? document.getElementById("wizard-session-name").value.trim() : "servertest",
        server_password: document.getElementById("wizard-server-pass") ? document.getElementById("wizard-server-pass").value : "",
        admin_password: document.getElementById("wizard-admin-pass") ? document.getElementById("wizard-admin-pass").value : "adminpass",
        max_players: document.getElementById("wizard-max-players") ? parseInt(document.getElementById("wizard-max-players").value) || 16 : 16,
        pvp: document.getElementById("wizard-mode") ? document.getElementById("wizard-mode").value === "pvp" : false,
        memory_min: document.getElementById("wizard-mem-min") ? document.getElementById("wizard-mem-min").value : "4g",
        memory_max: document.getElementById("wizard-mem-max") ? document.getElementById("wizard-mem-max").value : "6g",
        mod_ids: document.getElementById("wizard-mods") ? document.getElementById("wizard-mods").value : ""
    };

    showToast("Guardando configuración inicial...", "info");
    try {
        const res = await fetch("/api/server/install", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || "Configuración completada. Iniciando servidor...", "success");
            setTimeout(() => {
                window.location.reload();
            }, 1200);
        } else {
            showToast(data.error || "Error al iniciar la instalación.", "error");
        }
    } catch (err) {
        showToast("Error de conexión al iniciar instalación.", "error");
    }
}

// ==========================================
// --- GESTIÓN DE MODS DE STEAM WORKSHOP ---
let activeModsList = [];

async function loadMods() {
    try {
        const res = await fetch("/api/mods");
        const data = await res.json();
        activeModsList = data.mods || [];

        const countEl = document.getElementById("mods-count-val");
        if (countEl) countEl.textContent = activeModsList.length;

        const listContainer = document.getElementById("active-mods-list");
        if (!listContainer) return;

        if (activeModsList.length === 0) {
            listContainer.innerHTML = `
                <div style="text-align: center; padding: 24px; color: var(--text-dim); font-size: 0.85rem;">
                    No hay mods configurados en el servidor actualmente.<br>
                    Puedes añadir uno manualmente arriba o seleccionar uno del catálogo recomendado.
                </div>`;
            return;
        }

        listContainer.innerHTML = activeModsList.map((modId, index) => `
            <div class="mod-card" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: var(--bg-subtle); border: 1px solid var(--border-color); border-radius: 6px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 0.8rem; font-weight: 700; color: var(--text-dim); width: 20px;">#${index + 1}</span>
                    <div>
                        <div style="font-weight: 600; font-size: 0.9rem; color: #79c0ff; font-family: var(--font-mono);">
                            Mod ID: ${modId}
                        </div>
                        <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=${modId}" target="_blank" rel="noopener noreferrer" style="font-size: 0.75rem; color: #58a6ff; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;">
                            <span>Ver en Steam Workshop</span>
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                        </a>
                    </div>
                </div>
                <button type="button" class="btn btn-outline" onclick="removeMod('${modId}')" title="Quitar mod" style="padding: 4px 10px; font-size: 0.78rem; border-color: #f85149; color: #ff7b72;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    <span>Quitar</span>
                </button>
            </div>
        `).join("");
    } catch (e) {
        console.error("Error cargando mods:", e);
    }
}

async function addModManual() {
    const input = document.getElementById("new-mod-id");
    if (!input) return;
    const modId = input.value.trim();
    if (!modId || !/^[0-9]+$/.test(modId)) {
        showToast("Por favor ingresa un Mod ID numérico válido de Steam.", "error");
        return;
    }
    if (activeModsList.includes(modId)) {
        showToast(`El mod ${modId} ya se encuentra en la lista.`, "warning");
        return;
    }
    activeModsList.push(modId);
    await saveModsList();
    input.value = "";
}

async function removeMod(modId) {
    const ok = await App.confirm({
        title: "Quitar Mod",
        message: `¿Deseas quitar el Mod ID ${modId} de la lista activa del servidor?`,
        confirmText: "Quitar Mod",
        warning: true
    });
    if (!ok) return;
    activeModsList = activeModsList.filter(id => id !== modId);
    await saveModsList();
    showToast(`Mod ${modId} eliminado.`, "info");
}

async function saveModsList() {
    try {
        const raw_ids = activeModsList.join(",");
        const res = await fetch("/api/mods", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mod_ids: raw_ids })
        });
        const data = await res.json();
        if (data.success) {
            loadMods();
        } else {
            showToast("Error al guardar la lista de mods.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al guardar mods.", "error");
    }
}

async function updateModsNow() {
    showToast("Iniciando actualización de mods en segundo plano...", "info");
    try {
        const res = await fetch("/api/mods/update", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Comprobando actualizaciones de mods. Revisa la consola en vivo.", "success");
        } else {
            showToast("No se pudo iniciar la actualización de mods.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al solicitar actualización.", "error");
    }
}

// --- COMANDOS RÁPIDOS DE CONSOLA ---
// --- FILTRO DE CONSOLA EN VIVO ---
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

// --- Webhooks de Discord (Dockraft Style) ---
async function loadWebhookSettings() {
    try {
        const res = await fetch("/api/webhooks");
        const data = await res.json();
        
        const input = document.getElementById("webhook-url");
        if (input && data.url) input.value = data.url;

        const langSelect = document.getElementById("webhook-lang");
        if (langSelect && data.language) langSelect.value = data.language;

        const ev = data.events || {};
        const setCheck = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.checked = val !== false;
        };

        setCheck("wh-evt-start", ev.start);
        setCheck("wh-evt-starting", ev.starting);
        setCheck("wh-evt-shutdown", ev.shutdown);
        setCheck("wh-evt-shutdown-warn", ev.shutdown_warn);
        setCheck("wh-evt-backup", ev.backup);
        setCheck("wh-evt-save", ev.save);
        setCheck("wh-evt-restart", ev.restart);
        const elPlayers = document.getElementById("wh-evt-players");
        if (elPlayers) elPlayers.checked = !!ev.players;
    } catch (e) {
        console.error("Error al cargar webhook:", e);
    }
}

async function saveWebhookSettings() {
    const input = document.getElementById("webhook-url");
    const url = input ? input.value.trim() : "";
    const lang = document.getElementById("webhook-lang")?.value || "es";

    const getCheck = (id, fallback) => {
        const el = document.getElementById(id);
        return el ? el.checked : fallback;
    };

    const eventsPayload = {
        start: getCheck("wh-evt-start", true),
        starting: getCheck("wh-evt-starting", true),
        shutdown: getCheck("wh-evt-shutdown", true),
        shutdown_warn: getCheck("wh-evt-shutdown-warn", true),
        backup: getCheck("wh-evt-backup", true),
        save: getCheck("wh-evt-save", true),
        restart: getCheck("wh-evt-restart", true),
        players: getCheck("wh-evt-players", false)
    };

    try {
        const res = await fetch("/api/webhooks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: url, language: lang, events: eventsPayload })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Configuración de Webhook guardada exitosamente.", "success");
        } else {
            showToast("Error al guardar webhook.", "error");
        }
    } catch (e) {
        showToast("Error de conexión al guardar webhook.", "error");
    }
}

async function testWebhookNotification() {
    const input = document.getElementById("webhook-url");
    const url = input ? input.value.trim() : "";
    if (!url) {
        showToast("Por favor ingresa primero la URL del Webhook.", "error");
        return;
    }
    showToast("Enviando notificación de prueba a Discord...", "info");
    try {
        const res = await fetch("/api/webhooks/test", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("¡Notificación entregada con éxito a tu canal de Discord!", "success");
        } else {
            showToast(data.error || "No se pudo entregar la notificación a Discord.", "error");
        }
    } catch (e) {
        showToast("Error al probar notificación de Discord.", "error");
    }
}

// --- Historial de Auditoría (7 Días) ---
let activityLogsData = [];

async function loadActivityLogs() {
    const tbody = document.getElementById("activity-log-body");
    if (!tbody) return;
    try {
        const res = await fetch("/api/activity");
        const data = await res.json();
        activityLogsData = data.activities || [];
        const countBadge = document.getElementById("audit-count-badge");
        if (countBadge) countBadge.textContent = `${activityLogsData.length} registros`;
        renderActivityLogs(activityLogsData);
    } catch (e) {
        if (tbody) tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-dim); padding: 14px;">Error cargando historial de auditoría.</td></tr>`;
    }
}

function renderActivityLogs(logs) {
    const tbody = document.getElementById("activity-log-body");
    if (!tbody) return;
    if (!logs || logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-dim); padding: 16px;">No hay actividades registradas en los últimos 7 días.</td></tr>`;
        return;
    }

    const categoryColors = {
        "Servidor": "#58a6ff",
        "Seguridad": "#f85149",
        "Consola": "#79c0ff",
        "PZ": "#3fb950",
        "Mods": "#d29922",
        "Jugadores": "#a371f7",
        "Configuración": "#38bdf8",
        "Webhooks": "#58a6ff",
        "Tareas": "#e3b341",
        "Backups": "#3fb950",
        "Archivos": "#8b949e",
        "Clúster": "#58a6ff",
        "Instalación": "#f0883e"
    };

    const visible = logs.slice(0, 100);
    const rows = visible.map(item => {
        const color = categoryColors[item.category] || "#8b949e";
        return `
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding: 8px 14px; font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-dim); white-space: nowrap;">${escapeHtml(item.timestamp)}</td>
                <td style="padding: 8px 14px; white-space: nowrap;">
                    <span style="font-size: 0.72rem; font-weight: 600; padding: 2px 7px; border-radius: 4px; background: rgba(255,255,255,0.06); color: ${color}; border: 1px solid ${color}44;">
                        ${escapeHtml(item.category)}
                    </span>
                </td>
                <td style="padding: 8px 14px; color: var(--text-color); font-weight: 500; font-size: 0.8rem; white-space: nowrap;">${escapeHtml(item.user || "Sistema")}</td>
                <td style="padding: 8px 14px; color: var(--text-muted); font-size: 0.82rem; word-break: break-word;">${escapeHtml(item.message)}</td>
            </tr>
        `;
    }).join("");

    // Limitar el DOM: se muestran las 100 más recientes (el filtro opera sobre el total)
    if (logs.length > 100) {
        rows += `<tr><td colspan="4" style="text-align:center; padding:10px; color:var(--text-dim); font-size:0.78rem;">Mostrando las 100 más recientes de ${logs.length} registros. Usa el buscador para filtrar.</td></tr>`;
    }
    tbody.innerHTML = rows;
}

function filterActivityLogs(query) {
    if (!query || !query.trim()) {
        renderActivityLogs(activityLogsData);
        return;
    }
    const q = query.toLowerCase().trim();
    const filtered = activityLogsData.filter(item => {
        return (item.message && item.message.toLowerCase().includes(q)) ||
               (item.category && item.category.toLowerCase().includes(q)) ||
               (item.user && item.user.toLowerCase().includes(q)) ||
               (item.timestamp && item.timestamp.toLowerCase().includes(q));
    });
    renderActivityLogs(filtered);
}
