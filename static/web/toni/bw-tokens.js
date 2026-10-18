/* Manage 12m · API tokens. Dialogs open from the same links the server renders; Copy never stores the token. */
(() => {
 'use strict';
 function revokeTitle(name) { return `Revoke ${name}?`; }
 async function copyText(text, clipboard, fallback) {
  try {
   if (clipboard && clipboard.writeText) { await clipboard.writeText(text); return true; }
  } catch { /* fall through to the selection copy */ }
  return fallback ? fallback() : false;
 }
 window.BrickTokenRevokeTitle = revokeTitle;
 window.BrickTokenCopy = copyText;
 document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('[data-tokens]');
  if (!root) return;
  const open = dialog => { if (!dialog) return; if (dialog.open) dialog.close(); dialog.showModal(); };
  const base = root.dataset.base;
  const create = root.querySelector('[data-token-create]');
  const confirm = root.querySelector('[data-token-confirm]');
  const shown = root.querySelector('[data-token-shown]');
  // The secret page is the create POST's response: replace it so Back cannot bring the secret back.
  const leaveShown = () => { root.querySelectorAll('[data-token-value]').forEach(el => { el.textContent = ''; }); window.location.replace(base); };
  window.addEventListener('pageshow', event => { if (event.persisted && shown) leaveShown(); });
  for (const dialog of [create, confirm, shown]) {
   if (!dialog) continue;
   dialog.addEventListener('cancel', event => { if (dialog === shown) event.preventDefault(); });
   dialog.querySelectorAll('[data-token-close]').forEach(el => el.addEventListener('click', event => {
    if (el.tagName === 'A') event.preventDefault();
    if (dialog === shown) { leaveShown(); return; }
    dialog.close();
    if (window.history && window.history.replaceState) window.history.replaceState(null, '', base);
   }));
  }
  root.querySelectorAll('[data-token-create-open]').forEach(el => el.addEventListener('click', event => { event.preventDefault(); open(create); create.querySelector('input[name=name]').focus(); }));
  root.querySelectorAll('[data-token-revoke]').forEach(el => el.addEventListener('click', event => {
   event.preventDefault();
   confirm.querySelector('[data-token-confirm-title]').textContent = revokeTitle(el.dataset.name);
   confirm.querySelector('input[name=id]').value = el.dataset.tokenRevoke;
   open(confirm);
  }));
  for (const dialog of [create, confirm, shown]) { if (dialog && dialog.hasAttribute('open')) { dialog.removeAttribute('open'); dialog.showModal(); } }
  const copy = root.querySelector('[data-token-copy]');
  if (copy) {
   const value = root.querySelector('[data-token-value]');
   copy.addEventListener('click', async () => {
    const select = () => { const range = document.createRange(); range.selectNodeContents(value); const s = window.getSelection(); s.removeAllRanges(); s.addRange(range); return document.execCommand && document.execCommand('copy'); };
    const ok = await copyText(value.textContent.trim(), navigator.clipboard, select);
    copy.textContent = ok ? 'Copied' : 'Select and copy';
    if (!ok) select();
   });
  }
 });
})();
