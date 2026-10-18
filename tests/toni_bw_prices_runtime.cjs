// Prices runtime: pure functions (decode, filter, sort, pager, row and details markup) and the interactive page
// against a minimal DOM with a fake fetch. Run from the repository root: node tests/toni_bw_prices_runtime.cjs
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const script = fs.readFileSync('static/web/toni/bw-prices.js', 'utf8'), formatting = fs.readFileSync('static/web/toni/formatting.js', 'utf8');
const FIELDS = 'type number name colour color_id rgb ink image unresolved owned wanted stale price listings age observed price_stale'.split(' ');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const types = {S: 'Sets', M: 'Minifigures', P: 'Parts', '?': 'Placeholders'};
const record = (o = {}) => FIELDS.map(f => (f in o ? o[f] : ({type: 'S', number: '1', name: 'Name', colour: '', color_id: null, rgb: null, ink: null, image: null, unresolved: false,
  owned: false, wanted: false, stale: false, price: '€1.00', listings: false, age: '8 Oct', observed: '2026-10-08', price_stale: false})[f]));

// ---- pure functions: the script is loaded with no #bw-planning, so it only exports its helpers ----
function pure() {
  const window = {}, context = {window, document: {querySelector: () => null}, Intl, JSON, Number, String, Set, Math, Array, Object};
  vm.createContext(context); vm.runInContext(formatting, context); vm.runInContext(script, context);
  return window.BrickPrices;
}
const deq = (a, b) => assert.equal(JSON.stringify(a), JSON.stringify(b));  // results cross a vm realm
const B = pure();
{
  const data = {fields: FIELDS, rows: [
    record({number: '10', name: 'Zed', stale: true, owned: true}), record({number: '9', name: 'Alpha', type: 'P', colour: 'Red', color_id: 5, rgb: 'C91A09', ink: '#FAFAF8'}),
    record({number: '9', name: 'Alpha', type: 'P', colour: 'Black', color_id: 0, rgb: '05131D', ink: '#FAFAF8', observed: '', age: 'Age not recorded', price: null}),
    record({number: 'x?', name: 'Odd <b>"', type: '?', unresolved: true, wanted: true, price: '€1,234.50', listings: true, price_stale: true})]};
  const rows = B.decode(data);
  assert.equal(rows.length, 4); assert.equal(rows[1].colour, 'Red'); assert.ok(rows[0].hay.includes('zed'));
  // Natural number order; equal numbers fall back to colour; descending flips it.
  deq(B.sortRows(rows, 'number', false).map(r => r.number + r.colour), ['9Black', '9Red', '10', 'x?']);
  deq(B.sortRows(rows, 'number', true).map(r => r.number + r.colour), ['x?', '10', '9Black', '9Red']);
  deq(B.sortRows(rows, 'name', false).map(r => r.name)[0], 'Alpha');
  // Age: oldest first, undated rows last in either direction.
  assert.equal(B.sortRows(rows, 'age', false).at(-1).observed, ''); assert.equal(B.sortRows(rows, 'age', true).at(-1).observed, '');
  deq(B.filterRows(rows, {query: 'RED'}).map(r => r.colour), ['Red']);
  assert.equal(B.filterRows(rows, {type: 'P'}).length, 2);
  deq(B.filterRows(rows, {stale: 'true'}).map(r => r.number), ['10']);
  assert.equal(B.filterRows(rows, {stale: 'false'}).length, 3);
  deq(B.filterRows(rows, {collection: 'owned'}).map(r => r.number), ['10']);
  deq(B.filterRows(rows, {collection: 'wanted', type: '?'}).map(r => r.number), ['x?']);
  const cfg = {types, itemBase: '/collection/item/TYPE/NUMBER', imageBase: '/manage/images/0', unresolvedUrl: '/manage/unresolved', editable: true};
  const html = rows.map(r => B.rowHtml(cfg, r));
  // The row keeps the five blocks the CSS grid expects, in reading order.
  assert.match(html[0], /^<article class="bp-row" tabindex="0" data-bp-row data-key="[^"]+"><div class="bp-identity">.*<div class="bp-kind">.*<div class="bp-values">.*<div class="bp-ages mono secondary">/s);
  assert.match(html[0], /<span class="bc-status">Sets<\/span><span class="bc-status">Owned<\/span>/);
  assert.match(html[0], /data-bp-refresh='\[&quot;S&quot;,&quot;10&quot;\]'>Update<\/button>/);
  assert.match(html[0], /<summary>Details<\/summary>/); assert.doesNotMatch(html[0], /<details[^>]* open/);
  assert.match(html[0], /<span class="bp-desktop-age">8 Oct<\/span>/);
  assert.match(html[0], /href="\/collection\/item\/S\/10"/);
  assert.match(html[1], /href="\/collection\/item\/P\/9\?colour=5"/); assert.match(html[1], /class="bc-colour" style="background:#C91A09;color:#FAFAF8">Red/);
  // No price: "no sales", no age. Unresolved: no refresh button, the unresolved link instead; placeholder wording.
  assert.match(html[2], /<span>no sales<\/span>/); assert.doesNotMatch(html[2], /bp-desktop-age|bp-short-price/);
  assert.doesNotMatch(html[3], /data-bp-refresh/); assert.match(html[3], /href="\/manage\/unresolved">Unresolved figures/); assert.match(html[3], /Placeholder/);
  // Money is shown as the server wrote it; listings are labelled; a stale price says so on one line.
  assert.match(html[3], /bp-short-price">listings €1,234\.50<small class="bp-phone-age">8 Oct · stale<\/small>/);
  assert.doesNotMatch(html[3], /<b>|"Odd <b/); assert.match(html[3], /Odd\u00a0&lt;b&gt;&quot;/);
  assert.doesNotMatch(B.rowHtml({...cfg, editable: false}, rows[0]), /data-bp-refresh/);
  // The picture markup stays a single anchor with one lazy image.
  const picture = B.rowHtml(cfg, B.decode({fields: FIELDS, rows: [record({image: 42, name: 'Boat', colour: 'Red'})]})[0]);
  assert.match(picture, /<a href="\/manage\/images\/42"><img src="\/manage\/images\/42\?w=320" srcset="\/manage\/images\/42\?w=320 320w, \/manage\/images\/42\?w=640 640w" sizes="160px" data-full="\/manage\/images\/42" alt="Boat · Red" loading="lazy"><\/a>/);
  // Names keep a non-breaking last word.
  assert.match(B.rowHtml(cfg, B.decode({fields: FIELDS, rows: [record({name: 'Plate 2 x 4'})]})[0]), /<strong>Plate 2 x 4<\/strong>|<strong>Plate 2 x 4<\/strong>|<strong>Plate 2 x 4<\/strong>|<strong>Plate 2 x 4<\/strong>/);
  const detail = B.detailsHtml(cfg, rows[0], {context: 'Castle · 2001', selected: 'Used · avg · €12.00', conditions: ['Used · €12.00 · 8 Oct'], empty: false,
    groups: [{label: 'Market · BrickLink', quotes: [{label: 'Used', head: '€12.00 · avg', meta: '8 Oct · bricklink', range: 25, min: '€5.00', max: '€20.00', aria: 'Minimum €5.00'}]}]});
  assert.match(detail, /^<p class="bp-selected-quote">Selected price · Used · avg · €12\.00<\/p><p>Castle · 2001 · Sets · Owned<\/p>/);
  assert.match(detail, /<h3>Market · BrickLink<\/h3><div class="bp-quote">.*<i style="left:25%"><\/i>.*min €5\.00.*max €20\.00/s);
  assert.match(B.detailsHtml(cfg, rows[0], {context: '', selected: null, conditions: [], groups: [], empty: true}), /<p>no sales<\/p>/);
  // Pager: first, last, current and neighbours; one skipped page shows as its number, longer gaps as an ellipsis.
  deq(B.pageItems(3, 1), [1, 2, 3]); deq(B.pageItems(10, 1), [1, 2, '…', 10]); deq(B.pageItems(10, 5), [1, '…', 4, 5, 6, '…', 10]);
  deq(B.pageItems(10, 3), [1, 2, 3, 4, '…', 10]); assert.equal(B.rangeText(40, 3), '31 to 40 of 40'); assert.equal(B.rangeText(0, 1), ''); assert.equal(B.PAGE, 15);
}

// ---- the interactive page ----
class El {
  constructor(tag = 'DIV', dataset = {}) { this.tagName = tag; this.dataset = {...dataset}; this.events = {}; this.attrs = {}; this.children = []; this.hidden = false; this.disabled = false; this.value = ''; this.textContent = ''; this.className = ''; this.innerHTML = ''; }
  addEventListener(name, fn) { (this.events[name] ||= []).push(fn); }
  async fire(name, extra = {}) { for (const fn of this.events[name] || []) await fn({target: this, currentTarget: this, preventDefault() {}, ...extra}); }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  append(...n) { this.children.push(...n); } replaceChildren(...n) { this.children = n; } after(n) { this.next = n; } focus() { this.focused = true; }
  querySelector(s) { return this.nodes?.[s] || null; } querySelectorAll(s) { return this.groups?.[s] || []; }
  closest(s) { return this.closestMap?.[s] || null; } matches(s) { return this.selfMatches === s; } scrollIntoView() {}
  get selectedOptions() { return [this.options?.find(o => o.value === this.value) || {textContent: this.value}]; }
}
function page({rows, kind = '', editable = true, stored = null, fetcher}) {
  const nodes = {};
  const make = (sel, tag, dataset) => nodes[sel] = new El(tag, dataset);
  const root = new El('DIV', {screen: 'prices', types: JSON.stringify(types), itemBase: '/collection/item/TYPE/NUMBER', imageBase: '/manage/images/0', unresolvedUrl: '/manage/unresolved', editable: String(editable),
    kind, saveUrl: '/planning/action/ACTION', recordsUrl: '/planning/prices/records', detailsUrl: '/planning/prices/details', csrf: 'tok'});
  const container = make('[data-bp-rows]'), search = make('[data-bp-search]', 'INPUT'), sort = make('[data-bp-sort]', 'SELECT'), order = make('[data-bp-order]', 'SELECT');
  sort.value = 'number'; order.value = 'asc';
  for (const s of ['[data-bp-message]', '[data-bp-undo]', '[data-bp-count]', '[data-bp-empty]', '[data-bp-loading]', '#bp-filters', '[data-bp-chips]', '[data-bp-refresh-all]', '[data-bp-sort-panel]', '[data-bp-title]', '[data-bp-subtitle]', '[data-bp-stale-count]', '[data-bp-lookup]']) make(s);
  nodes['[data-bp-undo]'].hidden = true; nodes['[data-bp-empty]'].hidden = true;
  nodes['[data-bp-chips]'].children = [];
  const mkLabel = text => ({firstChild: {textContent: text}});
  const filters = ['type', 'stale', 'collection'].map(k => { const c = new El('SELECT', {bpFilter: k}); c.closestMap = {label: mkLabel({type: 'Type', stale: 'Age', collection: 'Collection'}[k])};
    c.options = {type: [{value: '', textContent: 'All'}, {value: 'S', textContent: 'Sets'}, {value: 'P', textContent: 'Parts'}], stale: [{value: '', textContent: 'All'}, {value: 'true', textContent: 'Stale'}, {value: 'false', textContent: 'Fresh'}],
      collection: [{value: '', textContent: 'All'}, {value: 'owned', textContent: 'Owned'}, {value: 'wanted', textContent: 'Wanted'}]}[k]; return c; });
  const chips = [['all', ''], ['stale', ''], ['type', 'S'], ['type', 'P'], ['collection', 'owned'], ['collection', 'wanted']].map(([k, v]) => new El('BUTTON', {bpChip: k, ...(v ? {value: v} : {})}));
  root.nodes = Object.fromEntries([...Object.entries(nodes), ['[data-bp-chip=stale]', chips[1]]]);
  root.groups = {'[data-bp-filter]': filters, '[data-bp-chip]': chips, '[data-bp-filters]': [], '[data-bp-sort-open]': [], '[data-bp-chip=collection]': chips.slice(4)};
  const store = new Map(stored ? Object.entries(stored) : []);
  const calls = [];
  const context = {
    window: {adminShell: {open() {}}}, Intl, JSON, Number, String, Set, Math, Array, Object, URLSearchParams, Promise, setTimeout, clearTimeout, console,
    document: {querySelector: s => s === '#bw-planning' ? root : null, getElementById: () => null, addEventListener() {}, createElement: tag => new El(tag.toUpperCase())},
    sessionStorage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k)}, location: {reload() { calls.push('reload'); }},
    fetch: async (url, init) => { calls.push([url, init]); const r = await fetcher(url, init); return {headers: {get: () => 'application/json'}, ...r}; }};
  vm.createContext(context); vm.runInContext(formatting, context); vm.runInContext(script, context);
  return {root, nodes, container, search, sort, order, filters, chips, calls, store, context};
}
const rowsOf = html => (html.match(/data-bp-row/g) || []).length;
const keys = html => [...html.matchAll(/data-key="([^"]+)"/g)].map(m => m[1]);
(async () => {
  const many = Array.from({length: 40}, (_, i) => record({number: String(100 + i), name: 'Item ' + i, type: i % 2 ? 'P' : 'S', colour: i % 2 ? 'Red' : '', color_id: i % 2 ? 5 : null, stale: i < 7, owned: i < 10, wanted: i >= 30}));
  many.push(record({number: '?1', type: '?', unresolved: true, name: 'Lost', price: null}));
  const detailBody = {context: 'Castle', selected: 'Used · €1.00', conditions: ['Used · €1.00 · 8 Oct'], groups: [], empty: false};
  const fetcher = (url, init) => {
    if (url === '/planning/prices/records') return {ok: true, json: async () => ({fields: FIELDS, rows: many})};
    if (url.startsWith('/planning/prices/details')) return {ok: true, json: async () => detailBody};
    if (url === '/planning/action/refresh') return {ok: true, json: async () => ({message: 'Price refresh queued', jobs: [1]})};
    return {ok: false, json: async () => ({message: 'no'})};
  };
  let p = page({rows: many, fetcher});
  await sleep(20);
  // Load: one records request, 15 rows on page 1, a pager of 3 pages, the count text as a range, the stale chip and the headline.
  assert.equal(p.calls.filter(c => c[0] === '/planning/prices/records').length, 1); assert.equal(p.calls.length, 1);
  assert.equal(rowsOf(p.container.innerHTML), 15); assert.equal(p.nodes['[data-bp-count]'].textContent, '1 to 15 of 41');
  assert.equal(p.nodes['[data-bp-loading]'].hidden, true); assert.equal(p.container.attrs['aria-busy'], 'false');
  const nav = p.container.next; assert.equal(nav.className, 'bc-pager'); assert.equal(nav.hidden, false); assert.equal(nav.children[3].textContent, '1 to 15 of 41');
  deq(nav.children[1].children.map(b => b.textContent), ['1', '2', '3']);
  assert.equal(nav.children[0].disabled, true); assert.equal(nav.children[2].disabled, false);
  assert.equal(p.chips[1].disabled, false); assert.equal(p.nodes['[data-bp-stale-count]'].textContent, '7'); assert.equal(p.nodes['[data-bp-title]'].textContent, '7 prices are stale');
  assert.equal(p.nodes['[data-bp-subtitle]'].textContent, 'Update one, or the whole filter');
  assert.equal(p.chips[4].disabled, false); assert.equal(p.chips[5].disabled, false);
  assert.equal(p.nodes['[data-bp-refresh-all]'].disabled, false);
  // Pager: next page shows the next 15, the last page the remainder (41 = 15 + 15 + 11).
  const first = keys(p.container.innerHTML);
  await nav.children[2].fire('click'); assert.equal(rowsOf(p.container.innerHTML), 15); assert.notDeepEqual(keys(p.container.innerHTML), first);
  assert.equal(p.container.next.children[3].textContent, '16 to 30 of 41');
  await p.container.next.children[1].children.at(-1).fire('click'); assert.equal(rowsOf(p.container.innerHTML), 11);
  assert.equal(p.container.next.children[2].disabled, true);
  // Search resets to page 1, is debounced, matches number, name and colour, and shows a removable chip.
  p.search.value = 'item 3'; await p.search.fire('input'); await sleep(200);
  assert.equal(rowsOf(p.container.innerHTML), 11); assert.equal(p.container.next.hidden, true);  // Item 3, 30..39 = 11 rows
  assert.equal(p.nodes['[data-bp-chips]'].children.length, 1); assert.equal(p.nodes['[data-bp-chips]'].children[0].textContent, 'Search: item 3 ×');
  await p.nodes['[data-bp-chips]'].children[0].fire('click'); assert.equal(p.search.value, ''); assert.equal(rowsOf(p.container.innerHTML), 15);
  // Chips: Stale, type, Owned/Wanted; All clears; the filter panel selects follow.
  await p.chips[1].fire('click'); assert.equal(p.nodes['[data-bp-count]'].textContent, '1 to 7 of 7'); assert.equal(p.chips[1].attrs['aria-pressed'], 'true'); assert.equal(p.chips[0].attrs['aria-pressed'], 'false');
  assert.equal(p.filters[1].value, 'true');
  await p.chips[1].fire('click'); assert.equal(p.chips[1].attrs['aria-pressed'], 'false');
  await p.chips[3].fire('click'); assert.equal(p.nodes['[data-bp-count]'].textContent, '1 to 15 of 20'); assert.equal(p.filters[0].value, 'P');
  await p.chips[4].fire('click'); assert.equal(rowsOf(p.container.innerHTML), 5);  // owned parts: odd i below 10
  await p.chips[0].fire('click'); assert.equal(p.nodes['[data-bp-count]'].textContent, '1 to 15 of 41');
  p.filters[2].value = 'wanted'; await p.filters[2].fire('change'); assert.equal(p.nodes['[data-bp-count]'].textContent, '1 to 10 of 10');
  p.filters[2].value = ''; await p.filters[2].fire('change');
  p.filters[0].value = 'S'; await p.filters[0].fire('change'); p.filters[1].value = 'false'; await p.filters[1].fire('change');
  assert.equal(p.nodes['[data-bp-count]'].textContent, '1 to 15 of 16');  // even i: 20 sets, 4 of them stale
  assert.equal(p.nodes['[data-bp-chips]'].children.length, 2);
  await p.chips[0].fire('click'); assert.equal(p.nodes['[data-bp-count]'].textContent, '1 to 15 of 41'); assert.equal(p.filters[0].value, '');
  // Sort: name descending puts "Lost" first among names, number sort is natural.
  p.sort.value = 'name'; p.order.value = 'desc'; await p.sort.fire('change'); assert.match(p.container.innerHTML, /^<article[^>]*>.*?<strong>Lost<\/strong>/s);
  p.sort.value = 'number'; p.order.value = 'asc'; await p.sort.fire('change');
  assert.match(p.container.innerHTML, /<span class="mono">100<span/);
  // Details load on open, once, scoped to the identity; a closed disclosure fetches nothing.
  const open = {open: true, dataset: {}, matches: s => s === '[data-bp-details]', querySelector: () => body, closest: () => ({dataset: {key: keys(p.container.innerHTML)[2]}})};
  const body = new El(); const before = p.calls.length;
  await p.container.fire('toggle', {target: open});
  assert.equal(p.calls.length, before + 1); const url = new URL('http://x' + p.calls.at(-1)[0]); assert.equal(url.pathname, '/planning/prices/details');
  assert.equal(url.searchParams.get('kind'), 'P'); assert.equal(url.searchParams.get('number'), '101'); assert.equal(url.searchParams.get('colour'), '5');
  assert.match(body.innerHTML, /Selected price · Used · €1\.00/); assert.equal(open.dataset.loaded, '1');
  await p.container.fire('toggle', {target: open}); assert.equal(p.calls.length, before + 1);
  await p.container.fire('toggle', {target: {...open, open: false, dataset: {}}}); assert.equal(p.calls.length, before + 1);
  // Per-row refresh posts the one identity with the token; the bulk button posts each unique, resolved identity of the filtered rows.
  const button = new El('BUTTON', {bpRefresh: JSON.stringify(['S', '100'])});
  await p.container.fire('click', {target: Object.assign(button, {closest: s => s === '[data-bp-refresh]' ? button : null})}); await sleep(5);
  let post = p.calls.at(-1); assert.equal(post[0], '/planning/action/refresh'); deq(JSON.parse(post[1].body), {items: [['S', '100']], csrf_token: 'tok'});
  assert.equal(p.nodes['[data-bp-message]'].textContent, 'Price refresh queued'); assert.equal(button.disabled, false);
  await p.nodes['[data-bp-refresh-all]'].fire('click'); await sleep(5);
  post = p.calls.at(-1); const sent = JSON.parse(post[1].body).items;
  assert.equal(sent.length, 40); assert.ok(!sent.some(i => i[0] === '?')); assert.equal(new Set(sent.map(i => i.join('|'))).size, 40);
  await p.chips[1].fire('click'); await p.nodes['[data-bp-refresh-all]'].fire('click'); await sleep(5);
  assert.equal(JSON.parse(p.calls.at(-1)[1].body).items.length, 7);
  // Without edit rights the page has no refresh buttons in rows.
  const viewer = page({rows: many, editable: false, fetcher}); await sleep(20);
  assert.doesNotMatch(viewer.container.innerHTML, /data-bp-refresh/);
  // ?kind= pre-selects the type, and a failed load says so without rows.
  const kind = page({rows: many, kind: 'P', fetcher}); await sleep(20);
  assert.equal(kind.nodes['[data-bp-count]'].textContent, '1 to 15 of 20'); assert.equal(kind.filters[0].value, 'P');
  const failed = page({rows: [], fetcher: () => ({ok: false, json: async () => ({})})}); await sleep(20);
  assert.match(failed.nodes['[data-bp-message]'].textContent, /Prices not loaded/); assert.equal(rowsOf(failed.container.innerHTML), 0);
  // An empty store shows the empty text, no pager, and keeps Refresh results disabled.
  const none = page({rows: [], fetcher: () => ({ok: true, json: async () => ({fields: FIELDS, rows: []})})}); await sleep(20);
  assert.equal(none.nodes['[data-bp-empty]'].hidden, false); assert.equal(none.container.next.hidden, true); assert.equal(none.nodes['[data-bp-refresh-all]'].disabled, true);
  assert.equal(none.chips[1].disabled, true); assert.equal(none.chips[4].disabled, true);
  console.log('prices runtime ok');
})().catch(e => { console.error(e); process.exit(1); });
