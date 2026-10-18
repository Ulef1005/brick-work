/* Import progress panel. Attach to a channel with on(), off(), emit() and connected; the pages supply a polling channel. */
(() => {
 'use strict';
 class BrickImportProgress {
  constructor(root, socket, {jobId = root.dataset.importJob, retry} = {}) {
   this.root = root;
   this.socket = socket;
   this.jobId = String(jobId);
   this.retryAction = retry;
   this.bar = root.querySelector('[data-import-bar]');
   this.fill = root.querySelector('[data-import-fill]');
   this.message = root.querySelector('[data-import-message]');
   this.button = root.querySelector('[data-import-retry]');
   this.failed = new Map();
   this.pending = false;
   this.listener = payload => this.update(payload);
   this.click = () => this.retry();
   this.connection = () => this.syncButton();
   socket.on('import_progress', this.listener);
   socket.on('connect', this.connection);
   socket.on('disconnect', this.connection);
   this.button.addEventListener('click', this.click);
  }
  syncButton() {
   this.button.hidden = this.failed.size === 0;
   this.button.disabled = !this.socket.connected || this.pending;
  }
  update(data) {
   if (!data || String(data.job_id) !== this.jobId) return;
   if (data.step == null && data.state === 'done') this.failed.clear();
   if (data.step && data.state === 'failed') this.failed.set(data.step, data);
   if (data.step && (data.state === 'started' || data.state === 'done')) this.failed.delete(data.step);
   if (['failed', 'waiting', 'done'].includes(data.state)) this.pending = false;
   const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
   const totalSteps = number(data.total_steps);
   const completed = number(data.completed_steps);
   const fraction = ['progress','waiting','started'].includes(data.state) && number(data.total) ? Math.min(1, number(data.count) / number(data.total)) : 0;
   const percent = totalSteps ? Math.min(100, 100 * (completed + fraction) / totalSteps) : 0;
   this.fill.style.width = `${percent}%`;
   this.bar.setAttribute('aria-valuenow', String(percent));
   this.message.textContent = data.message || 'Waiting to import';
   this.syncButton();
  }
  retry() {
   if (!this.socket.connected || this.pending || !this.failed.size) return;
   const step = this.failed.keys().next().value;
   this.pending = true;
   this.syncButton();
   // The page provides a retry callback backed by its authenticated write route.
   const sent = this.retryAction ? this.retryAction(Number(this.jobId), step) :
    this.socket.emit('import_retry', {job_id: Number(this.jobId), step});
   if (sent === false) { this.pending = false; this.syncButton(); }
  }
  destroy() {
   this.socket.off('import_progress', this.listener);
   this.socket.off('connect', this.connection);
   this.socket.off('disconnect', this.connection);
   this.button.removeEventListener('click', this.click);
  }
 }
 window.BrickImportProgress = BrickImportProgress;
})();
