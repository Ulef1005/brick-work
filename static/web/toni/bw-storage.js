(() => {
  'use strict';
  const LIMIT = 5;
  const match = (item, query) => `${item.name || ''} ${item.number || ''} ${item.colour || ''}`.toLowerCase().includes(query.toLowerCase());
  const order = (a, b, sort) => (sort === 'need' ? Number(b.need) - Number(a.need) : 0) || a.rank - b.rank;
  // Which items of each group show. A group shows LIMIT rows until it is expanded or a search or filter narrows it.
  // A checked item (item.checked) is never hidden or unchecked by a search, filter or limit: the move must carry what the person sees.
  const plan = (groups, {query = '', kind = '', sort = 'rank', expanded = []} = {}) => groups.map(group => {
    const hits = group.items.filter(item => (!kind || group.key === kind) && match(item, query)).sort((a, b) => order(a, b, sort));
    const limit = query || kind || expanded.includes(group.key) ? Infinity : LIMIT;
    const kept = hits.slice(0, limit), keep = new Set(kept);
    const forced = group.items.filter(item => item.checked && !keep.has(item)).sort((a, b) => order(a, b, sort));
    return {key: group.key, total: group.items.length, matches: hits, shown: [...kept, ...forced], more: Math.max(0, hits.length - limit)};
  });
  // What a move will take, in words: lots first, and the parts a checked lot carries count with the parts.
  const NOUNS = {lot: ['lot', 'lots'], copy: ['set', 'sets'], figure: ['figure', 'figures'], part: ['part', 'parts'], other: ['other item', 'other items']};
  const moveSummary = items => {
    const counts = {};
    items.forEach(item => { const key = item.forced ? 'part' : item.entity === 'stock' ? item.kind : item.entity; counts[key] = (counts[key] || 0) + 1; });
    const text = Object.keys(NOUNS).filter(key => counts[key]).map(key => `${counts[key]} ${NOUNS[key][counts[key] === 1 ? 0 : 1]}`).join(' · ');
    return text || '0 items';
  };
  // Checking a lot checks and disables its parts in this storage; unchecking it frees them again.
  const carry = items => {
    const lots = new Set(items.filter(i => i.entity === 'lot' && i.checked).map(i => i.id));
    items.filter(i => i.lot).forEach(i => {
      if (lots.has(i.lot)) { i.checked = true; i.disabled = true; i.forced = true; }
      else if (i.forced) { i.checked = false; i.disabled = false; i.forced = false; }
    });
    return items;
  };
  window.BrickStorage = {plan, match, LIMIT, shownCount: result => result.reduce((n, entry) => n + entry.shown.filter(item => !item.lot).length, 0), moveSummary, carry};
  // The click rule for rows outside select mode: links keep working, the hidden checkbox never toggles.
  window.BrickStorage.blocksClick = (selecting, target) => !selecting && !target.closest?.('a');
  const root = document.querySelector('#bw-ledger.bw-storage');
  const tools = root?.querySelector('[data-detail-tools]');
  if (!root || !tools) return;
  const search = tools.querySelector('[data-search]'), filter = tools.querySelector('[data-filter]'), sort = tools.querySelector('[data-sort]');
  const panel = tools.querySelector('[data-filter-panel]'), opener = tools.querySelector('[data-filters]');
  const count = tools.querySelector('[data-count]'), chips = tools.querySelector('[data-chips]');
  const groups = Array.from(root.querySelectorAll('.st-group')).map(node => ({
    key: node.dataset.group, node, noun: node.dataset.noun, title: node.querySelector('h2').firstChild.textContent.replace(/ · $/, ''),
    more: node.querySelector('[data-more]'), counter: node.querySelector('[data-group-count]'),
    items: Array.from(node.querySelectorAll('[data-item]')).map((item, rank) => { const box = item.querySelector('[data-selection]'); return {...item.dataset, rank, node: item, box, ...JSON.parse(box.dataset.selection)}; })
  }));
  groups.forEach(group => { const option = document.createElement('option'); option.value = group.key; option.textContent = group.title; filter.append(option); });
  const expanded = [];
  const form = root.querySelector('.st-move-form'), bar = root.querySelector('[data-bar]');
  const selectButton = root.querySelector('[data-select]'), moveOpen = root.querySelector('[data-move-open]');
  const selecting = () => root.classList.contains('is-selecting');
  const everything = () => groups.flatMap(g => g.items);
  const sync = () => {
    const all = everything();
    all.forEach(i => { i.checked = i.box.checked; });
    carry(all).forEach(i => { i.box.checked = i.checked; i.box.disabled = Boolean(i.disabled); });
    const picked = all.filter(i => i.box.checked);
    const n = picked.filter(i => !i.forced).length;
    bar.querySelector('[data-selected-count]').textContent = `${n} selected`;
    moveOpen.disabled = n === 0;
    root.querySelectorAll('[data-move-count]').forEach(node => { node.textContent = moveSummary(picked); });
  };
  const render = () => {
    const query = search.value.trim(), kind = filter.value;
    carry(everything().map(i => { i.checked = i.box.checked; return i; }));
    const result = plan(groups, {query, kind, sort: sort.value, expanded});
    let total = 0;
    result.forEach((entry, index) => {
      const group = groups[index], container = group.node.querySelector('[data-items]');
      const shown = new Set(entry.shown);
      group.items.forEach(item => { item.node.hidden = !shown.has(item); });
      entry.shown.forEach(item => container.append(item.node));
      total += entry.shown.length;
      group.node.hidden = !entry.shown.length;
      group.counter.textContent = String(group.items.filter(i => !i.lot).length);
      const more = Math.max(0, entry.matches.length - entry.shown.filter(i => entry.matches.includes(i)).length);
      group.more.hidden = more === 0;
      group.more.querySelector('span').textContent = `Show all ${entry.matches.length} ${group.noun}`;
    });
    count.textContent = window.BrickLedger.countText(count, total);
    root.querySelector('[data-nomatch]').hidden = total > 0;
    chips.replaceChildren();
    [search, filter].filter(c => c.value).forEach(control => {
      const chip = document.createElement('button'); chip.type = 'button';
      chip.textContent = `${control.tagName === 'SELECT' ? control.selectedOptions[0].textContent : control.value} ×`;
      chip.setAttribute('aria-label', `Remove filter ${control.value}`);
      chip.addEventListener('click', () => { control.value = ''; render(); control.focus?.(); });
      chips.append(chip);
    });
    sync();
  };
  search.addEventListener('input', render); filter.addEventListener('change', render); sort.addEventListener('change', render);
  opener.addEventListener('click', () => { panel.hidden = !panel.hidden; opener.setAttribute('aria-expanded', String(!panel.hidden)); if (!panel.hidden) filter.focus(); });
  groups.forEach(group => group.more.addEventListener('click', () => { expanded.push(group.key); render(); }));
  selectButton?.addEventListener('click', () => {
    const on = !selecting();
    root.classList.toggle('is-selecting', on);
    selectButton.setAttribute('aria-pressed', String(on));
    selectButton.textContent = on ? 'Cancel' : 'Select';
    bar.hidden = !on;
    if (!on) groups.forEach(g => g.items.forEach(i => { i.box.checked = false; i.box.disabled = false; i.forced = false; }));
    render();
  });
  // Outside select mode the hidden checkbox must not toggle from a click on its row.
  root.querySelectorAll('[data-item]').forEach(node => node.addEventListener('click', event => { if (window.BrickStorage.blocksClick(selecting(), event.target)) event.preventDefault(); }));
  form?.addEventListener('change', sync);
  render();
})();
