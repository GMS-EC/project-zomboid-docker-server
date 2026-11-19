// Gestión Multi-Canal de Webhooks (Discord, Telegram y Correo SMTP)
const Webhooks = {
  config: null,
  currentModalChannel: null,

  init() {
    if (this._initialized) return;
    this._initialized = true;

    document.querySelectorAll('#tab-webhooks input[id^="webhook-event-"]').forEach((el) => {
      el.addEventListener('change', () => this.saveEvents());
    });
  },

  async loadConfig() {
    try {
      const res = await fetch('/api/webhooks/config');
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error cargando configuración de webhooks');
      this.config = data;
      this.populateUI(this.config);
    } catch (err) {
      App.showToast(err.message, 'danger');
    }
  },

  populateUI(cfg) {
    if (!cfg) return;

    const langEl = document.getElementById('webhook-lang');
    if (langEl && cfg.language) langEl.value = cfg.language;

    const discord = cfg.discord || {};
    const dEn = document.getElementById('webhook-discord-enable');
    const dUrl = document.getElementById('webhook-discord-url');
    if (dEn) dEn.checked = !!discord.enabled;
    if (dUrl) dUrl.value = discord.webhook_url || '';

    const tg = cfg.telegram || {};
    const tgEn = document.getElementById('webhook-telegram-enable');
    const tgTok = document.getElementById('webhook-telegram-token');
    const tgChat = document.getElementById('webhook-telegram-chatid');
    if (tgEn) tgEn.checked = !!tg.enabled;
    if (tgTok) tgTok.value = tg.bot_token || '';
    if (tgChat) tgChat.value = tg.chat_id || '';

    const em = cfg.email || {};
    const emEn = document.getElementById('webhook-email-enable');
    const emHost = document.getElementById('webhook-email-host');
    const emPort = document.getElementById('webhook-email-port');
    const emUser = document.getElementById('webhook-email-user');
    const emPass = document.getElementById('webhook-email-pass');
    const emTls = document.getElementById('webhook-email-tls');
    const emFrom = document.getElementById('webhook-email-from');
    const emTo = document.getElementById('webhook-email-to');
    if (emEn) emEn.checked = !!em.enabled;
    if (emHost) emHost.value = em.smtp_host || '';
    if (emPort) emPort.value = em.smtp_port || 587;
    if (emUser) emUser.value = em.smtp_user || '';
    if (emPass) emPass.value = em.smtp_password || '';
    if (emTls) emTls.checked = em.smtp_use_tls !== false;
    if (emFrom) emFrom.value = em.from_email || '';
    if (emTo) emTo.value = em.to_emails || '';

    const ev = cfg.events || {};
    const map = {
      'webhook-event-start': ev.server_start !== false,
      'webhook-event-starting': ev.starting !== false,
      'webhook-event-stop': ev.server_stop !== false,
      'webhook-event-crash': ev.server_crash !== false,
      'webhook-event-backup': ev.backup_created !== false,
      'webhook-event-save': ev.save !== false,
      'webhook-event-restart': ev.restart !== false,
      'webhook-event-shutdown-warn': ev.shutdown_warn !== false,
      'webhook-event-player': !!ev.player_join,
      'webhook-event-player-leave': !!ev.player_leave
    };
    Object.entries(map).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.checked = !!val;
    });

    this.updateStatusBadges();
  },

  updateStatusBadges() {
    if (!this.config) return;

    const dUrl = (this.config.discord?.webhook_url || '').trim();
    const dBadge = document.getElementById('webhook-discord-status');
    const dText = document.getElementById('webhook-discord-status-text');
    if (dBadge && dText) {
      dBadge.className = dUrl ? 'webhook-status-badge configured' : 'webhook-status-badge unconfigured';
      dText.textContent = dUrl ? 'URL Configurada' : 'Sin configurar';
    }

    const tgTok = (this.config.telegram?.bot_token || '').trim();
    const tgChat = (this.config.telegram?.chat_id || '').trim();
    const tgBadge = document.getElementById('webhook-telegram-status');
    const tgText = document.getElementById('webhook-telegram-status-text');
    if (tgBadge && tgText) {
      const ok = !!(tgTok && tgChat);
      tgBadge.className = ok ? 'webhook-status-badge configured' : 'webhook-status-badge unconfigured';
      tgText.textContent = ok ? `Chat ${tgChat}` : 'Sin configurar';
    }

    const emHost = (this.config.email?.smtp_host || '').trim();
    const emTo = (this.config.email?.to_emails || '').trim();
    const emBadge = document.getElementById('webhook-email-status');
    const emText = document.getElementById('webhook-email-status-text');
    if (emBadge && emText) {
      const ok = !!(emHost && emTo);
      emBadge.className = ok ? 'webhook-status-badge configured' : 'webhook-status-badge unconfigured';
      emText.textContent = ok ? emHost : 'Sin configurar';
    }
  },

  openChannelsModal() {
    document.getElementById('webhooks-channels-modal')?.classList.add('open');
  },

  closeChannelsModal() {
    document.getElementById('webhooks-channels-modal')?.classList.remove('open');
  },

  openModal(channel) {
    this.currentModalChannel = channel;
    const modal = document.getElementById('webhook-config-modal');
    const secDiscord = document.getElementById('modal-section-discord');
    const secTg = document.getElementById('modal-section-telegram');
    const secEmail = document.getElementById('modal-section-email');

    if (secDiscord) secDiscord.style.display = channel === 'discord' ? 'block' : 'none';
    if (secTg) secTg.style.display = channel === 'telegram' ? 'block' : 'none';
    if (secEmail) secEmail.style.display = channel === 'email' ? 'block' : 'none';

    const titleEl = document.getElementById('webhook-modal-title');
    const titles = { discord: 'Configurar Discord', telegram: 'Configurar Telegram', email: 'Configurar Correo SMTP' };
    if (titleEl) titleEl.textContent = titles[channel] || 'Configurar Canal';

    const testBtn = document.getElementById('webhook-modal-test-btn');
    if (testBtn) testBtn.textContent = `Probar ${channel.toUpperCase()}`;

    modal?.classList.add('open');
  },

  closeModal() {
    document.getElementById('webhook-config-modal')?.classList.remove('open');
    this.currentModalChannel = null;
  },

  async toggleChannel(channel, isEnabled) {
    if (!this.config) this.config = {};
    if (!this.config[channel]) this.config[channel] = {};
    this.config[channel].enabled = isEnabled;

    try {
      const res = await fetch('/api/webhooks/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [channel]: { enabled: isEnabled } })
      });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error actualizando canal');
      this.config = data.config || this.config;
      App.showToast(`${channel.toUpperCase()} ${isEnabled ? 'activado' : 'pausado'}.`, 'info');
    } catch (err) {
      App.showToast(err.message, 'danger');
    }
  },

  _collectEvents() {
    return {
      server_start: document.getElementById('webhook-event-start')?.checked || false,
      starting: document.getElementById('webhook-event-starting')?.checked || false,
      server_stop: document.getElementById('webhook-event-stop')?.checked || false,
      server_crash: document.getElementById('webhook-event-crash')?.checked || false,
      backup_created: document.getElementById('webhook-event-backup')?.checked || false,
      save: document.getElementById('webhook-event-save')?.checked || false,
      restart: document.getElementById('webhook-event-restart')?.checked || false,
      shutdown_warn: document.getElementById('webhook-event-shutdown-warn')?.checked || false,
      player_join: document.getElementById('webhook-event-player')?.checked || false,
      player_leave: document.getElementById('webhook-event-player-leave')?.checked || false
    };
  },

  async saveEvents() {
    const events = this._collectEvents();
    try {
      const res = await fetch('/api/webhooks/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events })
      });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error guardando eventos');
      this.config = data.config || { ...(this.config || {}), events };
      App.showToast('Eventos actualizados.', 'success');
    } catch (err) {
      App.showToast(err.message, 'danger');
    }
  },

  async saveConfig() {
    const payload = {
      language: document.getElementById('webhook-lang')?.value || 'es',
      discord: {
        enabled: document.getElementById('webhook-discord-enable')?.checked || false,
        webhook_url: (document.getElementById('webhook-discord-url')?.value || '').trim()
      },
      telegram: {
        enabled: document.getElementById('webhook-telegram-enable')?.checked || false,
        bot_token: (document.getElementById('webhook-telegram-token')?.value || '').trim(),
        chat_id: (document.getElementById('webhook-telegram-chatid')?.value || '').trim()
      },
      email: {
        enabled: document.getElementById('webhook-email-enable')?.checked || false,
        smtp_host: (document.getElementById('webhook-email-host')?.value || '').trim(),
        smtp_port: parseInt(document.getElementById('webhook-email-port')?.value || '587', 10) || 587,
        smtp_user: (document.getElementById('webhook-email-user')?.value || '').trim(),
        smtp_password: document.getElementById('webhook-email-pass')?.value || '',
        smtp_use_tls: document.getElementById('webhook-email-tls')?.checked !== false,
        from_email: (document.getElementById('webhook-email-from')?.value || '').trim(),
        to_emails: (document.getElementById('webhook-email-to')?.value || '').trim()
      },
      events: this._collectEvents()
    };

    try {
      const res = await fetch('/api/webhooks/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || 'Error guardando configuración');
      this.config = data.config || payload;
      this.updateStatusBadges();
      App.showToast('Configuración de webhooks guardada.', 'success');
      return true;
    } catch (err) {
      App.showToast(err.message, 'danger');
      return false;
    }
  },

  async saveFromModal() {
    if (await this.saveConfig()) {
      this.closeModal();
    }
  },

  async testCurrentModalChannel() {
    if (this.currentModalChannel) {
      await this.testChannel(this.currentModalChannel);
    }
  },

  async testChannel(channel) {
    const btn = document.getElementById(`btn-test-${channel}`);
    const modalBtn = document.getElementById('webhook-modal-test-btn');
    if (btn) btn.disabled = true;
    if (modalBtn) modalBtn.disabled = true;

    try {
      await this.saveConfig();
      App.showToast(`Enviando prueba a ${channel.toUpperCase()}...`, 'info');
      const res = await fetch(`/api/webhooks/test/${encodeURIComponent(channel)}`, { method: 'POST' });
      const data = await window.readApiJson(res);
      if (!res.ok) throw new Error(data.detail || `Error enviando prueba a ${channel}`);
      App.showToast(data.message || 'Notificación de prueba enviada.', 'success');
    } catch (err) {
      App.showToast(err.message, 'danger');
    } finally {
      if (btn) btn.disabled = false;
      if (modalBtn) modalBtn.disabled = false;
    }
  }
};

document.addEventListener('DOMContentLoaded', () => Webhooks.init());
window.Webhooks = Webhooks;
