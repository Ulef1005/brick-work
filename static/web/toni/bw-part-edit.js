/* #401 · The set page's part list: edit mode (tick the parts that are missing, one Save), the Set is checked switch, and the receipt line with Undo.
   The ticks live in a small model keyed by the part line's id, never in the row nodes, so they survive paging, sorting and collapsing a section.
   Nothing is sent until Save missing; Cancel drops every tick. Writes go through /collection/save/mark-missing and /set-checked. */
(() => {
  'use strict';
  const clamp = (value, need) => Math.min(Math.max(1, Math.floor(Number(value)) || 1), Math.max(1, Math.floor(Number(need)) || 1));
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const summary = (parts, pieces) => plural(parts, 'part', 'parts') + ' · ' + plural(pieces, 'piece', 'pieces') + ' marked missing';
  /* rows: [{id, need, missing, section}]. A line opens ticked at the count it already has missing; a new tick starts at 1 (or the count it had). */
  function createModel(rows) {
    const lines = new Map(rows.map(r => [r.id, {id: r.id, need: r.need, section: r.section || '', start: r.missing > 0 ? clamp(r.missing, r.need) : 0}]));
    lines.forEach(line => { line.count = line.start; });
    const all = () => [...lines.values()];
    return {
      count: id => lines.get(id)?.count || 0,
      isOn: id => (lines.get(id)?.count || 0) > 0,
      tick(id) {
        const line = lines.get(id);
        if (!line) return;
        line.count = line.count > 0 ? 0 : (line.start || 1);
      },
      step(id, delta) {
        const line = lines.get(id);
        if (line && line.count > 0) line.count = clamp(line.count + delta, line.need);
      },
      reset() { all().forEach(line => { line.count = line.start; }); },
      totals() {
        const on = all().filter(line => line.count > 0);
        return {parts: on.length, pieces: on.reduce((sum, line) => sum + line.count, 0)};
      },
      section: name => all().filter(line => line.section === name && line.count > 0).length,
      dirty: () => all().some(line => line.count !== line.start),
      /* What Save sends: a line whose tick or count changed. A cleared line goes back to 0 missing. */
      payload: () => all().filter(line => line.count !== line.start).map(line => ({id: line.id, missing: line.count})),
    };
  }
  /* The screen a receipt belongs to: the path plus the query parts that choose the copy, stock row or colour (as bw-collection.js reads it, #236). */
  const screenOf = loc => {
    const id = ['copy', 'stock', 'colour'].map(k => { const m = new RegExp('[?&]' + k + '=([^&#]+)').exec(loc.search || ''); return m && k + '=' + m[1]; }).filter(Boolean).join('&');
    return id ? loc.pathname + '?' + id : loc.pathname;
  };
  window.BrickPartEdit = {clamp, createModel, summary, screenOf};

  const root = document.querySelector('#bw-collection');
  if (!root) return;
  const module = root.querySelector('[data-bc-pl]');
  if (!module) return;
  const receiptKey = 'bw-collection-receipt';
  const find = selector => module.querySelector(selector);
  const progress = find('[data-bc-pl-progress]'), mode = find('[data-bc-pl-mode]'), bar = find('[data-bc-pl-bar]'),
    sum = find('[data-bc-pl-sum]'), save = find('[data-bc-pl-save]'), warn = find('[data-bc-pl-warn]'), warnText = find('[data-bc-pl-warn-text]'),
    edit = find('[data-bc-pl-edit]'), cancel = find('[data-bc-pl-cancel]'), receipt = find('[data-bc-pl-receipt]'),
    receiptText = find('[data-bc-pl-receipt-text]'), undo = find('[data-bc-pl-undo]'), checked = find('[data-bc-pl-checked]'),
    rule = find('[data-bc-pl-rule]'), switchNote = find('[data-bc-pl-switch-note]');
  const rowEls = [...module.querySelectorAll('[data-bc-pl-row]')];
  const sectionEls = [...module.querySelectorAll('[data-bc-part-section]')];
  const model = createModel(rowEls.map(el => ({
    id: Number(el.dataset.bcPlRow), need: Number(el.dataset.bcPlNeed), missing: Number(el.dataset.bcPlMissing),
    section: el.closest('[data-bc-part-section]')?.dataset.bcPartSection || '',
  })));
  let editing = false, busy = false;
  const store = fn => { try { return fn(sessionStorage); } catch (_) { return null; } };

  const paint = () => {
    rowEls.forEach(el => {
      const id = Number(el.dataset.bcPlRow), on = model.isOn(id), count = model.count(id), need = Number(el.dataset.bcPlNeed);
      el.dataset.bcPlOn = String(on);
      el.querySelector('[data-bc-pl-box]')?.setAttribute('aria-checked', String(on));
      const line = el.querySelector('[data-bc-pl-line]');
      if (line) line.hidden = !on;
      const output = el.querySelector('[data-bc-pl-count]');
      if (output) output.textContent = String(on ? count : 1);
      el.querySelectorAll('[data-bc-pl-step]').forEach(b => { b.disabled = !on || (Number(b.dataset.bcPlStep) < 0 && count <= 1) || (Number(b.dataset.bcPlStep) > 0 && count >= need); });
    });
    sectionEls.forEach(el => {
      const tag = el.querySelector('[data-bc-pl-ticked]');
      if (!tag) return;
      const n = model.section(el.dataset.bcPartSection);
      tag.textContent = n + ' ticked';
      tag.hidden = !editing || n === 0;
    });
    const totals = model.totals();
    if (sum) sum.textContent = summary(totals.parts, totals.pieces);
    if (save) save.disabled = busy || !model.dirty();
  };

  const setMode = on => {
    editing = on;
    if (on) module.setAttribute('data-bc-pl-editing', ''); else module.removeAttribute('data-bc-pl-editing');
    if (progress) progress.hidden = on;
    if (mode) mode.hidden = !on;
    if (bar) bar.hidden = !on;
    if (warn) warn.hidden = true;
    if (save) save.textContent = 'Save missing';
    if (edit) edit.setAttribute('aria-expanded', String(on));
    paint();
  };

  edit?.addEventListener('click', () => { model.reset(); setMode(true); cancel?.focus?.(); });
  cancel?.addEventListener('click', () => { if (busy) return; model.reset(); setMode(false); edit?.focus?.(); });

  rowEls.forEach(el => {
    const id = Number(el.dataset.bcPlRow);
    el.querySelector('[data-bc-pl-box]')?.addEventListener('click', () => { if (editing && !busy) { model.tick(id); paint(); } });
    el.querySelectorAll('[data-bc-pl-step]').forEach(b => b.addEventListener('click', () => { if (editing && !busy) { model.step(id, Number(b.dataset.bcPlStep)); paint(); } }));
    el.querySelector('.bc-pl-stepper')?.addEventListener('keydown', event => {
      const delta = {ArrowUp: 1, ArrowRight: 1, '+': 1, '=': 1, ArrowDown: -1, ArrowLeft: -1, '-': -1}[event.key];
      if (delta && editing && !busy) { event.preventDefault(); model.step(id, delta); paint(); }
    });
  });

  const post = async (action, data) => {
    let response;
    try {
      response = await fetch(root.dataset.saveUrl.replace('ACTION', action), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...data, csrf_token: root.dataset.csrf})});
    } catch (_) {
      throw Object.assign(new Error('The connection dropped'), {offline: true});
    }
    let result = {};
    try { result = await response.json(); } catch (_) { /* a non-JSON answer is a failure below */ }
    if (!response.ok) throw new Error(result.message || 'The server refused it');
    return result;
  };
  const remember = result => store(s => s.setItem(receiptKey, JSON.stringify({...result, screen: screenOf(location)})));

  save?.addEventListener('click', async () => {
    if (busy || !model.dirty()) return;
    busy = true;
    if (warn) warn.hidden = true;
    paint();
    try {
      const result = await post('mark-missing', {copy_id: module.dataset.copy, rows: model.payload()});
      remember(result);
      location.reload();
    } catch (error) {
      busy = false;
      if (warnText) warnText.textContent = error.message.replace(/\.?$/, '.') + ' Your ticks are kept; press Retry.';
      if (warn) warn.hidden = false;
      if (save) save.textContent = 'Retry';
      paint();
    }
  });

  /* The receipt line: shown from the stored receipt after a reload; Undo is the page's own Undo (bw-collection.js), which undoes and reloads. */
  const showReceipt = (text, onUndo) => {
    if (!receipt) return;
    if (receiptText) receiptText.textContent = text;
    receipt.hidden = false;
    receipt.undoNow = onUndo || null;
  };
  const stored = store(s => JSON.parse(s.getItem(receiptKey) || 'null'));
  if (stored && stored.message) showReceipt(stored.message);
  undo?.addEventListener('click', () => {
    if (receipt?.undoNow) return receipt.undoNow();
    root.querySelector('[data-bc-undo]')?.click();
  });

  /* Set is checked: the person's own switch. It saves at once; outside edit mode the page reloads so the pills follow, inside edit mode it
     updates in place so the ticks are not lost, and its Undo flips it back in place. */
  const paintChecked = on => {
    checked?.setAttribute('aria-checked', String(on));
    if (rule) {
      const gap = rule.dataset.gap ? Number(rule.dataset.gap) : 0;
      const base = 'Complete needs Set is checked and nothing missing.';
      rule.textContent = on && gap ? 'Stays Incomplete while ' + plural(gap, 'part is', 'parts are') + ' missing. ' + base : base;
    }
  };
  checked?.addEventListener('click', async () => {
    if (busy) return;
    const wanted = checked.getAttribute('aria-checked') !== 'true';
    busy = true;
    checked.disabled = true;
    if (switchNote) switchNote.textContent = '';
    try {
      const result = await post('set-checked', {copy_id: checked.dataset.copy, wanted});
      if (!editing) { remember(result); location.reload(); return; }
      paintChecked(wanted);
      showReceipt(result.message, async () => {
        try {
          await post('undo', {event_id: result.event_id});
          paintChecked(!wanted);
          if (receipt) receipt.hidden = true;
        } catch (error) { if (switchNote) switchNote.textContent = error.message; }
      });
    } catch (error) {
      if (switchNote) switchNote.textContent = error.message;
    } finally {
      busy = false;
      checked.disabled = false;
      paint();
    }
  });
  paint();
})();
