/* ==========================================================================
   Registros de Auditoría y Eventos (Project Zomboid)
   ========================================================================== */

const _logsEscapeHtml = (str) => (window.escapeHtml ? window.escapeHtml(str) : String(str ?? ""));

const Logs = {
  currentCategory: "all",
  searchQuery: "",
  currentPage: 1,
  pageSize: 25,
  totalRecords: 0,
  autoRefreshTimer: null,
  searchDebounceTimer: null,

  init() {
    const autoCheck = document.getElementById("logs-auto-refresh");
    if (autoCheck && autoCheck.checked) {
      this.startAutoRefresh();
    }
  },

  startAutoRefresh() {
    this.stopAutoRefresh();
    this.autoRefreshTimer = setInterval(() => {
      if (window.App?.activeTab === "logs") {
        this.loadLogs(false);
      }
    }, 5000);
  },

  stopAutoRefresh() {
    if (this.autoRefreshTimer) {
      clearInterval(this.autoRefreshTimer);
      this.autoRefreshTimer = null;
    }
  },

  toggleAutoRefresh(enabled) {
    if (enabled) this.startAutoRefresh();
    else this.stopAutoRefresh();
  },

  setCategory(category) {
    this.currentCategory = category || "all";
    this.currentPage = 1;
    document.querySelectorAll(".log-chip").forEach((chip) => {
      chip.classList.toggle("active", chip.dataset.category === this.currentCategory);
    });
    this.loadLogs(true);
  },

  handleSearch(value) {
    clearTimeout(this.searchDebounceTimer);
    this.searchDebounceTimer = setTimeout(() => {
      this.searchQuery = (value || "").trim();
      this.currentPage = 1;
      this.loadLogs(false);
    }, 220);
  },

  changePageSize(newSize) {
    this.pageSize = Number(newSize) || 25;
    this.currentPage = 1;
    this.loadLogs(true);
  },

  goToPage(page) {
    const maxPage = Math.max(1, Math.ceil(this.totalRecords / this.pageSize));
    if (page < 1 || page > maxPage) return;
    this.currentPage = page;
    this.loadLogs(true);
  },

  getCategoryBadge(cat) {
    const low = (cat || "").toLowerCase();
    const map = {
      console: { label: "Consola", bg: "rgba(188, 140, 255, 0.14)", color: "#d2a8ff", border: "rgba(188, 140, 255, 0.35)" },
      consola: { label: "Consola", bg: "rgba(188, 140, 255, 0.14)", color: "#d2a8ff", border: "rgba(188, 140, 255, 0.35)" },
      server: { label: "Servidor", bg: "rgba(63, 185, 80, 0.14)", color: "#7ee787", border: "rgba(63, 185, 80, 0.35)" },
      servidor: { label: "Servidor", bg: "rgba(63, 185, 80, 0.14)", color: "#7ee787", border: "rgba(63, 185, 80, 0.35)" },
      player: { label: "Jugadores", bg: "rgba(167, 139, 250, 0.14)", color: "#c4b5fd", border: "rgba(167, 139, 250, 0.35)" },
      jugadores: { label: "Jugadores", bg: "rgba(167, 139, 250, 0.14)", color: "#c4b5fd", border: "rgba(167, 139, 250, 0.35)" },
      update: { label: "Mods / Update", bg: "rgba(45, 212, 191, 0.14)", color: "#5eead4", border: "rgba(45, 212, 191, 0.35)" },
      mods: { label: "Mods / Update", bg: "rgba(45, 212, 191, 0.14)", color: "#5eead4", border: "rgba(45, 212, 191, 0.35)" },
      actualización: { label: "Mods / Update", bg: "rgba(45, 212, 191, 0.14)", color: "#5eead4", border: "rgba(45, 212, 191, 0.35)" },
      backup: { label: "Respaldos", bg: "rgba(88, 166, 255, 0.14)", color: "#79c0ff", border: "rgba(88, 166, 255, 0.35)" },
      backups: { label: "Respaldos", bg: "rgba(88, 166, 255, 0.14)", color: "#79c0ff", border: "rgba(88, 166, 255, 0.35)" },
      tasks: { label: "Tareas", bg: "rgba(210, 153, 34, 0.14)", color: "#f2cc60", border: "rgba(210, 153, 34, 0.35)" },
      tareas: { label: "Tareas", bg: "rgba(210, 153, 34, 0.14)", color: "#f2cc60", border: "rgba(210, 153, 34, 0.35)" },
      security: { label: "Seguridad", bg: "rgba(248, 81, 73, 0.14)", color: "#ff7b72", border: "rgba(248, 81, 73, 0.35)" },
      seguridad: { label: "Seguridad", bg: "rgba(248, 81, 73, 0.14)", color: "#ff7b72", border: "rgba(248, 81, 73, 0.35)" },
      file: { label: "Archivos", bg: "rgba(139, 148, 158, 0.15)", color: "#c9d1d9", border: "rgba(139, 148, 158, 0.35)" },
      archivos: { label: "Archivos", bg: "rgba(139, 148, 158, 0.15)", color: "#c9d1d9", border: "rgba(139, 148, 158, 0.35)" },
      settings: { label: "Configuración", bg: "rgba(56, 189, 248, 0.14)", color: "#7dd3fc", border: "rgba(56, 189, 248, 0.35)" },
      configuración: { label: "Configuración", bg: "rgba(56, 189, 248, 0.14)", color: "#7dd3fc", border: "rgba(56, 189, 248, 0.35)" },
      webhooks: { label: "Webhooks", bg: "rgba(114, 137, 218, 0.15)", color: "#a5b4fc", border: "rgba(114, 137, 218, 0.35)" },
    };
    const cfg = map[low] || { label: cat || "Sistema", bg: "rgba(139, 148, 158, 0.15)", color: "#c9d1d9", border: "rgba(139, 148, 158, 0.35)" };
    return `<span class="badge" style="background:${cfg.bg};color:${cfg.color};border:1px solid ${cfg.border};font-size:0.74rem;padding:2px 8px;">${_logsEscapeHtml(cfg.label)}</span>`;
  },

  async loadLogs(showSpinner = false) {
    const tbody = document.getElementById("logs-table-body");
    const emptyState = document.getElementById("logs-empty-state");
    if (!tbody) return;

    if (showSpinner && tbody.innerHTML === "") {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-dim);">Cargando registros...</td></tr>';
    }

    const offset = (this.currentPage - 1) * this.pageSize;
    const params = new URLSearchParams({
      limit: String(this.pageSize),
      offset: String(offset),
    });
    if (this.currentCategory && this.currentCategory !== "all") {
      params.set("category", this.currentCategory);
    }
    if (this.searchQuery) {
      params.set("search", this.searchQuery);
    }

    try {
      const res = await fetch("/api/activity/logs?" + params.toString());
      const data = await window.readApiJson(res);
      if (!res.ok) return;

      this.totalRecords = Number(data.total || 0);
      const counts = data.counts || {};
      const totalAll = Number(counts.all ?? this.totalRecords);
      const consoleCount = Number(counts.console || 0);
      const systemCount = Math.max(0, totalAll - consoleCount);

      const elTotal = document.getElementById("logs-total-count");
      const elCmds = document.getElementById("logs-commands-count");
      const elSys = document.getElementById("logs-system-count");
      if (elTotal) elTotal.textContent = `${totalAll} registros`;
      if (elCmds) elCmds.textContent = `${consoleCount} comandos`;
      if (elSys) elSys.textContent = `${systemCount} eventos`;

      const rows = data.logs || [];
      if (!rows.length) {
        tbody.innerHTML = "";
        if (emptyState) emptyState.style.display = "block";
      } else {
        if (emptyState) emptyState.style.display = "none";
        tbody.innerHTML = rows.map((row) => {
          const ts = row.timestamp || (row.created_at ? new Date(row.created_at * 1000).toLocaleString("es-ES") : "-");
          const st = (row.status || "success").toLowerCase();
          const stBadge = st === "error"
            ? '<span class="badge badge-danger" style="font-size:0.72rem;">Error</span>'
            : (st === "warning"
              ? '<span class="badge badge-warning" style="font-size:0.72rem;">Aviso</span>'
              : '<span class="badge badge-success" style="font-size:0.72rem;">OK</span>');
          const detail = row.detail || row.details || row.message || "";
          return `
            <tr>
              <td style="font-family:var(--font-mono);font-size:0.78rem;color:var(--text-dim);">${_logsEscapeHtml(ts)}</td>
              <td>${this.getCategoryBadge(row.category)}</td>
              <td style="font-family:var(--font-mono);font-size:0.78rem;color:var(--text-muted);">${_logsEscapeHtml(row.action || row.category || "-")}</td>
              <td style="font-size:0.84rem;color:var(--text-color);word-break:break-word;">${_logsEscapeHtml(detail)}</td>
              <td style="font-size:0.8rem;color:var(--text-muted);">${_logsEscapeHtml(row.user || "Sistema")}</td>
              <td style="text-align:center;">${stBadge}</td>
            </tr>
          `;
        }).join("");
      }

      this.renderPagination();
    } catch (e) {
      console.error("Error cargando logs:", e);
    }
  },

  renderPagination() {
    const infoEl = document.getElementById("logs-pagination-info");
    const ctrlEl = document.getElementById("logs-pagination-controls");
    const maxPage = Math.max(1, Math.ceil(this.totalRecords / this.pageSize));
    const start = this.totalRecords === 0 ? 0 : ((this.currentPage - 1) * this.pageSize) + 1;
    const end = Math.min(this.totalRecords, this.currentPage * this.pageSize);

    if (infoEl) {
      infoEl.textContent = `Mostrando ${start}-${end} de ${this.totalRecords} registros`;
    }
    if (!ctrlEl) return;

    if (maxPage <= 1) {
      ctrlEl.innerHTML = "";
      return;
    }

    ctrlEl.innerHTML = `
      <button type="button" class="btn btn-outline btn-sm" ${this.currentPage <= 1 ? "disabled" : ""} onclick="Logs.goToPage(${this.currentPage - 1})">Anterior</button>
      <span style="padding:0 8px;">Página ${this.currentPage} / ${maxPage}</span>
      <button type="button" class="btn btn-outline btn-sm" ${this.currentPage >= maxPage ? "disabled" : ""} onclick="Logs.goToPage(${this.currentPage + 1})">Siguiente</button>
    `;
  },

  exportLogs(format = "csv") {
    const a = document.createElement("a");
    a.href = "/api/activity/export?format=" + encodeURIComponent(format);
    a.download = `pz_activity_log.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  },

  async clearLogs() {
    const ok = await App.confirm(
      "Vaciar historial de auditoría",
      "¿Estás seguro de eliminar permanentemente todos los registros de actividad?",
      true
    );
    if (!ok) return;

    try {
      const res = await fetch("/api/activity/clear", { method: "POST" });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo vaciar el historial", "error");
        return;
      }
      App.showToast("Historial de auditoría vaciado", "success");
      this.currentPage = 1;
      this.loadLogs(true);
    } catch (e) {
      App.showToast("Error vaciando historial: " + e.message, "error");
    }
  },
};

document.addEventListener("DOMContentLoaded", () => Logs.init());
window.Logs = Logs;
