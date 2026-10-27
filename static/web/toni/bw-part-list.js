/* The copy page's Part list: the Switch sheet (design 4.4), Cancel of a pending BrickLink switch and Switch now for a ready one.
   Writes go through /collection/save/part-list*; a switch keeps its receipt where the page's Undo reads it. */
(() => {
 'use strict';
 const root = document.querySelector('#bw-collection');
 if (!root) return;
 const dialog = document.getElementById('bc-part-list');
 const body = dialog && dialog.querySelector('[data-bc-part-body]');
 const message = root.querySelector('[data-bc-message]');
 const receiptKey = 'bw-collection-receipt', flashKey = 'bw-part-list-flash';
 const store = (fn) => { try { return fn(sessionStorage); } catch (_) { return null; } };
 const flash = store(s => s.getItem(flashKey));
 if (flash) { store(s => s.removeItem(flashKey)); if (message) message.textContent = flash; }
 const send = async (action, data) => {
  const response = await fetch(root.dataset.saveUrl.replace('ACTION', action), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...data, csrf_token: root.dataset.csrf})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || 'Not saved · try again');
  return result;
 };
 const done = result => {
  if (result.event_id) store(s => s.setItem(receiptKey, JSON.stringify(result)));
  else store(s => { s.removeItem(receiptKey); s.setItem(flashKey, result.message); });
  location.reload();
 };
 const bind = form => {
  const radios = [...form.querySelectorAll('input[name=choice]')];
  const sync = () => {
   const chosen = radios.find(r => r.checked);
   form.querySelectorAll('[data-bc-change]').forEach(s => { s.hidden = !chosen || s.dataset.bcChange !== chosen.value; });
   const go = form.querySelector('button[type=submit]');
   if (go) go.disabled = !chosen;
  };
  radios.forEach(r => r.addEventListener('change', sync));
  form.querySelectorAll('[data-bw-close]').forEach(b => b.addEventListener('click', () => dialog.close()));
  const status = form.querySelector('[data-bc-form-message]');
  form.addEventListener('submit', async event => {
   event.preventDefault();
   const chosen = radios.find(r => r.checked);
   if (!chosen) return;
   const buttons = [...form.querySelectorAll('button')];
   buttons.forEach(b => { b.disabled = true; });
   if (status) status.textContent = 'Saving';
   try {
    done(await send('part-list', {copy_id: form.dataset.copy, choice: chosen.value, preference: form.querySelector('[name=preference]').checked}));
   } catch (error) {
    if (status) status.textContent = error.message + ' · Try again';
    buttons.forEach(b => { b.disabled = false; });
   }
  });
  sync();
 };
 root.querySelectorAll('[data-bc-part-list]').forEach(opener => opener.addEventListener('click', async () => {
  if (!dialog) return;
  opener.disabled = true;
  try {
   const response = await fetch(opener.dataset.bcPartList, {headers: {Accept: 'text/html'}});
   if (!response.ok) throw new Error('The part lists could not be loaded');
   body.innerHTML = await response.text();
   bind(body.querySelector('form'));
   dialog.showModal();
  } catch (error) { if (message) message.textContent = error.message; }
  finally { opener.disabled = false; }
 }));
 root.querySelectorAll('[data-bc-part-act]').forEach(button => button.addEventListener('click', async () => {
  button.disabled = true;
  try { done(await send(button.dataset.bcPartAct, {copy_id: button.dataset.copy})); }
  catch (error) { if (message) message.textContent = error.message; button.disabled = false; }
 }));
})();
