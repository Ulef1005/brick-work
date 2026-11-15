/* #53 Sell this copy: the listing text preview. The text is made on the server and sits in the preview's field; this script copies it (the clipboard,
   else the selection copy of bw-tokens.js), shows Edited with Reset to generated once the words change, and opens Missing parts at 1024 and wider. */
(() => {
  'use strict';
  const WIDE = '(min-width: 1024px)';
  const COPIED = 'Copied', FAILED = 'Copy failed · select and copy by hand';

  // The selection copy for when the clipboard is not available: a field the size of nothing holds the text for the browser's copy command.
  function selectionCopy(text, doc) {
    const field = doc.createElement('textarea');
    field.value = text; field.setAttribute('readonly', ''); field.style.position = 'fixed'; field.style.opacity = '0';
    doc.body.appendChild(field); field.select();
    let ok = false;
    try { ok = !!(doc.execCommand && doc.execCommand('copy')); } catch { ok = false; }
    field.remove();
    return ok;
  }

  // True when the text reached the clipboard. `copyText` is bw-tokens.js's (clipboard first, then the fallback).
  async function copyListing(text, env) {
    const copyText = env.copyText || (async (value, clipboard, fallback) => {
      try { if (clipboard && clipboard.writeText) { await clipboard.writeText(value); return true; } } catch { /* fall through */ }
      return fallback ? fallback() : false;
    });
    return !!(await copyText(text, env.clipboard, () => selectionCopy(text, env.document)));
  }

  function wire(section, env) {
    const field = section.querySelector('[data-bc-sell-text]');
    if (!field) return;
    const sheet = section.querySelector('[data-bc-sell-sheet]');
    const edited = section.querySelector('[data-bc-sell-edited]');
    const reset = section.querySelector('[data-bc-sell-reset]');
    const statuses = [...section.querySelectorAll('[data-bc-sell-status]')];
    const inSheet = el => !!(sheet && sheet.contains && sheet.contains(el));
    const say = (button, text) => { const s = statuses.find(x => inSheet(x) === inSheet(button)) || statuses[0]; if (s) s.textContent = text; };
    const clear = () => statuses.forEach(s => { s.textContent = ''; });
    const generated = field.defaultValue;
    const refresh = () => { const changed = field.value !== generated; if (edited) edited.hidden = !changed; clear(); };
    field.addEventListener('input', refresh);
    if (reset) reset.addEventListener('click', () => { field.value = generated; refresh(); });
    section.querySelectorAll('[data-bc-sell-copy]').forEach(button => button.addEventListener('click', async () => {
      if (button.disabled) return;
      const ok = await copyListing(field.value, env);
      if (ok) { clear(); say(button, COPIED); return; }
      // Copy failed: the preview opens with the text selected, so it can be copied by hand.
      if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
      field.focus(); field.select();
      clear();
      const status = statuses.find(inSheet) || statuses[0];
      if (status) status.textContent = FAILED;
    }));
    if (env.matchMedia && env.matchMedia(WIDE).matches) { const first = section.querySelector('[data-bc-sell-dis]'); if (first) first.open = true; }
  }

  const env = typeof window === 'undefined' ? null : {
    document: window.document, clipboard: window.navigator && window.navigator.clipboard, matchMedia: window.matchMedia && window.matchMedia.bind(window),
    get copyText() { return window.BrickTokenCopy; }
  };
  if (typeof window !== 'undefined') {
    window.BrickSell = {copyListing, selectionCopy, wire};
    if (window.document && window.document.addEventListener) {
      window.document.addEventListener('DOMContentLoaded', () => window.document.querySelectorAll('[data-bc-sell]').forEach(section => wire(section, env)));
    }
  }
})();
