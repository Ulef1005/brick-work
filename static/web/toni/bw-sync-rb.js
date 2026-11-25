/* Rebrickable sync (#519): the pick step's chips and counts, and the seconds line of the preview. Without it the page still works: every set is a tick box. */
(function () {
  const forms = typeof document.querySelectorAll === 'function' ? document.querySelectorAll('[data-sr-pick]') : [];
  forms.forEach((form) => {
    const rows = [...form.querySelectorAll('[data-sr-row]')];
    const chips = [...form.querySelectorAll('[data-sr-chip]')];
    const search = form.querySelector('[data-sr-search]');
    const shown = form.querySelector('[data-sr-picked]');
    const keysOf = (row) => (row.dataset.keys || '').split('|').filter(Boolean);
    const boxOf = (row) => row.querySelector('[data-sr-item]');
    const sync = () => {
      const on = rows.filter((row) => boxOf(row).checked);
      if (shown) shown.textContent = String(on.length);
      chips.forEach((chip) => {
        const mine = rows.filter((row) => keysOf(row).includes(chip.dataset.srChip));
        chip.setAttribute('aria-pressed', String(mine.length > 0 && mine.every((row) => boxOf(row).checked)));
      });
    };
    chips.forEach((chip) => chip.addEventListener('click', () => {
      const mine = rows.filter((row) => keysOf(row).includes(chip.dataset.srChip));
      const all = mine.every((row) => boxOf(row).checked);
      mine.forEach((row) => { boxOf(row).checked = !all; });
      sync();
    }));
    form.addEventListener('change', sync);
    if (search) search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      rows.forEach((row) => { row.hidden = Boolean(q) && !(row.dataset.name || '').toLowerCase().includes(q); });
    });
    sync();
  });
  const seconds = typeof document.querySelector === 'function' ? document.querySelector('[data-sr-seconds]') : null;
  const requests = typeof document.querySelector === 'function' ? document.querySelector('[data-sy-requests]') : null;
  if (seconds && requests && typeof MutationObserver === 'function') {
    new MutationObserver(() => { seconds.textContent = requests.textContent; }).observe(requests, { childList: true, characterData: true, subtree: true });
  }
})();
