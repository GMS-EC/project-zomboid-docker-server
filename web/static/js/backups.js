// Gestión de Respaldos y Políticas (Dockraft Port adaptado a Project Zomboid)
const Backups = {
  backupsList: [],
  policiesList: [],
  selectedScope: 'full',
  configScope: 'full',
  configTargets: [],
  availableTargets: null,
  originFilter: 'all',
  maxBackupsCount: 10,
  isCreatingBackup: false,
  currentStage: 'idle',
  activeJobId: null,
  handledJobIds: new Set(),
  progressPollTimer: null,
  _isPollingStatus: false,
  _pollErrorCount: 0,

  init() {
    if (this._initialized) return;
    this._initialized = true;
    this.loadBackups();
  },

  async loadBackups() {
    await Promise.all([
      this.fetchBackupConfig(),
      this.fetchBackupsList(),
      this.checkBackupStatus()
    ]);
  },

  setOriginFilter(filter) {
    this.originFilter = ['auto', 'manual'].includes(filter) ? filter : 'all';
    document.querySelectorAll('.backups-filter-pill').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-filter') === this.originFilter);
    });
    this.renderBackupsTable();
  },

  updateSummaryBadges() {
    const totalCountEl = document.getElementById('backups-total-count');
    const policyEl = document.getElementById('backups-policy-summary');
    if (totalCountEl) {
      const count = this.backupsList.length;
      totalCountEl.textContent = this.maxBackupsCount > 0
        ? `${count} / ${this.maxBackupsCount}`
        : `${count} copias`;
    }
    if (policyEl) {
      const n = this.maxBackupsCount || 10;
      policyEl.textContent = n === 1 ? `Máx. ${n} copia` : `Máx. ${n} copias`;
    }
  },

  async fetchBackupsList() {
    const tableBody = document.getElementById('backups-table-body');
    const totalSizeEl = document.getElementById('backups-total-size');
    if (!tableBody) return;

    try {
      const res = await fetch('/api/backups/list');
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error al obtener la lista de backups');
      this.backupsList = Array.isArray(data) ? data : (data.backups || []);

      const totalBytes = this.backupsList.reduce((acc, b) => acc + (b.size_bytes || 0), 0);
      if (totalSizeEl) totalSizeEl.textContent = this.formatBytes(totalBytes);
      this.updateSummaryBadges();
      this.renderBackupsTable();
    } catch (err) {
      console.error(err);
      if (!this.backupsList || this.backupsList.length === 0) {
        this.renderBackupsTable(err.message);
      }
      App.showToast(err.message, 'danger');
    }
  },

  renderBackupsTable(errorMsg = '') {
    const tableBody = document.getElementById('backups-table-body');
    const emptyState = document.getElementById('backups-empty-state');
    if (!tableBody) return;
    const tableEl = tableBody.closest('table');

    const list = Array.isArray(this.backupsList) ? this.backupsList : [];
    const filtered = list.filter(b => {
      if (this.originFilter === 'auto') return !!b.is_auto || b.origin === 'auto';
      if (this.originFilter === 'manual') return !(b.is_auto || b.origin === 'auto');
      return true;
    });

    tableBody.innerHTML = '';
    if (errorMsg || filtered.length === 0) {
      if (tableEl) tableEl.style.display = 'none';
      if (emptyState) emptyState.style.display = 'block';
      return;
    }

    if (tableEl) tableEl.style.display = '';
    if (emptyState) emptyState.style.display = 'none';

    filtered.forEach(b => {
      const tr = document.createElement('tr');
      const isAuto = !!b.is_auto || b.origin === 'auto';
      const originBadge = isAuto
        ? '<span class="badge-origin badge-origin-auto">Automático</span>'
        : '<span class="badge-origin badge-origin-manual">Manual</span>';

      const scope = b.scope || 'full';
      const scopeBadges = {
        world: '<span class="badge-scope badge-scope-world">Solo Mundo</span>',
        config: '<span class="badge-scope badge-scope-config">Config / DB</span>',
        custom: '<span class="badge-scope badge-scope-custom">Personalizado</span>',
        full: '<span class="badge-scope badge-scope-full">Completo</span>',
      };
      const scopeBadge = scopeBadges[scope] || scopeBadges.full;
      const sizeStr = b.size_formatted || (b.size_mb !== undefined ? `${b.size_mb} MB` : '--');

      tr.innerHTML = `
        <td>
          <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; font-family: var(--font-mono); font-size: 0.86rem; color: var(--text-main);">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>
            ${this.escapeHtml(b.filename)}
          </div>
        </td>
        <td>${originBadge}</td>
        <td>${scopeBadge}</td>
        <td style="color: var(--text-dim); font-size: 0.84rem;">${this.escapeHtml(b.created_at || '--')}</td>
        <td style="font-family: var(--font-mono); font-size: 0.84rem; color: var(--text-muted);">${this.escapeHtml(sizeStr)}</td>
        <td style="text-align: right;">
          <div style="display: inline-flex; gap: 6px;">
            <a href="/api/backups/download/${encodeURIComponent(b.filename)}" class="btn btn-outline" style="padding: 4px 10px; font-size: 0.8rem; display: inline-flex; align-items: center; gap: 4px;" download>
              Descargar
            </a>
            <button type="button" class="btn btn-warning" style="padding: 4px 10px; font-size: 0.8rem;" data-action="restore">
              Restaurar
            </button>
            <button type="button" class="btn btn-danger" style="padding: 4px 10px; font-size: 0.8rem;" data-action="delete" title="Eliminar copia">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </div>
        </td>
      `;

      tr.querySelector('[data-action="restore"]')?.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.restoreBackup(b.filename);
      });
      tr.querySelector('[data-action="delete"]')?.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.deleteBackup(b.filename);
      });
      tableBody.appendChild(tr);
    });
  },

  openConfigModal(policyId = null) {
    const policy = policyId ? this.policiesList.find(p => p.id === policyId) : null;
    if (!policy && this.policiesList.length >= 4) {
      App.showToast('Solo puedes crear hasta 4 políticas de respaldo.', 'warning');
      return;
    }

    const modal = document.getElementById('modal-backup-config');
    if (!modal) return;

    const titleEl = document.getElementById('backup-policy-modal-title');
    const idInput = document.getElementById('backup-policy-id');
    const nameInput = document.getElementById('backup-policy-name');
    const compToggle = document.getElementById('backup-config-compression');
    const stopToggle = document.getElementById('backup-config-stop');
    const preCmdInput = document.getElementById('backup-config-pre-cmd');
    const postCmdInput = document.getElementById('backup-config-post-cmd');
    const delBtn = document.getElementById('btn-delete-policy-modal');

    if (policy) {
      if (titleEl) titleEl.textContent = 'Editar Política de Respaldo';
      if (idInput) idInput.value = policy.id;
      if (nameInput) nameInput.value = policy.name || '';
      if (compToggle) compToggle.checked = policy.compression !== false;
      if (stopToggle) stopToggle.checked = !!policy.stop_server;
      if (preCmdInput) preCmdInput.value = policy.pre_command || '';
      if (postCmdInput) postCmdInput.value = policy.post_command || '';
      if (delBtn) delBtn.style.display = this.policiesList.length > 1 ? 'inline-flex' : 'none';
      this.configTargets = Array.isArray(policy.targets) ? policy.targets : [];
      this.selectConfigScope(policy.scope || 'full');
    } else {
      if (titleEl) titleEl.textContent = 'Nueva Política de Respaldo';
      if (idInput) idInput.value = '';
      if (nameInput) nameInput.value = '';
      if (compToggle) compToggle.checked = true;
      if (stopToggle) stopToggle.checked = false;
      if (preCmdInput) preCmdInput.value = '';
      if (postCmdInput) postCmdInput.value = '';
      if (delBtn) delBtn.style.display = 'none';
      this.configTargets = [];
      this.selectConfigScope('full');
    }

    modal.classList.add('open');
  },

  openRetentionModal() {
    const input = document.getElementById('backup-retention-max');
    if (input) input.value = this.maxBackupsCount || 10;
    document.getElementById('modal-backup-retention')?.classList.add('open');
  },

  closeRetentionModal() {
    document.getElementById('modal-backup-retention')?.classList.remove('open');
  },

  async saveRetentionMax() {
    const input = document.getElementById('backup-retention-max');
    const maxCount = Math.max(1, Math.min(100, parseInt(input?.value || '10', 10) || 10));
    try {
      const res = await fetch('/api/backups/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          backup_max_count: maxCount,
          backup_scope: this.configScope || 'full',
          backup_targets: this.configTargets || [],
          backup_compression: this.configCompression !== false,
          backup_stop_server: !!this.configStopServer,
          backup_pre_command: this.configPreCommand || ''
        })
      });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error guardando límite global');
      this.maxBackupsCount = maxCount;
      this.updateSummaryBadges();
      this.closeRetentionModal();
      await this.fetchBackupsList();
      App.showToast(`Rotación global actualizada a máximo ${maxCount} copias.`, 'success');
    } catch (err) {
      App.showToast(err.message, 'danger');
    }
  },

  async deleteCurrentPolicy() {
    const pid = document.getElementById('backup-policy-id')?.value.trim() || '';
    const pname = document.getElementById('backup-policy-name')?.value.trim() || '';
    if (!pid) return;
    if (await this.deletePolicy(pid, pname)) {
      this.closeConfigModal();
    }
  },

  renderPoliciesList() {
    const container = document.getElementById('backups-policies-list');
    const newBtn = document.getElementById('btn-new-policy');
    if (newBtn) {
      newBtn.style.display = (this.policiesList || []).length >= 4 ? 'none' : 'inline-flex';
    }
    if (!container) return;
    container.innerHTML = '';

    if (!this.policiesList || this.policiesList.length === 0) {
      container.innerHTML = '<div style="color: var(--text-dim); font-size: 0.84rem;">No hay políticas configuradas.</div>';
      return;
    }

    const scopeLabels = {
      full: 'Servidor Completo',
      world: 'Solo Mundo',
      config: 'Config y DB',
      custom: 'Personalizado',
    };

    this.policiesList.forEach(p => {
      const card = document.createElement('div');
      card.className = 'backup-policy-card';

      const scopeText = p.scope === 'custom'
        ? `Personalizado (${(p.targets || []).length} elementos)`
        : (scopeLabels[p.scope] || 'Servidor Completo');

      const flags = [];
      flags.push(p.compression !== false ? 'Comprimido (.tar.gz)' : 'Sin compresión (rápido)');
      if (p.stop_server) flags.push('Apaga servidor');
      if (p.pre_command) flags.push(`Pre: ${p.pre_command}`);
      if (p.post_command) flags.push(`Post: ${p.post_command}`);

      card.innerHTML = `
        <div class="backup-policy-card-header">
          <div style="min-width: 0;">
            <div class="backup-policy-name">${this.escapeHtml(p.name)}</div>
            <div class="backup-policy-scope">${this.escapeHtml(scopeText)}</div>
          </div>
          <button type="button" class="action-icon-btn" data-action="edit-policy" title="Editar política">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
        </div>
        <div class="backup-policy-flags">${flags.map(f => `<span class="backup-policy-flag">${this.escapeHtml(f)}</span>`).join('')}</div>
      `;

      card.querySelector('[data-action="edit-policy"]')?.addEventListener('click', () => this.openConfigModal(p.id));
      container.appendChild(card);
    });
  },

  async deletePolicy(policyId, policyName) {
    const ok = await App.confirm({
      title: 'Eliminar Política de Respaldo',
      message: `¿Eliminar la política '${policyName}'?`,
      confirmText: 'Eliminar',
      danger: true
    });
    if (!ok) return false;

    try {
      const res = await fetch(`/api/backups/policies/${encodeURIComponent(policyId)}`, { method: 'DELETE' });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error eliminando política');
      this.policiesList = data.policies || [];
      this.renderPoliciesList();
      this.updateSummaryBadges();
      App.showToast('Política eliminada correctamente.', 'success');
      return true;
    } catch (err) {
      App.showToast(err.message, 'danger');
      return false;
    }
  },

  closeConfigModal() {
    document.getElementById('modal-backup-config')?.classList.remove('open');
  },

  _stageLabel(stage) {
    const map = {
      preparing: 'Preparando copia de seguridad...',
      saving: 'Guardando mundo antes del respaldo...',
      stopping: 'Deteniendo servidor para respaldo...',
      compressing: 'Comprimiendo archivos del servidor...',
      pruning: 'Aplicando rotación de copias...',
      restarting: 'Reiniciando servidor...'
    };
    return map[stage] || map.compressing;
  },

  _setProgressVisible(visible, stage = 'compressing') {
    this.isCreatingBackup = !!visible;
    this.currentStage = visible ? (stage || 'compressing') : 'idle';

    const progBox = document.getElementById('backup-progress-box');
    const progLabel = document.getElementById('backup-progress-label');
    const createBtn = document.getElementById('btn-create-backup');

    if (progLabel && visible) progLabel.textContent = this._stageLabel(this.currentStage);
    if (progBox) progBox.style.display = visible ? 'block' : 'none';
    if (createBtn) createBtn.disabled = !!visible;
  },

  startProgressPolling() {
    if (this.progressPollTimer) return;
    this._pollErrorCount = 0;
    this.progressPollTimer = setInterval(() => this.checkBackupStatus(), 1500);
  },

  stopProgressPolling() {
    if (this.progressPollTimer) {
      clearInterval(this.progressPollTimer);
      this.progressPollTimer = null;
    }
    this._pollErrorCount = 0;
  },

  async checkBackupStatus() {
    if (this._isPollingStatus) return;
    this._isPollingStatus = true;
    try {
      const res = await fetch('/api/backups/status');
      const st = await window.readApiJson(res);
      this._pollErrorCount = 0;

      if (st && st.is_running) {
        if (st.job_id) this.activeJobId = st.job_id;
        this._setProgressVisible(true, st.stage || 'compressing');
        this.startProgressPolling();
        return;
      }

      const jobId = st && st.job_id;
      const matchesTracked = !!(jobId && this.activeJobId === jobId && !this.handledJobIds.has(jobId));

      this.stopProgressPolling();
      this._setProgressVisible(false);

      if (matchesTracked) {
        this.handledJobIds.add(jobId);
        this.activeJobId = null;
        if (st.status === 'completed') {
          App.showToast(`Copia creada: ${st.filename || ''} (${st.size_formatted || ''})`, 'success');
          await this.fetchBackupsList();
        } else if (st.status === 'error') {
          App.showToast(st.error || 'Error al crear la copia de seguridad', 'danger');
        }
      }
    } catch (err) {
      this._pollErrorCount = (this._pollErrorCount || 0) + 1;
      if (this.progressPollTimer && this._pollErrorCount >= 5) {
        this.stopProgressPolling();
        this._setProgressVisible(false);
      }
    } finally {
      this._isPollingStatus = false;
    }
  },

  openCreateModal() {
    if (this.isCreatingBackup) {
      App.showToast('Ya hay una copia de seguridad en progreso.', 'info');
      return;
    }
    const modal = document.getElementById('modal-create-backup');
    if (modal) {
      modal.classList.add('open');
      this.selectScope('full');
      const nameInput = document.getElementById('backup-modal-tag');
      if (nameInput) nameInput.value = '';

      const compModal = document.getElementById('backup-modal-compression');
      if (compModal) compModal.checked = this.configCompression !== undefined ? this.configCompression : true;

      const stopModal = document.getElementById('backup-modal-stop');
      if (stopModal) stopModal.checked = !!this.configStopServer;

      const preCmdModal = document.getElementById('backup-modal-pre-cmd');
      if (preCmdModal) preCmdModal.value = this.configPreCommand || '';

      const postCmdModal = document.getElementById('backup-modal-post-cmd');
      if (postCmdModal) postCmdModal.value = this.configPostCommand || '';
    }
  },

  closeCreateModal() {
    document.getElementById('modal-create-backup')?.classList.remove('open');
  },

  selectScope(scope) {
    const cleanScope = ['full', 'world', 'config', 'custom'].includes(scope) ? scope : 'full';
    this.selectedScope = cleanScope;
    document.querySelectorAll('#modal-create-backup .backup-scope-card').forEach(c => {
      c.classList.toggle('selected', c.getAttribute('data-scope') === cleanScope);
    });

    const customBox = document.getElementById('backup-custom-targets-box');
    if (cleanScope === 'custom') {
      if (customBox) customBox.style.display = 'block';
      this.loadTargets();
    } else if (customBox) {
      customBox.style.display = 'none';
    }
  },

  selectConfigScope(scope) {
    const cleanScope = ['full', 'world', 'config', 'custom'].includes(scope) ? scope : 'full';
    this.configScope = cleanScope;
    document.querySelectorAll('.backup-cfg-scope-card').forEach(c => {
      c.classList.toggle('selected', c.getAttribute('data-scope') === cleanScope);
    });

    const customBox = document.getElementById('backup-cfg-custom-targets-box');
    if (cleanScope === 'custom') {
      if (customBox) customBox.style.display = 'block';
      this.loadConfigTargets();
    } else if (customBox) {
      customBox.style.display = 'none';
    }
  },

  async loadConfigTargets() {
    const container = document.getElementById('backup-cfg-targets-list');
    if (!container) return;

    if (!this.availableTargets) {
      container.innerHTML = '<div style="color: var(--text-dim); font-size: 0.82rem; padding: 12px; text-align: center;">Analizando carpetas de Zomboid...</div>';
      try {
        const res = await fetch('/api/backups/targets');
        if (res.ok) this.availableTargets = await window.readApiJson(res);
      } catch (e) {}
    }

    container.innerHTML = '';
    if (!this.availableTargets || this.availableTargets.length === 0) {
      container.innerHTML = '<div style="color: var(--text-dim); font-size: 0.82rem; padding: 12px; text-align: center;">No hay carpetas disponibles todavía.</div>';
      return;
    }

    const savedTargets = Array.isArray(this.configTargets) ? this.configTargets : [];
    this.availableTargets.forEach(target => {
      const item = document.createElement('div');
      item.className = 'backup-target-item';
      const isChecked = savedTargets.length > 0
        ? savedTargets.includes(target.name)
        : (target.category === 'world' || target.category === 'config');
      const sid = this.escapeHtml(target.name);
      item.innerHTML = `
        <label class="backup-target-label" for="cfg-target-cb-${sid}">
          <input type="checkbox" id="cfg-target-cb-${sid}" class="backup-cfg-target-cb" value="${sid}" ${isChecked ? 'checked' : ''}>
          <span style="font-family: var(--font-mono);">${sid}</span>
        </label>
        <span class="backup-target-size">${this.escapeHtml(target.size_formatted || '0 B')}</span>
      `;
      container.appendChild(item);
    });
  },

  toggleAllConfigTargets(check) {
    document.querySelectorAll('.backup-cfg-target-cb').forEach(cb => { cb.checked = !!check; });
  },

  async loadTargets() {
    const container = document.getElementById('backup-targets-list');
    if (!container) return;

    container.innerHTML = '<div style="color: var(--text-dim); font-size: 0.82rem; padding: 12px; text-align: center;">Analizando carpetas de Zomboid...</div>';
    try {
      const res = await fetch('/api/backups/targets');
      const targets = await window.readApiJson(res);
      this.availableTargets = Array.isArray(targets) ? targets : [];
      container.innerHTML = '';

      if (!this.availableTargets.length) {
        container.innerHTML = '<div style="color: var(--text-dim); font-size: 0.82rem; padding: 12px; text-align: center;">No hay carpetas disponibles todavía.</div>';
        return;
      }

      this.availableTargets.forEach(target => {
        const item = document.createElement('div');
        item.className = 'backup-target-item';
        const sid = this.escapeHtml(target.name);
        const defChecked = target.category === 'world' || target.category === 'config';
        item.innerHTML = `
          <label class="backup-target-label" for="target-cb-${sid}">
            <input type="checkbox" id="target-cb-${sid}" class="backup-target-cb" value="${sid}" ${defChecked ? 'checked' : ''}>
            <span style="font-family: var(--font-mono);">${sid}</span>
          </label>
          <span class="backup-target-size">${this.escapeHtml(target.size_formatted || '0 B')}</span>
        `;
        container.appendChild(item);
      });
    } catch (err) {
      container.innerHTML = `<div style="color: #f85149; font-size: 0.82rem; padding: 8px;">Error cargando elementos: ${this.escapeHtml(err.message)}</div>`;
    }
  },

  toggleAllTargets(check) {
    document.querySelectorAll('.backup-target-cb').forEach(cb => { cb.checked = !!check; });
  },

  async submitCreateBackup() {
    if (this.isCreatingBackup) {
      App.showToast('Ya hay una copia de seguridad en progreso.', 'info');
      return;
    }

    const customName = document.getElementById('backup-modal-tag')?.value.trim() || '';
    const compression = document.getElementById('backup-modal-compression')?.checked !== false;
    const stopServer = !!document.getElementById('backup-modal-stop')?.checked;
    const preCommand = document.getElementById('backup-modal-pre-cmd')?.value.trim() || '';
    const postCommand = document.getElementById('backup-modal-post-cmd')?.value.trim() || '';

    let selectedTargets = null;
    if (this.selectedScope === 'custom') {
      selectedTargets = Array.from(document.querySelectorAll('.backup-target-cb:checked')).map(cb => cb.value);
      if (!selectedTargets.length) {
        App.showToast('Selecciona al menos una carpeta o archivo para respaldar.', 'warning');
        return;
      }
    }

    const btn = document.getElementById('btn-modal-submit-backup');
    if (btn) btn.disabled = true;

    try {
      const res = await fetch('/api/backups/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: customName || null,
          tag: customName || 'manual',
          scope: this.selectedScope,
          targets: selectedTargets,
          compression,
          stop_server: stopServer,
          pre_command: preCommand,
          post_command: postCommand,
          background: true
        })
      });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error al crear la copia de seguridad');

      if (data && data.status === 'started') {
        this.activeJobId = data.job_id || 'active';
        this.closeCreateModal();
        this._setProgressVisible(true, (data.progress && data.progress.stage) || 'preparing');
        App.showToast('Creando respaldo en segundo plano...', 'info');
        this.startProgressPolling();
      } else {
        this.closeCreateModal();
        App.showToast('Copia de seguridad creada con éxito.', 'success');
        await this.fetchBackupsList();
      }
    } catch (err) {
      App.showToast(err.message, 'danger');
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async restoreBackup(filename) {
    const ok = await App.confirm({
      title: 'Restaurar Copia de Seguridad',
      message: `¿Restaurar '${filename}'?\nEl servidor debe estar apagado y los archivos actuales serán reemplazados.`,
      confirmText: 'Restaurar',
      warning: true
    });
    if (!ok) return;

    try {
      App.showToast('Restaurando copia de seguridad...', 'info');
      const res = await fetch('/api/backups/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename })
      });
      const data = await window.readApiJson(res);
      if (data.success || data.status === 'success') {
        App.showToast('Copia de seguridad restaurada correctamente.', 'success');
      } else {
        App.showToast(data.error || data.detail || 'No se pudo restaurar la copia', 'danger');
      }
    } catch (err) {
      App.showToast(err.message, 'danger');
    }
  },

  async deleteBackup(filename) {
    const ok = await App.confirm({
      title: 'Eliminar Copia de Seguridad',
      message: `¿Eliminar permanentemente '${filename}'?`,
      confirmText: 'Eliminar',
      danger: true
    });
    if (!ok) return;

    try {
      const res = await fetch(`/api/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      const data = await window.readApiJson(res);
      if (!res.ok || data.success === false) {
        throw new Error(data.detail || data.error || 'Error al eliminar copia');
      }
      this.backupsList = (this.backupsList || []).filter(b => b.filename !== filename);
      this.updateSummaryBadges();
      this.renderBackupsTable();
      App.showToast('Copia de seguridad eliminada', 'success');
      await this.fetchBackupsList();
    } catch (err) {
      App.showToast(err.message, 'danger');
    }
  },

  async fetchBackupConfig() {
    try {
      const res = await fetch('/api/backups/policies');
      if (!res.ok) return;
      const data = await window.readApiJson(res);

      this.maxBackupsCount = parseInt(data.max_count || 10, 10) || 10;
      this.policiesList = Array.isArray(data.policies) ? data.policies : [];

      const primary = this.policiesList[0] || {};
      this.configCompression = primary.compression !== false;
      this.configStopServer = !!primary.stop_server;
      this.configPreCommand = primary.pre_command || '';
      this.configPostCommand = primary.post_command || '';
      this.configScope = primary.scope || 'full';
      this.configTargets = Array.isArray(primary.targets) ? primary.targets : [];

      this.renderPoliciesList();
      this.updateSummaryBadges();
    } catch (err) {}
  },

  async saveBackupConfig() {
    const idInput = document.getElementById('backup-policy-id');
    const nameInput = document.getElementById('backup-policy-name');
    const compToggle = document.getElementById('backup-config-compression');
    const stopToggle = document.getElementById('backup-config-stop');
    const preCmdInput = document.getElementById('backup-config-pre-cmd');
    const postCmdInput = document.getElementById('backup-config-post-cmd');

    const policyName = (nameInput ? nameInput.value.trim() : '') || '';
    if (!policyName) {
      App.showToast('Ingresa un nombre para la política de respaldo', 'warning');
      if (nameInput) nameInput.focus();
      return;
    }

    let selectedTargets = [];
    if (this.configScope === 'custom') {
      selectedTargets = Array.from(document.querySelectorAll('.backup-cfg-target-cb:checked')).map(cb => cb.value);
      if (!selectedTargets.length) {
        App.showToast('Selecciona al menos una carpeta o archivo para respaldar', 'warning');
        return;
      }
    }

    const payload = {
      id: (idInput && idInput.value.trim()) ? idInput.value.trim() : null,
      name: policyName,
      scope: this.configScope || 'full',
      targets: selectedTargets,
      compression: compToggle ? compToggle.checked : true,
      stop_server: stopToggle ? stopToggle.checked : false,
      pre_command: preCmdInput ? preCmdInput.value.trim() : '',
      post_command: postCmdInput ? postCmdInput.value.trim() : ''
    };

    try {
      const res = await fetch('/api/backups/policies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error guardando política');

      this.maxBackupsCount = data.max_count || this.maxBackupsCount || 10;
      this.policiesList = Array.isArray(data.policies) ? data.policies : [];
      this.renderPoliciesList();
      this.updateSummaryBadges();
      this.closeConfigModal();
      await this.fetchBackupsList();
      App.showToast('Política de respaldo guardada.', 'success');
    } catch (err) {
      App.showToast(err.message, 'danger');
    }
  },

  formatBytes(bytes) {
    return window.formatBytes ? window.formatBytes(bytes) : `${bytes} B`;
  },

  escapeHtml(str) {
    return window.escapeHtml ? window.escapeHtml(str) : String(str || '');
  }
};

document.addEventListener('DOMContentLoaded', () => Backups.init());
window.Backups = Backups;
