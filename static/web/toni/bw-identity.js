/* Unresolved items: search, Filters by reason, Sort, removable chips and the count (the kit's list pattern). Rows stay in the page; nothing is fetched. */
(() => {
 const words = {merge: 'Merge candidates', link: 'Links to check', no_candidate: 'No candidate', kind_differs: 'Kind differs', migration: 'From the migration', unidentified: 'Unidentified'};
 function update(list) {
  const query = (list.querySelector('[data-bu-search]')?.value || '').trim().toLowerCase();
  const reason = list.querySelector('[data-bu-filter]:checked')?.value || '';
  const sort = list.querySelector('[data-bu-sort]:checked')?.value || 'name';
  const container = list.querySelector('[data-bu-rows]');
  const rows = [...container.querySelectorAll('[data-bu-row]')];
  rows.sort((a, b) => sort === 'uses' ? Number(b.dataset.uses) - Number(a.dataset.uses) || a.dataset.name.localeCompare(b.dataset.name)
   : sort === 'kind' ? a.dataset.kind.localeCompare(b.dataset.kind) || a.dataset.name.localeCompare(b.dataset.name) : a.dataset.name.localeCompare(b.dataset.name));
  let shown = 0;
  for (const row of rows) {
   row.hidden = (query && !row.dataset.name.toLowerCase().includes(query)) || (reason && !row.dataset.facets.split(' ').includes(reason));
   if (!row.hidden) shown++;
   container.appendChild(row);
  }
  const count = list.querySelector('[data-bu-count]');
  if (count) count.textContent = `${shown} ${shown === 1 ? 'item' : 'items'}`;
  const empty = list.querySelector('[data-bu-empty]');
  if (empty) empty.hidden = shown > 0 || rows.length === 0;
  const chips = list.querySelector('[data-bu-chips]');
  if (!chips) return;
  chips.replaceChildren();
  const add = (label, clear) => {
   const chip = document.createElement('button');
   chip.type = 'button';
   chip.textContent = label + ' · Remove';
   chip.setAttribute('aria-label', 'Remove filter: ' + label);
   chip.addEventListener('click', clear);
   chips.appendChild(chip);
  };
  if (query) add(`“${query}”`, () => { list.querySelector('[data-bu-search]').value = ''; update(list); });
  if (reason) add(words[reason] || reason, () => { list.querySelector('[data-bu-filter][value=""]').checked = true; update(list); });
 }
 document.querySelectorAll('[data-bu-list]').forEach(list => {
  list.addEventListener('input', () => update(list));
  list.addEventListener('change', () => update(list));
  list.querySelectorAll('[data-bu-open]').forEach(button => button.addEventListener('click', () => {
   const panel = list.querySelector(`[data-bu-panel="${button.dataset.buOpen}"]`);
   const open = panel.hidden;
   list.querySelectorAll('[data-bu-panel]').forEach(p => { p.hidden = true; });
   list.querySelectorAll('[data-bu-open]').forEach(b => b.setAttribute('aria-expanded', 'false'));
   panel.hidden = !open;
   button.setAttribute('aria-expanded', String(open));
  }));
  update(list);
 });
})();
