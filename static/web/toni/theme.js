/* Port of approved kit theme.js; server default replaces specimen query override. */
/* Runs synchronously in the head before styles, including when storage is blocked. */
(() => {
 const valid = value => ['system','light','dark'].includes(value);
 let stored; try { stored = localStorage.getItem('tw-admin-theme'); } catch {}
 const initial = document.documentElement.dataset.themeDefault;
 let mode = valid(stored) ? stored : valid(initial) ? initial : 'system';
 window.adminTheme = {
  get mode() { return mode; },
  apply(value, persist = false) {
   mode = valid(value) ? value : 'system';
   document.documentElement.classList.remove('tw-light','tw-dark');
   if (mode !== 'system') document.documentElement.classList.add('tw-' + mode);
   if (persist) { try { localStorage.setItem('tw-admin-theme', mode); } catch {} }
   document.dispatchEvent(new CustomEvent('admin-theme', {detail: mode}));
  }
 };
 window.adminTheme.apply(mode);
 matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (mode === 'system') window.adminTheme.apply('system');
 });
})();
