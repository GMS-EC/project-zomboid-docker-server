/* ==========================================================================
   Gestor de Archivos (/Zomboid) - Basado en Dockraft Workbench adaptado a PZ
   ========================================================================== */

const _filesEscapeHtml = (str) => (window.escapeHtml ? window.escapeHtml(str) : String(str ?? ""));
const _filesJsStr = (str) => _filesEscapeHtml(JSON.stringify(String(str ?? "")));

const Files = {
  currentPath: "",
  currentEditingFile: null,
  currentItems: [],
  searchQuery: "",
  selectedPaths: new Set(),
  renameTarget: null,
  uploadQueue: [],
  isUploading: false,
  uploadBatchRefreshNeeded: false,
  isUploadWidgetCollapsed: false,
  uploadSeqCounter: 0,

  init() {
    document.addEventListener("click", (e) => {
      const menu = document.getElementById("file-context-menu");
      if (menu && menu.style.display === "block" && !menu.contains(e.target) && !e.target.closest(".btn-row-context")) {
        this.hideContextMenu();
      }
    });

    const card = document.getElementById("file-manager-card");
    const overlay = document.getElementById("file-drop-overlay");
    if (card && overlay) {
      let dragCounter = 0;

      card.addEventListener("dragenter", (e) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter++;
        const targetText = document.getElementById("file-dropzone-target-text");
        if (targetText) {
          targetText.textContent = "Se guardarán en: " + (this.currentPath ? "/Zomboid/" + this.currentPath : "/Zomboid");
        }
        overlay.style.display = "flex";
      });

      card.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.stopPropagation();
      });

      card.addEventListener("dragleave", (e) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter--;
        if (dragCounter <= 0) {
          dragCounter = 0;
          overlay.style.display = "none";
        }
      });

      card.addEventListener("drop", (e) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter = 0;
        overlay.style.display = "none";
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          this.handleUploadFiles(e.dataTransfer.files);
        }
      });
    }

    const editor = document.getElementById("editor-textarea");
    if (editor) {
      const updateStatus = () => {
        const val = editor.value || "";
        const charCountEl = document.getElementById("editor-char-count");
        if (charCountEl) charCountEl.textContent = val.length + " caracteres";
        const posEl = document.getElementById("editor-cursor-pos");
        if (posEl) {
          const textUpTo = val.slice(0, editor.selectionStart || 0);
          const lines = textUpTo.split("\n");
          posEl.textContent = `Línea ${lines.length}, Columna ${lines[lines.length - 1].length + 1}`;
        }
      };

      editor.addEventListener("input", updateStatus);
      editor.addEventListener("keyup", updateStatus);
      editor.addEventListener("click", updateStatus);
      editor.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
          e.preventDefault();
          this.saveCurrentFile();
        } else if (e.key === "Tab") {
          e.preventDefault();
          const start = editor.selectionStart;
          const end = editor.selectionEnd;
          editor.value = editor.value.substring(0, start) + "  " + editor.value.substring(end);
          editor.selectionStart = editor.selectionEnd = start + 2;
          updateStatus();
        }
      });
    }
  },

  async loadDirectory(path = "") {
    this.currentPath = path;
    this.clearSelection();
    const tbody = document.getElementById("files-table-body");
    if (tbody) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:32px; color:var(--text-dim);">Cargando directorio...</td></tr>';
    }

    try {
      const res = await fetch("/api/files/list?path=" + encodeURIComponent(path));
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo listar el directorio", "error");
        return;
      }
      this.currentPath = data.current_path ?? path;
      this.currentItems = data.items || [];
      this.renderBreadcrumbs(this.currentPath);
      this.renderItems(this.getFilteredItems());
    } catch (e) {
      App.showToast("Error cargando archivos: " + e.message, "error");
    }
  },

  renderBreadcrumbs(path) {
    const container = document.getElementById("file-breadcrumbs");
    if (!container) return;

    const parts = path ? path.split("/").filter(Boolean) : [];
    let html = `<button type="button" class="crumb-item" style="background:none;border:none;color:var(--accent-soft);cursor:pointer;font-weight:600;" onclick="Files.loadDirectory('')">/Zomboid</button>`;
    let acc = "";
    parts.forEach((p, idx) => {
      acc = acc ? `${acc}/${p}` : p;
      html += `<span style="color:var(--text-dim);margin:0 4px;">/</span>`;
      if (idx === parts.length - 1) {
        html += `<span class="crumb-item active" style="color:var(--text-color);font-weight:600;">${_filesEscapeHtml(p)}</span>`;
      } else {
        html += `<button type="button" class="crumb-item" style="background:none;border:none;color:var(--accent-soft);cursor:pointer;" onclick="Files.loadDirectory(${_filesJsStr(acc)})">${_filesEscapeHtml(p)}</button>`;
      }
    });
    container.innerHTML = html;
  },

  getFilteredItems() {
    const q = (this.searchQuery || "").trim().toLowerCase();
    if (!q) return this.currentItems;
    return this.currentItems.filter((item) => String(item.name || "").toLowerCase().includes(q));
  },

  filterFiles(query) {
    this.searchQuery = query || "";
    this.renderItems(this.getFilteredItems());
  },

  isEditableExt(ext) {
    const editable = new Set([
      "ini", "lua", "txt", "cfg", "conf", "json", "xml",
      "sh", "bat", "md", "log", "properties", "yml", "yaml", "csv",
    ]);
    return editable.has((ext || "").toLowerCase());
  },

  getFileIcon(name, isDir) {
    if (isDir) {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="rgba(227, 179, 65, 0.25)" stroke="#e3b341" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
    }
    const ext = (name.split(".").pop() || "").toLowerCase();
    if (ext === "lua") {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#79c0ff" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
    }
    if (ext === "ini" || ext === "cfg" || ext === "conf" || ext === "properties") {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7ee2b4" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
    }
    if (ext === "zip" || ext === "gz" || ext === "tar") {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f2cc60" stroke-width="2"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/></svg>';
    }
    if (ext === "db" || ext === "sqlite") {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#d2a8ff" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>';
    }
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
  },

  renderItems(items) {
    const tbody = document.getElementById("files-table-body");
    if (!tbody) return;

    const parts = [];
    if (this.currentPath && !this.searchQuery) {
      const parentPath = this.currentPath.split("/").slice(0, -1).join("/");
      parts.push(`
        <tr style="cursor:pointer;" onclick="Files.loadDirectory(${_filesJsStr(parentPath)})">
          <td></td>
          <td colspan="4" style="font-weight:600; color:var(--accent-soft);">
            <span style="display:inline-flex;align-items:center;gap:8px;">↩ .. (Carpeta superior)</span>
          </td>
        </tr>
      `);
    }

    if (!items || items.length === 0) {
      parts.push('<tr><td colspan="5" style="text-align:center; padding:32px; color:var(--text-dim);">Esta carpeta está vacía o no hay coincidencias.</td></tr>');
      tbody.innerHTML = parts.join("");
      return;
    }

    for (const item of items) {
      const relPath = this.currentPath ? `${this.currentPath}/${item.name}` : item.name;
      const checked = this.selectedPaths.has(relPath) ? "checked" : "";
      const modStr = item.modified ? new Date(item.modified * 1000).toLocaleString("es-ES") : "-";
      const sizeStr = item.is_dir ? "—" : window.formatBytes(item.size || 0);
      const isEditable = !item.is_dir && this.isEditableExt(item.extension);
      const isZip = !item.is_dir && (item.extension || "").toLowerCase() === "zip";

      const clickAction = item.is_dir
        ? `Files.loadDirectory(${_filesJsStr(relPath)})`
        : (isEditable ? `Files.openEditor(${_filesJsStr(relPath)})` : `Files.downloadFile(${_filesJsStr(relPath)})`);

      const actionBtns = [];
      if (isEditable) {
        actionBtns.push(`<button type="button" class="btn btn-outline btn-sm" style="padding:3px 8px;font-size:0.75rem;" onclick="Files.openEditor(${_filesJsStr(relPath)})">Editar</button>`);
      } else if (isZip) {
        actionBtns.push(`<button type="button" class="btn btn-outline btn-sm" style="padding:3px 8px;font-size:0.75rem;" onclick="Files.unzipFile(${_filesJsStr(relPath)})">Extraer</button>`);
      }
      if (!item.is_dir) {
        actionBtns.push(`<button type="button" class="btn btn-outline btn-sm" style="padding:3px 8px;font-size:0.75rem;" onclick="Files.downloadFile(${_filesJsStr(relPath)})" title="Descargar">⬇</button>`);
      }
      actionBtns.push(`<button type="button" class="btn btn-outline btn-sm btn-row-context" style="padding:3px 8px;font-size:0.75rem;" onclick="Files.showContextMenu(event, ${_filesJsStr(relPath)}, ${_filesJsStr(item.name)}, ${Boolean(item.is_dir)}, ${Boolean(isZip)})" title="Más acciones">⋮</button>`);

      parts.push(`
        <tr oncontextmenu="event.preventDefault(); Files.showContextMenu(event, ${_filesJsStr(relPath)}, ${_filesJsStr(item.name)}, ${Boolean(item.is_dir)}, ${Boolean(isZip)})">
          <td style="text-align:center;">
            <input type="checkbox" class="form-checkbox file-row-check" ${checked} onchange="Files.toggleSelect(${_filesJsStr(relPath)}, this.checked)">
          </td>
          <td>
            <div style="display:flex;align-items:center;gap:9px;cursor:pointer;" onclick="${clickAction}">
              ${this.getFileIcon(item.name, item.is_dir)}
              <span style="font-family:var(--font-mono);font-size:0.84rem;color:${item.is_dir ? "#e6edf3" : "var(--text-color)"};font-weight:${item.is_dir ? "600" : "400"};">${_filesEscapeHtml(item.name)}</span>
            </div>
          </td>
          <td style="font-family:var(--font-mono);font-size:0.78rem;color:var(--text-dim);">${_filesEscapeHtml(sizeStr)}</td>
          <td class="col-modified" style="font-size:0.78rem;color:var(--text-dim);">${_filesEscapeHtml(modStr)}</td>
          <td style="text-align:right;">
            <div style="display:inline-flex;gap:4px;align-items:center;">${actionBtns.join("")}</div>
          </td>
        </tr>
      `);
    }

    tbody.innerHTML = parts.join("");
  },

  showContextMenu(event, relPath, name, isDir, isZip) {
    event.stopPropagation();
    const menu = document.getElementById("file-context-menu");
    if (!menu) return;

    const items = [];
    if (!isDir && this.isEditableExt(name.split(".").pop())) {
      items.push(`<button type="button" class="context-item" onclick="Files.openEditor(${_filesJsStr(relPath)}); Files.hideContextMenu();">✏️ Editar contenido</button>`);
    }
    items.push(`<button type="button" class="context-item" onclick="Files.openRenameModal(${_filesJsStr(relPath)}, ${_filesJsStr(name)}); Files.hideContextMenu();">🏷️ Renombrar</button>`);
    items.push(`<button type="button" class="context-item" onclick="Files.duplicateItem(${_filesJsStr(relPath)}); Files.hideContextMenu();">📋 Duplicar</button>`);
    items.push(`<button type="button" class="context-item" onclick="Files.compressItem(${_filesJsStr(relPath)}); Files.hideContextMenu();">🗜️ Comprimir ZIP</button>`);
    if (isZip) {
      items.push(`<button type="button" class="context-item" onclick="Files.unzipFile(${_filesJsStr(relPath)}); Files.hideContextMenu();">📦 Extraer ZIP aquí</button>`);
    }
    if (!isDir) {
      items.push(`<button type="button" class="context-item" onclick="Files.downloadFile(${_filesJsStr(relPath)}); Files.hideContextMenu();">⬇️ Descargar</button>`);
    }
    items.push(`<div class="context-divider"></div>`);
    items.push(`<button type="button" class="context-item danger" onclick="Files.deleteItem(${_filesJsStr(relPath)}, ${Boolean(isDir)}); Files.hideContextMenu();">🗑️ Eliminar</button>`);

    menu.innerHTML = items.join("");
    menu.style.display = "block";

    const x = Math.min(event.clientX, window.innerWidth - 205);
    const y = Math.min(event.clientY, window.innerHeight - 240);
    menu.style.left = Math.max(8, x) + "px";
    menu.style.top = Math.max(8, y) + "px";
  },

  hideContextMenu() {
    const menu = document.getElementById("file-context-menu");
    if (menu) menu.style.display = "none";
  },

  toggleSelect(path, checked) {
    if (checked) this.selectedPaths.add(path);
    else this.selectedPaths.delete(path);
    this.updateBulkBar();
  },

  toggleSelectAll(checked) {
    const filtered = this.getFilteredItems();
    if (checked) {
      filtered.forEach((item) => {
        const rel = this.currentPath ? `${this.currentPath}/${item.name}` : item.name;
        this.selectedPaths.add(rel);
      });
    } else {
      this.selectedPaths.clear();
    }
    this.renderItems(filtered);
    this.updateBulkBar();
  },

  clearSelection() {
    this.selectedPaths.clear();
    const selAll = document.getElementById("file-select-all");
    if (selAll) selAll.checked = false;
    document.querySelectorAll(".file-row-check").forEach((cb) => { cb.checked = false; });
    this.updateBulkBar();
  },

  updateBulkBar() {
    const bar = document.getElementById("files-bulk-bar");
    const countEl = document.getElementById("bulk-selected-count");
    const n = this.selectedPaths.size;
    if (bar) bar.style.display = n > 0 ? "flex" : "none";
    if (countEl) countEl.textContent = `${n} seleccionado${n === 1 ? "" : "s"}`;
  },

  async openEditor(path) {
    try {
      const res = await fetch("/api/files/read?path=" + encodeURIComponent(path));
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo abrir el archivo", "error");
        return;
      }
      this.currentEditingFile = path;
      const titleEl = document.getElementById("editor-file-title");
      const area = document.getElementById("editor-textarea");
      const modal = document.getElementById("file-editor-modal");
      if (titleEl) titleEl.textContent = "Editando: /Zomboid/" + path;
      if (area) {
        area.value = data.content ?? "";
        const charCount = document.getElementById("editor-char-count");
        if (charCount) charCount.textContent = area.value.length + " caracteres";
      }
      if (modal) modal.classList.add("open");
    } catch (e) {
      App.showToast("Error leyendo archivo: " + e.message, "error");
    }
  },

  closeEditor() {
    document.getElementById("file-editor-modal")?.classList.remove("open");
    this.currentEditingFile = null;
  },

  async saveCurrentFile() {
    if (!this.currentEditingFile) return;
    const content = document.getElementById("editor-textarea")?.value ?? "";
    try {
      const res = await fetch("/api/files/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: this.currentEditingFile, content }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "Error guardando archivo", "error");
        return;
      }
      App.showToast("Archivo guardado correctamente", "success");
      this.closeEditor();
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error guardando archivo: " + e.message, "error");
    }
  },

  openCreateFileModal() {
    const input = document.getElementById("input-file-create-name");
    if (input) input.value = "";
    document.getElementById("modal-file-create")?.classList.add("open");
    setTimeout(() => input?.focus(), 60);
  },

  closeCreateFileModal() {
    document.getElementById("modal-file-create")?.classList.remove("open");
  },

  async submitCreateFile() {
    const name = document.getElementById("input-file-create-name")?.value.trim();
    if (!name) return;
    const relPath = this.currentPath ? `${this.currentPath}/${name}` : name;
    try {
      const res = await fetch("/api/files/create-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: relPath }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo crear el archivo", "error");
        return;
      }
      this.closeCreateFileModal();
      await this.loadDirectory(this.currentPath);
      this.openEditor(relPath);
    } catch (e) {
      App.showToast("Error creando archivo: " + e.message, "error");
    }
  },

  async createNewFolder() {
    const folderName = await App.prompt("Nueva Carpeta", "Introduce el nombre de la carpeta:", "");
    if (!folderName || !folderName.trim()) return;
    const relPath = this.currentPath ? `${this.currentPath}/${folderName.trim()}` : folderName.trim();
    try {
      const res = await fetch("/api/files/create-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: relPath }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo crear la carpeta", "error");
        return;
      }
      App.showToast("Carpeta creada correctamente", "success");
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error creando carpeta: " + e.message, "error");
    }
  },

  openRenameModal(path, currentName) {
    this.renameTarget = path;
    const input = document.getElementById("input-file-rename");
    if (input) input.value = currentName || "";
    document.getElementById("modal-file-rename")?.classList.add("open");
    setTimeout(() => input?.focus(), 60);
  },

  closeRenameModal() {
    document.getElementById("modal-file-rename")?.classList.remove("open");
    this.renameTarget = null;
  },

  async submitRename() {
    const newName = document.getElementById("input-file-rename")?.value.trim();
    if (!this.renameTarget || !newName) return;
    try {
      const res = await fetch("/api/files/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: this.renameTarget, new_name: newName }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo renombrar", "error");
        return;
      }
      App.showToast("Renombrado correctamente", "success");
      this.closeRenameModal();
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error al renombrar: " + e.message, "error");
    }
  },

  async duplicateItem(path) {
    try {
      const res = await fetch("/api/files/duplicate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo duplicar", "error");
        return;
      }
      App.showToast("Elemento duplicado: " + (data.new_name || ""), "success");
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error duplicando: " + e.message, "error");
    }
  },

  async compressItem(path) {
    try {
      App.showToast("Comprimiendo elemento...", "info");
      const res = await fetch("/api/files/compress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo comprimir", "error");
        return;
      }
      App.showToast("ZIP creado: " + (data.archive_name || ""), "success");
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error comprimiendo: " + e.message, "error");
    }
  },

  async unzipFile(path) {
    try {
      App.showToast("Extrayendo ZIP...", "info");
      const res = await fetch("/api/files/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, target_dir: this.currentPath }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo extraer", "error");
        return;
      }
      App.showToast("ZIP extraído correctamente", "success");
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error extrayendo ZIP: " + e.message, "error");
    }
  },

  downloadFile(path) {
    const a = document.createElement("a");
    a.href = "/api/files/download?path=" + encodeURIComponent(path);
    a.download = path.split("/").pop() || "archivo";
    document.body.appendChild(a);
    a.click();
    a.remove();
  },

  async deleteItem(path, isDir) {
    const confirmed = await App.confirm(
      "Eliminar elemento",
      `¿Eliminar ${isDir ? "la carpeta" : "el archivo"} "${path}"? Esta acción no se puede deshacer.`,
      true
    );
    if (!confirmed) return;
    try {
      const res = await fetch("/api/files/delete?path=" + encodeURIComponent(path), { method: "DELETE" });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "No se pudo eliminar", "error");
        return;
      }
      App.showToast("Eliminado correctamente", "success");
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error eliminando: " + e.message, "error");
    }
  },

  async bulkDelete() {
    const paths = Array.from(this.selectedPaths);
    if (!paths.length) return;
    const confirmed = await App.confirm(
      "Eliminación múltiple",
      `¿Eliminar ${paths.length} elementos seleccionados permanentemente?`,
      true
    );
    if (!confirmed) return;
    try {
      const res = await fetch("/api/files/bulk-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "Error en eliminación múltiple", "error");
        return;
      }
      App.showToast(`Se eliminaron ${data.deleted_count || 0} elementos.`, "success");
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error en eliminación múltiple: " + e.message, "error");
    }
  },

  async bulkCompress() {
    const paths = Array.from(this.selectedPaths);
    if (!paths.length) return;
    try {
      App.showToast("Comprimiendo selección...", "info");
      const res = await fetch("/api/files/bulk-compress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, target_dir: this.currentPath }),
      });
      const data = await window.readApiJson(res);
      if (!res.ok) {
        App.showToast(data.detail || "Error comprimiendo selección", "error");
        return;
      }
      App.showToast("Archivo comprimido: " + (data.archive_name || ""), "success");
      this.loadDirectory(this.currentPath);
    } catch (e) {
      App.showToast("Error comprimiendo: " + e.message, "error");
    }
  },

  handleUploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    for (const file of fileList) {
      this.uploadQueue.push({
        id: "up-" + (++this.uploadSeqCounter),
        file,
        name: file.name,
        targetDir: this.currentPath,
        progress: 0,
        status: "pending",
      });
    }
    this.uploadBatchRefreshNeeded = true;
    this.renderUploadWidget();
    if (!this.isUploading) this.processUploadQueue();
  },

  processUploadQueue() {
    const nextItem = this.uploadQueue.find((it) => it.status === "pending");
    if (!nextItem) {
      this.isUploading = false;
      this.renderUploadWidget();
      if (this.uploadBatchRefreshNeeded) {
        this.uploadBatchRefreshNeeded = false;
        this.loadDirectory(this.currentPath);
      }
      return;
    }

    this.isUploading = true;
    nextItem.status = "uploading";
    this.renderUploadWidget();

    const fd = new FormData();
    fd.append("path", nextItem.targetDir || "");
    fd.append("file", nextItem.file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/files/upload", true);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        nextItem.progress = Math.round((e.loaded / e.total) * 100);
        this.renderUploadWidget();
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        nextItem.status = "done";
        nextItem.progress = 100;
      } else {
        nextItem.status = "error";
      }
      this.renderUploadWidget();
      this.processUploadQueue();
    };

    xhr.onerror = () => {
      nextItem.status = "error";
      this.renderUploadWidget();
      this.processUploadQueue();
    };

    xhr.send(fd);
  },

  renderUploadWidget() {
    const widget = document.getElementById("file-upload-widget");
    const listEl = document.getElementById("file-upload-widget-list");
    const subtitle = document.getElementById("file-upload-widget-subtitle");
    const globalBar = document.getElementById("file-upload-global-bar");
    const footer = document.getElementById("file-upload-widget-footer");
    if (!widget || !listEl) return;

    if (!this.uploadQueue.length) {
      widget.style.display = "none";
      return;
    }

    widget.style.display = "block";
    const total = this.uploadQueue.length;
    const done = this.uploadQueue.filter((u) => u.status === "done").length;
    const avg = Math.round(this.uploadQueue.reduce((acc, u) => acc + u.progress, 0) / total);

    if (subtitle) subtitle.textContent = `${done}/${total} completados (${avg}%)`;
    if (globalBar) globalBar.style.width = `${avg}%`;
    if (footer) footer.style.display = done > 0 ? "flex" : "none";

    listEl.innerHTML = this.uploadQueue.map((u) => {
      const badgeColor = u.status === "done" ? "#3fb950" : (u.status === "error" ? "#f85149" : "#58a6ff");
      return `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;font-size:0.78rem;border-bottom:1px solid rgba(255,255,255,0.06);">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:190px;">${_filesEscapeHtml(u.name)}</span>
          <span style="color:${badgeColor};font-family:var(--font-mono);">${u.status === "done" ? "OK" : (u.status === "error" ? "Error" : u.progress + "%")}</span>
        </div>
      `;
    }).join("");
  },

  toggleUploadManagerCollapse() {
    this.isUploadWidgetCollapsed = !this.isUploadWidgetCollapsed;
    const body = document.getElementById("file-upload-widget-body");
    if (body) body.style.display = this.isUploadWidgetCollapsed ? "none" : "block";
  },

  clearCompletedUploads() {
    this.uploadQueue = this.uploadQueue.filter((u) => u.status === "pending" || u.status === "uploading");
    this.renderUploadWidget();
  },

  closeUploadManager() {
    this.uploadQueue = [];
    const widget = document.getElementById("file-upload-widget");
    if (widget) widget.style.display = "none";
  },
};

document.addEventListener("DOMContentLoaded", () => Files.init());
window.Files = Files;
