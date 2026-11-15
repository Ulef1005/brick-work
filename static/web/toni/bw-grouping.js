/* Settings: the live "Changed: N categories." line of the Edit grouping editor. The page works without it; the server counts again on save. */
(() => {
 'use strict';
 function changed(selects) {
  return Array.from(selects).filter((select) => select.value !== select.dataset.default).length;
 }
 function line(count) {
  return `Changed: ${count} ${count === 1 ? 'category' : 'categories'}.`;
 }
 window.BrickGroupingChanged = changed;
 window.BrickGroupingLine = line;
 document.addEventListener('DOMContentLoaded', () => {
  const editor = document.querySelector('[data-grouping-editor]');
  if (!editor) return;
  const status = editor.querySelector('[data-grouping-status]');
  const selects = editor.querySelectorAll('select[data-default]');
  editor.addEventListener('change', () => {status.textContent = line(changed(selects));});
 });
})();
