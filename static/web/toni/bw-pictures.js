/* Sum server estimates; confirmation recomputes exact identities and checks files. */
(() => {
 'use strict';
 function count(matrix, types, scope) {
  const result = {count:0, unresolved:0, unknown_colour:0};
  if (!types.length) return result;
  for (const kind of new Set([...types, '?'])) {
   for (const key of Object.keys(result)) result[key] += matrix[kind][scope][key];
  }
  return result;
 }
 window.BrickPictureCount = count;
 document.addEventListener('DOMContentLoaded', () => {
  const dialog = document.querySelector('[data-picture-dialog]');
  if (!dialog) return;
  const form = dialog.querySelector('form');
  const matrix = JSON.parse(document.querySelector('[data-picture-counts]').textContent);
  const opener = document.querySelector('[data-picture-open]');
  function update() {
   const data = new FormData(form);
   const total = count(matrix, data.getAll('types'), data.get('scope'));
   form.querySelector('[data-picture-expected]').value = total.count;
   form.querySelector('[data-picture-count]').textContent = `${total.count} picture identities will be queued · ${total.unresolved} unresolved · ${total.unknown_colour} unknown colour will be skipped`;
   form.querySelector('[data-picture-submit]').disabled = !data.getAll('types').length || !total.count;
  }
  opener.addEventListener('click', () => {update();dialog.showModal();});
  dialog.querySelector('[data-picture-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => opener.focus());
  form.addEventListener('change', update);
  form.addEventListener('submit', () => {form.querySelector('[data-picture-submit]').disabled = true;});
 });
})();
