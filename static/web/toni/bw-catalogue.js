/* Catalogue jobs (poll the running job, then reload to show the result) and the picture source order on Settings (M.10c). */
(() => {
 'use strict';
 const job = document.querySelector('[data-catalogue-job]');
 if (job) {
  const fill = job.querySelector('[data-import-fill]'), bar = job.querySelector('[data-import-bar]'), message = job.querySelector('[data-import-message]');
  const tick = async () => {
   try {
    const r = await fetch(job.dataset.jobUrl, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
    const s = await r.json();
    if (s.state !== 'running') { location.reload(); return; }
    const total = (s.steps || []).length || 1, percent = Math.round(100 * s.step / total);
    fill.style.width = percent + '%';
    bar.setAttribute('aria-valuenow', String(percent));
    message.textContent = (s.steps || [])[s.step] || '';
    job.querySelectorAll('.bwc-steps li').forEach(li => {
     const i = Number(li.dataset.step);
     li.className = i < s.step ? 'bwc-done' : i === s.step ? 'bwc-now' : '';
     li.firstElementChild.textContent = i <= s.step ? '●' : '○';
    });
   } catch (e) { /* offline for a moment: the next tick tries again */ }
   setTimeout(tick, 1500);
  };
  setTimeout(tick, 1500);
 }
 document.querySelectorAll('[data-order-group]').forEach(group => {
  const list = group.querySelector('[data-order-list]'), value = group.querySelector('[data-order-value]');
  const sync = () => {
   const items = [...list.children];
   value.value = items.filter(li => li.querySelector('[data-order-use]').checked).map(li => li.dataset.source).join(',');
   items.forEach(li => li.classList.toggle('bwc-unused', !li.querySelector('[data-order-use]').checked));
  };
  list.addEventListener('click', event => {
   const up = event.target.closest('[data-order-up]'), down = event.target.closest('[data-order-down]');
   const li = (up || down)?.closest('li');
   if (!li) return;
   if (up && li.previousElementSibling) li.parentNode.insertBefore(li, li.previousElementSibling);
   if (down && li.nextElementSibling) li.parentNode.insertBefore(li.nextElementSibling, li);
   sync();
   (up || down).focus();
  });
  list.addEventListener('change', sync);
 });
})();
