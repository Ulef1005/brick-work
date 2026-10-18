/* Prices (4b): compact records load once, 15 rows render per page, a row's observations load when Details opens. */
(() => {
  'use strict';
  const PAGE = 15;
  const collator = new Intl.Collator(undefined, {numeric: true});
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const tail = value => (window.BrickFormatting?.nowrapTail || (x => x))(value);

  function decode(data) {
    return data.rows.map(row => {
      const r = {};
      data.fields.forEach((field, i) => { r[field] = row[i]; });
      r.hay = [r.number, r.name, r.colour].join(' ').toLocaleLowerCase();
      r.id = r.type + '|' + r.number + '|' + (r.color_id == null ? '' : r.color_id);  // an attribute value: no control characters
      return r;
    });
  }
  // Number, then name, then colour keeps equal numbers (one part in many colours) in a stable order.
  function sortRows(rows, sort, descending) {
    const direction = descending ? -1 : 1;
    const tie = (a, b) => collator.compare(a.number, b.number) || collator.compare(a.colour, b.colour) || (a.type < b.type ? -1 : a.type > b.type ? 1 : 0);
    return rows.slice().sort((a, b) => {
      if (sort === 'age') {
        // Rows without a recorded date stay last in either direction.
        if (!a.observed !== !b.observed) return a.observed ? -1 : 1;
        return (a.observed < b.observed ? -1 : a.observed > b.observed ? 1 : 0) * direction || tie(a, b);
      }
      const diff = sort === 'name' ? collator.compare(a.name, b.name) : collator.compare(a.number, b.number);
      return diff * direction || tie(a, b);
    });
  }
  function filterRows(rows, {query = '', type = '', stale = '', collection = ''} = {}) {
    const text = query.trim().toLocaleLowerCase();
    return rows.filter(r => (!text || r.hay.includes(text)) && (!type || r.type === type) &&
      (!stale || (stale === 'true') === !!r.stale) && (!collection || !!r[collection]));
  }
  // First, last and current page with their neighbours; a single skipped page shows as its number, longer gaps as an ellipsis.
  function pageItems(pages, page) {
    const wanted = [...new Set([1, page - 1, page, page + 1, pages].filter(n => n >= 1 && n <= pages))].sort((a, b) => a - b), items = [];
    wanted.forEach((n, i) => { if (i) { const gap = n - wanted[i - 1]; if (gap === 2) items.push(n - 1); else if (gap > 2) items.push('…'); } items.push(n); });
    return items;
  }
  const rangeText = (total, page) => total ? ((page - 1) * PAGE + 1) + ' to ' + Math.min(total, page * PAGE) + ' of ' + total : '';
  const itemUrl = (cfg, r) => cfg.itemBase.replace('TYPE', encodeURIComponent(r.type)).replace('NUMBER', r.number.split('/').map(encodeURIComponent).join('/')) +
    (r.color_id == null ? '' : '?colour=' + encodeURIComponent(r.color_id));

  function pictureHtml(cfg, r) {
    if (r.image == null) return '<span class="mono">' + esc(r.number) + '</span><span>No image</span>';
    const src = esc(cfg.imageBase.replace(/0$/, '') + r.image);
    // Thumbnail with srcset; the link and data-full keep the original for the lightbox.
    return '<a href="' + src + '"><img src="' + src + '?w=320" srcset="' + src + '?w=320 320w, ' + src + '?w=640 640w" sizes="160px" data-full="' + src + '" alt="' + esc(r.name + (r.colour ? ' · ' + r.colour : '')) + '" loading="lazy"></a>';
  }
  function rowHtml(cfg, r) {
    const kind = cfg.types[r.type] || r.type;
    const chip = r.type === 'P' ? '<span class="bc-colour"' + (r.rgb ? ' style="background:#' + esc(r.rgb) + ';color:' + esc(r.ink) + '"' : '') + '>' + esc(r.colour || 'Unknown colour') + '</span>' : '';
    const flag = r.unresolved ? '<span class="status">' + (r.type === '?' ? 'Placeholder' : 'To check') + '</span>' : '';
    const age = r.price == null ? '' : esc(r.age) + (r.price_stale ? ' · stale' : '');
    const price = r.price == null ? '<span>no sales</span>'
      : '<span class="mono bp-short-price">' + (r.listings ? 'listings ' : '') + esc(r.price) + '<small class="bp-phone-age">' + age + '</small></span>';
    const refresh = cfg.editable && !r.unresolved ? '<button type="button" data-bp-refresh=\'' + esc(JSON.stringify([r.type, r.number])) + '\'>Update</button>' : '';
    return '<article class="bp-row" tabindex="0" data-bp-row data-key="' + esc(r.id) + '">' +
      '<div class="bp-identity"><div class="bc-picture" data-item-no="' + esc(r.number) + '">' + pictureHtml(cfg, r) + '</div><div>' +
      '<a href="' + esc(itemUrl(cfg, r)) + '"><div class="bc-identity">' + chip + '<span class="mono">' + esc(r.number) +
      '<span class="bp-phone-kind"> · ' + esc(kind) + (r.owned ? ' · Owned' : '') + (r.wanted ? ' · Wanted' : '') + '</span></span>' +
      (r.name ? '<strong>' + esc(tail(r.name)) + '</strong>' : '') + flag + '</div></a>' +
      (r.unresolved ? '<a href="' + esc(cfg.unresolvedUrl) + '">Unresolved figures</a>' : '') + '</div></div>' +
      '<div class="bp-kind"><span class="bc-status">' + esc(kind) + '</span>' + (r.owned ? '<span class="bc-status">Owned</span>' : '') + (r.wanted ? '<span class="bc-status">Wanted</span>' : '') + '</div>' +
      '<div class="bp-values"><div class="bp-condition-prices">' + price + '</div>' +
      '<details class="kit-disclosure bp-records" data-bp-details><summary>Details</summary><div data-bp-details-body></div></details></div>' +
      '<div class="bp-ages mono secondary">' + (r.price == null ? '' : '<span class="bp-desktop-age">' + age + '</span>') + refresh + '</div></article>';
  }
  function quoteHtml(q) {
    return '<div class="bp-quote"><div class="actions"><strong>' + esc(q.label) + '</strong><span class="mono">' + esc(q.head) + '</span></div>' +
      (q.range != null ? '<div class="bc-range" aria-label="' + esc(q.aria) + '"><i style="left:' + Number(q.range) + '%"></i></div><div class="actions mono"><span>min ' + esc(q.min) + '</span><span>max ' + esc(q.max) + '</span></div>' : '') +
      '<p class="mono secondary">' + esc(q.meta) + '</p></div>';
  }
  function detailsHtml(cfg, r, d) {
    const kind = [d.context, cfg.types[r.type] || r.type, r.owned ? 'Owned' : '', r.wanted ? 'Wanted' : ''].filter(Boolean).join(' · ');
    return (d.selected ? '<p class="bp-selected-quote">Selected price · ' + esc(d.selected) + '</p>' : '') +
      '<p>' + esc(kind) + '</p><div class="bp-all-conditions">' + d.conditions.map(c => '<p>' + esc(c) + '</p>').join('') + '</div>' +
      d.groups.map(g => '<h3>' + esc(g.label) + '</h3>' + g.quotes.map(quoteHtml).join('')).join('') + (d.empty ? '<p>no sales</p>' : '');
  }
  window.BrickPrices = {decode, sortRows, filterRows, pageItems, rangeText, rowHtml, detailsHtml, esc, PAGE};

  const root = document.querySelector('#bw-planning');
  if (!root || root.dataset.screen !== 'prices') return;
  const cfg = {types: JSON.parse(root.dataset.types || '{}'), itemBase: root.dataset.itemBase, imageBase: root.dataset.imageBase,
    unresolvedUrl: root.dataset.unresolvedUrl, editable: root.dataset.editable === 'true'};
  const $ = selector => root.querySelector(selector);
  const container = $('[data-bp-rows]'), search = $('[data-bp-search]'), sortSelect = $('[data-bp-sort]'), orderSelect = $('[data-bp-order]');
  const message = $('[data-bp-message]'), undo = $('[data-bp-undo]'), count = $('[data-bp-count]'), empty = $('[data-bp-empty]'), loading = $('[data-bp-loading]');
  const controls = [...root.querySelectorAll('[data-bp-filter]')], panel = $('#bp-filters'), chipsBox = $('[data-bp-chips]');
  const bulk = $('[data-bp-refresh-all]');
  const stateKey = 'bw-prices-list', receiptKey = 'bw-planning-receipt';
  let all = [], sorted = [], sortedKey = '', view = [], page = 1, receipt = null, ready = false;
  const state = {query: '', type: root.dataset.kind || '', stale: '', collection: ''};
  try {
    const saved = JSON.parse(sessionStorage.getItem(stateKey));
    if (saved) {
      Object.assign(state, {query: saved.query || '', stale: saved.stale || '', collection: saved.collection || ''});
      if (!root.dataset.kind) state.type = saved.type || '';
      if (sortSelect && saved.sort) sortSelect.value = saved.sort;
      if (orderSelect && saved.order) orderSelect.value = saved.order;
      page = Math.max(1, Number(saved.page) || 1);
    }
  } catch (_) {}
  if (search) search.value = state.query;
  try { receipt = JSON.parse(sessionStorage.getItem(receiptKey)); } catch (_) {}
  if (receipt && undo) { undo.hidden = false; message.textContent = 'Saved · Undo'; }

  // The 12h pager, the same markup and classes as the Collection lists.
  const nav = document.createElement('nav'), prev = document.createElement('button'), next = document.createElement('button'), numbers = document.createElement('div'), text = document.createElement('p');
  nav.className = 'bc-pager'; nav.hidden = true; nav.setAttribute('aria-label', 'Pages'); nav.dataset.bcPager = '';
  numbers.className = 'bc-page-numbers'; text.className = 'mono'; text.dataset.bcPageText = '';
  for (const [b, label, delta] of [[prev, 'Previous', -1], [next, 'Next', 1]]) {
    b.type = 'button'; b.className = 'bc-page-step bc-page-' + (delta < 0 ? 'prev' : 'next'); b.textContent = label; b.setAttribute('aria-label', label + ' page');
    b.addEventListener('click', () => { goTo(page + delta); if (b.disabled) focusCurrent(); });
  }
  nav.append(prev, numbers, next, text); container.after(nav);
  const focusCurrent = () => [...numbers.children].find(c => c.getAttribute('aria-current') === 'page')?.focus({preventScroll: true});
  function goTo(n) { page = n; render(); container.querySelector('[data-bp-row]')?.scrollIntoView?.({block: 'start'}); }
  function updatePager(total) {
    const pages = Math.max(1, Math.ceil(total / PAGE));
    nav.hidden = pages < 2; text.textContent = rangeText(total, page); prev.disabled = page <= 1; next.disabled = page >= pages;
    numbers.replaceChildren(...pageItems(pages, page).map(n => {
      if (n === '…') { const gap = document.createElement('span'); gap.className = 'bc-page-gap'; gap.textContent = '…'; gap.setAttribute('aria-hidden', 'true'); return gap; }
      const b = document.createElement('button'); b.type = 'button'; b.textContent = String(n); b.setAttribute('aria-label', 'Page ' + n);
      b.className = 'bc-page-number' + (n !== 1 && n !== pages && n !== page ? ' bc-page-neighbour' : '');
      if (n === page) b.setAttribute('aria-current', 'page');
      b.addEventListener('click', () => { goTo(n); focusCurrent(); }); return b;
    }));
  }

  function syncControls() {
    controls.forEach(c => { c.value = state[c.dataset.bpFilter] || ''; });
    root.querySelectorAll('[data-bp-chip]').forEach(b => {
      const key = b.dataset.bpChip, value = b.dataset.value;
      b.setAttribute('aria-pressed', String(key === 'all' ? !state.type && !state.stale && !state.collection : key === 'stale' ? state.stale === 'true' : state[key] === value));
    });
  }
  function render() {
    if (!ready) return;
    const order = orderSelect?.value === 'desc', sort = sortSelect?.value || 'number';
    if (sortedKey !== sort + order) { sorted = sortRows(all, sort, order); sortedKey = sort + order; }
    view = filterRows(sorted, state);
    page = Math.min(Math.max(1, page), Math.max(1, Math.ceil(view.length / PAGE)));
    container.innerHTML = view.slice((page - 1) * PAGE, page * PAGE).map(r => rowHtml(cfg, r)).join('');
    container.setAttribute('aria-busy', 'false');
    updatePager(view.length);
    count.textContent = view.length ? rangeText(view.length, page) : window.BrickFormatting?.resultCount ? window.BrickFormatting.resultCount(0, 'results') : '0 results';
    empty.hidden = !ready || view.length > 0;
    if (bulk) bulk.disabled = !view.some(r => !r.unresolved);
    syncControls();
    chipsBox.replaceChildren();
    const active = [...(state.query ? [['Search: ' + state.query, () => { state.query = ''; search.value = ''; }]] : []),
      ...controls.filter(c => c.value).map(c => [c.closest('label').firstChild.textContent.trim() + ': ' + c.selectedOptions[0].textContent, () => { state[c.dataset.bpFilter] = ''; }])];
    active.forEach(([label, clear]) => {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = label + ' ×'; b.setAttribute('aria-label', 'Remove ' + label);
      b.addEventListener('click', () => { clear(); page = 1; render(); }); chipsBox.append(b);
    });
    try { sessionStorage.setItem(stateKey, JSON.stringify({...state, sort, order: orderSelect?.value || 'asc', page})); } catch (_) {}
  }
  function changed() { page = 1; render(); }
  let timer;
  search?.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { state.query = search.value; changed(); }, 120); });
  [sortSelect, orderSelect].filter(Boolean).forEach(c => c.addEventListener('change', changed));
  controls.forEach(c => c.addEventListener('change', () => { state[c.dataset.bpFilter] = c.value; changed(); }));
  root.querySelectorAll('[data-bp-chip]').forEach(b => b.addEventListener('click', () => {
    const key = b.dataset.bpChip;
    if (key === 'all') Object.assign(state, {type: '', stale: '', collection: ''});
    else if (key === 'stale') state.stale = state.stale === 'true' ? '' : 'true';
    else state[key] = state[key] === b.dataset.value ? '' : b.dataset.value;
    changed();
  }));

  // Filter and sort panels, as on the other Planning screens.
  const toggles = [...root.querySelectorAll('[data-bp-filters]')], sortPanel = $('[data-bp-sort-panel]'), sortToggles = [...root.querySelectorAll('[data-bp-sort-open]')];
  let opener = null;
  function closePanels() { [panel, sortPanel].filter(Boolean).forEach(p => { p.hidden = true; }); [...toggles, ...sortToggles].forEach(t => t.setAttribute('aria-expanded', 'false')); }
  function togglePanel(p, buttons, b) {
    const opening = p.hidden; closePanels(); p.hidden = !opening; buttons.forEach(t => t.setAttribute('aria-expanded', String(opening)));
    if (opening) { opener = b; p.querySelector('button, input, select')?.focus(); } else opener?.focus();
  }
  toggles.forEach(b => b.addEventListener('click', () => togglePanel(panel, toggles, b)));
  sortToggles.forEach(b => b.addEventListener('click', () => togglePanel(sortPanel, sortToggles, b)));
  $('[data-bp-reset]')?.addEventListener('click', () => { Object.assign(state, {query: '', type: '', stale: '', collection: ''}); search.value = ''; changed(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && [panel, sortPanel].some(p => p && !p.hidden)) { closePanels(); opener?.focus(); }
    // Phone: Tab stays inside the open filter panel.
    if (e.key === 'Tab' && panel && !panel.hidden && window.matchMedia?.('(max-width:1023px)').matches) {
      const focusable = [...panel.querySelectorAll('button, input, select, a[href]')].filter(n => !n.disabled && n.getClientRects().length);
      if (focusable.length) { const first = focusable[0], last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); } }
    }
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    const rows = [...container.querySelectorAll('[data-bp-row]')], current = e.target.closest?.('[data-bp-row]');
    if (['ArrowDown', 'ArrowUp'].includes(e.key) && rows.length) { e.preventDefault(); rows[Math.max(0, Math.min(rows.length - 1, rows.indexOf(current) + (e.key === 'ArrowDown' ? 1 : -1)))].focus(); }
    if (e.key === 'Enter' && current === e.target) { e.preventDefault(); current.querySelector('.bp-identity a')?.click(); }
    if (e.key === '/' && search) { e.preventDefault(); search.focus(); }
    if (e.key.toLowerCase() === 'f' && toggles[0]) { e.preventDefault(); toggles[0].click(); }
  });

  // Look up any number opens the global jump dialog with the typed text.
  const lookup = $('[data-bp-lookup]');
  lookup?.addEventListener('submit', e => {
    e.preventDefault(); const input = document.getElementById('jump-query'), dialog = document.getElementById('global-jump');
    if (input && dialog) { input.value = $('[data-bp-lookup-query]').value; window.adminShell.open(dialog, lookup.querySelector('button')); }
  });

  // Details: the observation list of one identity loads the first time its disclosure opens.
  const detailCache = new Map();
  container.addEventListener('toggle', async e => {
    const details = e.target;
    if (!details.matches?.('[data-bp-details]') || !details.open || details.dataset.loaded) return;
    const body = details.querySelector('[data-bp-details-body]'), key = details.closest('[data-bp-row]').dataset.key, r = all.find(x => x.id === key);
    if (!r) return;
    body.textContent = 'Loading';
    try {
      if (!detailCache.has(key)) {
        const params = new URLSearchParams({kind: r.type, number: r.number}); if (r.color_id != null) params.set('colour', r.color_id);
        const response = await fetch(root.dataset.detailsUrl + '?' + params, {headers: {Accept: 'application/json'}});
        if (!response.ok) throw new Error('Not loaded');
        detailCache.set(key, await response.json());
      }
      body.innerHTML = detailsHtml(cfg, r, detailCache.get(key)); details.dataset.loaded = '1';
    } catch (_) { body.textContent = 'Not loaded · Close and open Details to try again'; }
  }, true);

  // Saving: the same write route, receipt and Undo as the other Planning screens.
  async function send(action, data) {
    const response = await fetch(root.dataset.saveUrl.replace('ACTION', action), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...data, csrf_token: root.dataset.csrf})});
    const result = await response.json(); if (!response.ok) throw new Error(result.message || 'Not saved · try again');
    if (result.event_id && action !== 'undo') { receipt = {event_id: result.event_id, collection: false}; try { sessionStorage.setItem(receiptKey, JSON.stringify(receipt)); } catch (_) {} undo.hidden = false; }
    message.textContent = result.message; return result;
  }
  async function run(button, operation, reload = false) {
    button.disabled = true; message.textContent = 'Saving';
    try { await operation(); if (reload) location.reload(); } catch (e) { message.textContent = e.message; } finally { button.disabled = false; }
  }
  undo?.addEventListener('click', () => run(undo, async () => {
    const response = await fetch((receipt.collection ? root.dataset.collectionUrl || root.dataset.saveUrl : root.dataset.saveUrl).replace('ACTION', 'undo'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({event_id: receipt.event_id, csrf_token: root.dataset.csrf})});
    const result = await response.json(); if (!response.ok) throw new Error(result.message || 'Not saved · try again');
    message.textContent = result.message; try { sessionStorage.removeItem(receiptKey); } catch (_) {} receipt = null;
  }, true));
  container.addEventListener('click', e => {
    const b = e.target.closest?.('[data-bp-refresh]');
    if (b) run(b, async () => {
      await send('refresh', {items: [JSON.parse(b.dataset.bpRefresh)]});
      const row = b.closest('[data-bp-row]'), d = row?.querySelector('[data-bp-details]');
      if (row) detailCache.delete(row.dataset.key); if (d) delete d.dataset.loaded;
    });
  });
  bulk?.addEventListener('click', () => run(bulk, () => {
    const seen = new Set(), items = [];
    view.forEach(r => { const k = r.type + '|' + r.number; if (r.type !== '?' && !r.unresolved && !seen.has(k)) { seen.add(k); items.push([r.type, r.number]); } });
    const chunks = []; for (let i = 0; i < items.length; i += 2000) chunks.push(items.slice(i, i + 2000));
    return chunks.reduce((done, chunk) => done.then(() => send('refresh', {items: chunk})), Promise.resolve())
      .then(() => { if (chunks.length > 1) message.textContent = items.length + ' items queued in ' + chunks.length + ' parts'; });
  }));

  function headline() {
    const stale = all.filter(r => r.stale).length, title = $('[data-bp-title]'), subtitle = $('[data-bp-subtitle]'), chip = $('[data-bp-chip=stale]');
    // Chips are always on the page, so their arrival moves nothing; those with no rows are disabled.
    if (chip) { chip.disabled = !stale; $('[data-bp-stale-count]').textContent = stale ? String(stale) : ''; }
    if (stale) { title.textContent = stale + (stale === 1 ? ' price is stale' : ' prices are stale'); subtitle.textContent = 'Update one, or the whole filter'; }
    root.querySelectorAll('[data-bp-chip=collection]').forEach(b => { b.disabled = !all.some(r => r[b.dataset.value]); });
  }
  async function load() {
    message.textContent = '';
    try {
      const response = await fetch(root.dataset.recordsUrl, {headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error('Prices not loaded');
      if (!(response.headers.get('content-type') || '').includes('json')) throw new Error('Signed out or not available');
      all = decode(await response.json());
    } catch (e) {
      loading.textContent = ''; container.setAttribute('aria-busy', 'false');
      message.textContent = (e instanceof SyntaxError ? 'Prices not loaded' : e.message) + ' · Reload to try again'; return;
    }
    ready = true; loading.hidden = true; headline(); render();
  }
  load();
})();
