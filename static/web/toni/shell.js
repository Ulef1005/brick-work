/* Production subset of approved admin.js: theme and native dialog only.
   Native showModal provides focus containment and Escape; restore the opener. */
(() => {
 const selectors = [...document.querySelectorAll('[data-theme-selector]')];
 selectors.forEach(selector => {
  selector.value = window.adminTheme.mode;
  selector.addEventListener('change', () => {
   window.adminTheme.apply(selector.value, true);
   selectors.forEach(other => { other.value = selector.value; });
  });
 });
 const scrim = document.querySelectorAll('[data-nav-scrim]')[0];
 const navSheets = [...document.querySelectorAll('[data-nav-sheet]')];
 const openers = new WeakMap();
 const focusTargets = new WeakMap(), handoffs = new WeakSet();
 const closeNavigation = (handoff = false) => navSheets.forEach(sheet => {
  if (sheet.open) {
   if (handoff) handoffs.add(sheet);
   sheet.close();
  }
 });
 scrim?.addEventListener('click', () => closeNavigation());
 document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && navSheets.some(sheet => sheet.open)) {
   event.preventDefault(); closeNavigation();
  }
 });
 const desktop = matchMedia('(min-width: 1024px)');
 const restoreFocus = target => {
  if (desktop.matches && target?.dataset.navGroup) {
   target = document.querySelectorAll(`.rail nav [data-rail-group="${target.dataset.navGroup}"] a`)[0]
    || document.querySelectorAll('main')[0];
  }
  target?.focus();
 };
 window.adminShell = {open(dialog, opener, keyboard = true) {
  if (dialog.open) return;
  if (dialog.id === 'global-jump') dialog.dataset.check = opener?.dataset.jumpCheck || 'false';
  closeNavigation(true);
  openers.set(dialog, opener);
  if (dialog.dataset.navSheet) { dialog.show(); if (scrim) scrim.hidden = false; }
  else dialog.showModal();
  opener?.setAttribute('aria-expanded', 'true');
  if (dialog.dataset.navSheet) {
   const target = keyboard ? dialog.querySelectorAll('.workbench-grid a, .workbench-grid button')[0] : dialog;
   target?.focus();
  }
  dialog.dispatchEvent(new Event('shell-open'));
 }};
 document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', event => {
  event.preventDefault();
  const dialog = document.getElementById(button.dataset.open);
  if (dialog.id === 'appearance') {
   const sheet = button.closest('[data-nav-sheet]');
   if (sheet?.open) {
    focusTargets.set(dialog, openers.get(sheet));
    handoffs.add(sheet);
    sheet.close();
   } else focusTargets.delete(dialog);
  }
  window.adminShell.open(dialog, button);
 }));
 document.querySelectorAll('dialog').forEach(dialog => {
  dialog.addEventListener('close', () => {
   if (dialog.dataset.navSheet && scrim) scrim.hidden = !navSheets.some(sheet => sheet.open);
   const opener = openers.get(dialog);
   opener?.setAttribute('aria-expanded', 'false');
   if (handoffs.has(dialog)) handoffs.delete(dialog);
   // The close event fires after close(): if this or another dialog is open again by then (Escape, then Enter at once), focus is already
   // where it belongs, so the stale close must not pull it back to the opener.
   else if (![...document.querySelectorAll('dialog')].some(open => open.open)) restoreFocus(focusTargets.get(dialog) || opener);
  });
  dialog.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
 });
 document.querySelectorAll('details[data-disclosure-parent]').forEach(details => {
  details.addEventListener('toggle', () => details.querySelector('summary').setAttribute('aria-expanded', String(details.open)));
 });
 desktop.addEventListener('change', event => {
  if (event.matches) document.querySelectorAll('[data-nav-sheet]').forEach(sheet => {
   if (sheet.open) sheet.close();
  });
 });
 const segments = [...document.querySelectorAll('[data-theme-mode]')];
 const syncTheme = () => {
  selectors.forEach(selector => { selector.value = window.adminTheme.mode; });
  segments.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.themeMode === window.adminTheme.mode)));
  const dark = window.adminTheme.mode === 'dark' || (window.adminTheme.mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.querySelectorAll('.brand-mark').forEach(mark => { mark.src = dark ? mark.dataset.dark : mark.dataset.light; });
 };
 segments.forEach(button => button.addEventListener('click', () => { window.adminTheme.apply(button.dataset.themeMode, true); syncTheme(); }));
 document.addEventListener('admin-theme', syncTheme); syncTheme();
 document.querySelectorAll('[data-nav-group]').forEach(tab => {
  const open = (event, keyboard) => {
   const sheet = document.getElementById(tab.getAttribute('aria-controls'));
   if (!sheet) return;
   event.preventDefault();
   window.adminShell.open(sheet, tab, keyboard);
  };
  tab.addEventListener('click', event => open(event, event.detail === 0));
  tab.addEventListener('keydown', event => {
   if (event.key === 'Enter' || event.key === ' ') open(event, true);
  });
 });
 document.querySelectorAll('[data-nav-sheet]').forEach(sheet => {
  sheet.addEventListener('click', event => {
   if (event.target !== sheet) return;
   const rect = sheet.getBoundingClientRect();
   if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) sheet.close();
  });
 });
 // Touch labels on the collapsed rail, without changing the destination.
 document.querySelectorAll('.rail nav a').forEach(link => {
  let timer, labelled = false;
  link.addEventListener('pointerdown', event => {
   if (event.pointerType === 'mouse' || !matchMedia('(min-width: 1024px) and (max-width: 1279px)').matches) return;
   timer = setTimeout(() => {
    const label = document.createElement('span'); label.className = 'rail-tooltip'; label.textContent = link.title;
    link.append(label); labelled = true;
   }, 500);
  });
  ['pointerup','pointercancel','pointerleave'].forEach(type => link.addEventListener(type, () => clearTimeout(timer)));
  link.addEventListener('click', event => { if (labelled) { event.preventDefault(); link.querySelector('.rail-tooltip')?.remove(); labelled = false; } });
 });
 // Phone top strip: bring the active entry into view so Gear, Books and Catalogs do not sit off the edge (#153).
 // Only the strip scrolls (never the page) and only when the entry is not already fully visible; the jump is instant, so no motion at all
 // for prefers-reduced-motion users.
 const revealActive = () => document.querySelectorAll('.group-items > div:not([hidden])').forEach(strip => {
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
