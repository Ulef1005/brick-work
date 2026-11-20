/* Production subset of approved admin.js: theme and native dialog only.
   Native showModal provides focus containment and Escape; restore the opener.
   The navigation (top bar, sub row, tab bar) is plain links since #492: nothing here opens a group sheet. */
(() => {
 const selectors = [...document.querySelectorAll('[data-theme-selector]')];
 selectors.forEach(selector => {
  selector.value = window.adminTheme.mode;
  selector.addEventListener('change', () => {
   window.adminTheme.apply(selector.value, true);
   selectors.forEach(other => { other.value = selector.value; });
  });
 });
 const openers = new WeakMap();
 window.adminShell = {open(dialog, opener) {
  if (dialog.open) return;
  if (dialog.id === 'global-jump') dialog.dataset.check = opener?.dataset.jumpCheck || 'false';
  openers.set(dialog, opener);
  dialog.showModal();
  opener?.setAttribute('aria-expanded', 'true');
  dialog.dispatchEvent(new Event('shell-open'));
 }};
 document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', event => {
  event.preventDefault();
  window.adminShell.open(document.getElementById(button.dataset.open), button);
 }));
 document.querySelectorAll('dialog').forEach(dialog => {
  dialog.addEventListener('close', () => {
   const opener = openers.get(dialog);
   opener?.setAttribute('aria-expanded', 'false');
   // The close event fires after close(): if another dialog is open again by then (Escape, then Enter at once), focus is already
   // where it belongs, so the stale close must not pull it back to the opener.
   if (![...document.querySelectorAll('dialog')].some(open => open.open)) opener?.focus();
  });
  dialog.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
 });
 document.querySelectorAll('details[data-disclosure-parent]').forEach(details => {
  details.addEventListener('toggle', () => details.querySelector('summary').setAttribute('aria-expanded', String(details.open)));
 });
 const segments = [...document.querySelectorAll('[data-theme-mode]')];
 const syncTheme = () => {
  selectors.forEach(selector => { selector.value = window.adminTheme.mode; });
  segments.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.themeMode === window.adminTheme.mode)));
 };
 segments.forEach(button => button.addEventListener('click', () => { window.adminTheme.apply(button.dataset.themeMode, true); syncTheme(); }));
 document.addEventListener('admin-theme', syncTheme); syncTheme();
 // The sub row (a phone's strip, a narrow desktop's row): bring the active entry into view so Gear, Books and Catalogs do not sit off the edge (#153).
 // Only the strip scrolls (never the page) and only when the entry is not already fully visible; the jump is instant, so no motion at all
 // for prefers-reduced-motion users.
 const revealActive = () => document.querySelectorAll('.bp-shell .sub, .bp-shell .psub').forEach(strip => {
  const link = strip.querySelector('a[aria-current=page]');
  if (!link || strip.scrollWidth <= strip.clientWidth) return;
  const box = strip.getBoundingClientRect(), at = link.getBoundingClientRect();
  if (at.left >= box.left && at.right <= box.right) return;
  strip.scrollTo({ left: strip.scrollLeft + (at.left - box.left) - (box.width - at.width) / 2, behavior: 'auto' });
 });
 // After load, not at script time: measuring here forced an early layout on every page, which changed how Linux draws form controls'
 // text (the screenshot gate saw the selects of Place and Tools & Admin differ). The node harnesses have no addEventListener: run at once there.
 // Again when the strip appears or changes width: a window narrowed into the phone layout, or a phone rotated (Codex review).
 if (typeof window.addEventListener === 'function') {
  if (document.readyState === 'complete') revealActive(); else window.addEventListener('load', revealActive);
  let revealTimer;
  window.addEventListener('resize', () => { clearTimeout(revealTimer); revealTimer = setTimeout(revealActive, 100); });
 } else revealActive();
})();
