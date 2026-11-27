// #401 · The set page's part list edit mode: the tick model, the DOM wiring on a small fake page, the request and the receipt.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/web/toni/bw-part-edit.js'), 'utf8');

class Node {
  constructor(dataset = {}) { this.dataset = {...dataset}; this.attrs = {}; this.events = {}; this.nodes = {}; this.groups = {}; this.textContent = ''; this.disabled = false; this.hidden = false; this.up = {}; this.clicks = 0; }
  addEventListener(name, fn) { this.events[name] = fn; }
  querySelector(s) { return this.nodes[s] || null; }
  querySelectorAll(s) { return this.groups[s] || []; }
  closest(s) { return this.up[s] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  focus() { this.focused = true; }
  append(...kids) { this.kids = (this.kids || []).concat(kids); }
  click() { this.clicks += 1; return this.events.click?.({}); }
  fire(name, extra = {}) { return this.events[name]?.({preventDefault() { this.prevented = true; }, ...extra}); }
}

// Three part lines in two sections: 3001 needs 4 (missing 3 already), 3023 needs 2, 3010 needs 1.
function build({response, draft = null, checkedOn = false} = {}) {
  const root = new Node({saveUrl: '/collection/save/ACTION', csrf: 'token'}), module = new Node({copy: 'copy-1'});
  root.nodes['[data-bc-pl]'] = module;
  const named = {}, add = (key, node) => { named[key] = node; module.nodes[`[data-bc-pl-${key}]`] = node; return node; };
  ['checked-row', 'progress', 'mode', 'bar', 'sum', 'save', 'warn', 'edit', 'cancel', 'receipt', 'rule', 'switch-note'].forEach(k => add(k, new Node()));
  add('warn-text', new Node());
  const sw = add('checked', new Node({copy: 'copy-1'})); sw.attrs['aria-checked'] = String(checkedOn);
  named.rule.dataset.gap = '3'; named.bar.hidden = true; named.mode.hidden = true; named.save.textContent = 'Save missing';
  const globalUndo = new Node(), globalMessage = new Node(); globalUndo.classList = {added: [], add(c) { this.added.push(c); }};
  root.nodes['[data-bc-undo]'] = globalUndo; root.nodes['[data-bc-message]'] = globalMessage;
  const sections = ['Bricks', 'Plates'].map(name => { const el = new Node({bcPartSection: name}); el.nodes['[data-bc-pl-ticked]'] = new Node(); el.nodes['[data-bc-pl-ticked]'].hidden = true; return el; });
  const mkRow = (id, need, missing, section) => {
    const el = new Node({bcPlRow: String(id), bcPlNeed: String(need), bcPlMissing: String(missing)});
    el.up['[data-bc-part-section]'] = section;
    el.nodes['[data-bc-pl-box]'] = new Node(); el.nodes['[data-bc-pl-line]'] = new Node(); el.nodes['[data-bc-pl-line]'].hidden = true;
    el.nodes['[data-bc-pl-count]'] = new Node();
    const minus = new Node({bcPlStep: '-1'}), plus = new Node({bcPlStep: '1'});
    el.groups['[data-bc-pl-step]'] = [minus, plus];
    if (need > 1) el.nodes['.bc-pl-stepper'] = new Node();
    return Object.assign(el, {minus, plus, box: el.nodes['[data-bc-pl-box]'], line: el.nodes['[data-bc-pl-line]'], count: el.nodes['[data-bc-pl-count]']});
  };
  const rows = [mkRow(11, 4, 3, sections[0]), mkRow(12, 2, 0, sections[0]), mkRow(13, 1, 0, sections[1])];
  module.groups['[data-bc-pl-row]'] = rows; module.groups['[data-bc-part-section]'] = sections;
  const calls = [], store = {}, reloads = [];
  if (draft) store['bw-part-edit-draft:copy-1'] = JSON.stringify(draft);
  const context = {
    URLSearchParams, window: {}, document: {querySelector: s => s === '#bw-collection' ? root : null},
    sessionStorage: {setItem: (k, v) => { store[k] = v; }, getItem: k => store[k] ?? null, removeItem: k => { delete store[k]; }},
    location: {pathname: '/collection/item/7', search: '?copy=copy-1&inventory=parts', reload: () => reloads.push(1)},
    fetch: async (url, init) => { calls.push({url, body: JSON.parse(init.body)}); if (response instanceof Error) throw response; return typeof response === 'function' ? response(url) : response; },
  };
  vm.runInNewContext(source, context);
  return {context, root, module, named, rows, sections, calls, store, reloads, globalUndo, globalMessage, sw, tag: i => sections[i].nodes['[data-bc-pl-ticked]']};
}
const plain = value => JSON.parse(JSON.stringify(value));   // results of the sandbox have another Object prototype
const ok = {ok: true, json: async () => ({message: 'Saved · 2 parts marked missing', event_id: 41})};

// The model: a tick starts at 1, a part already missing opens ticked at its count, the stepper stops at what the set needs.
{
  const {createModel, clamp, summary, screenOf} = build().context.window.BrickPartEdit;
  assert.equal(clamp(0, 4), 1); assert.equal(clamp(9, 4), 4); assert.equal(clamp('x', 4), 1); assert.equal(clamp(2, 0), 1);
  const m = createModel([{id: 1, need: 4, missing: 3, section: 'A'}, {id: 2, need: 2, missing: 0, section: 'A'}, {id: 3, need: 1, missing: 0, section: 'B'}, {id: 4, need: 3, missing: 9, section: 'B'}]);
  assert.equal(m.count(1), 3); assert.equal(m.isOn(2), false); assert.equal(m.count(4), 3);            // an impossible stored count opens at the cap
  assert.deepEqual(plain(m.totals()), {parts: 2, pieces: 6}); assert.equal(m.section('A'), 1); assert.equal(m.section('B'), 1);
  assert.equal(m.dirty(), false); assert.deepEqual(plain(m.payload()), []);
  m.step(2, 1); assert.equal(m.count(2), 0);                                                       // not ticked: the stepper does nothing
  m.tick(2); assert.equal(m.count(2), 1); m.step(2, 1); m.step(2, 1); assert.equal(m.count(2), 2); m.step(2, -1); m.step(2, -1); assert.equal(m.count(2), 1);
  m.tick(3); assert.equal(m.count(3), 1); m.step(3, 1); assert.equal(m.count(3), 1);                // needed once: 1 is the cap
  assert.deepEqual(plain(m.totals()), {parts: 4, pieces: 8}); assert.equal(m.section('A'), 2);
  m.tick(1); assert.equal(m.count(1), 0); m.tick(1); assert.equal(m.count(1), 3);                  // unticking and ticking again brings its count back
  m.tick(1);
  assert.deepEqual(plain(m.payload()), [{id: 1, missing: 0}, {id: 2, missing: 1}, {id: 3, missing: 1}]);   // only what changed; a cleared row goes to 0
  m.reset(); assert.equal(m.dirty(), false); assert.equal(m.count(2), 0); assert.equal(m.count(1), 3);
  assert.equal(summary(1, 1), '1 part · 1 piece marked missing'); assert.equal(summary(7, 8), '7 parts · 8 pieces marked missing'); assert.equal(summary(0, 0), '0 parts · 0 pieces marked missing');
  assert.equal(screenOf({pathname: '/collection/item/7', search: '?copy=abc&inventory=parts'}), '/collection/item/7?copy=abc');
  assert.equal(screenOf({pathname: '/collection/item/7', search: '?copy=a%2Fb+c&stock=%C3%A4&colour=4'}), '/collection/item/7?copy=a/b c&stock=ä&colour=4');
  assert.equal(screenOf({pathname: '/collection/item/7', search: ''}), '/collection/item/7');
}

(async () => {
  // Opening the edit mode: the header changes, the bar shows, the pre-ticked row is ticked with its stepper, Save waits for a change.
  let t = build({response: ok});
  assert.equal(t.named.save.disabled, true); assert.equal(t.named.edit.getAttribute('aria-expanded'), null);
  t.named.edit.fire('click');
  assert.equal(t.module.getAttribute('data-bc-pl-editing'), ''); assert.equal(t.named.progress.hidden, true); assert.equal(t.named.mode.hidden, false);
  assert.equal(t.named.bar.hidden, false); assert.equal(t.named.edit.getAttribute('aria-expanded'), 'true'); assert.equal(t.named.cancel.focused, true);
  assert.equal(t.rows[0].box.getAttribute('aria-checked'), 'true'); assert.equal(t.rows[0].line.hidden, false); assert.equal(t.rows[0].count.textContent, '3');
  assert.equal(t.rows[1].box.getAttribute('aria-checked'), 'false'); assert.equal(t.rows[1].line.hidden, true);
  assert.equal(t.named.sum.textContent, '1 part · 3 pieces marked missing'); assert.equal(t.named.save.disabled, true);
  assert.equal(t.tag(0).textContent, '1 ticked'); assert.equal(t.tag(0).hidden, false); assert.equal(t.tag(1).hidden, true);

  // Tick, stepper cap, counts: the section headers and the bar follow.
  t.rows[1].box.fire('click');
  assert.equal(t.rows[1].dataset.bcPlOn, 'true'); assert.equal(t.rows[1].count.textContent, '1'); assert.equal(t.rows[1].minus.disabled, true); assert.equal(t.rows[1].plus.disabled, false);
  t.rows[1].plus.fire('click'); assert.equal(t.rows[1].count.textContent, '2'); assert.equal(t.rows[1].plus.disabled, true);
  t.rows[1].plus.fire('click'); assert.equal(t.rows[1].count.textContent, '2');                      // capped at what the set needs
  t.rows[1].nodes['.bc-pl-stepper'].fire('keydown', {key: 'ArrowDown'}); assert.equal(t.rows[1].count.textContent, '1');
  const other = {key: 'x'}; t.rows[1].nodes['.bc-pl-stepper'].fire('keydown', other); assert.equal(other.prevented, undefined);
  t.rows[2].box.fire('click');
  assert.equal(t.rows[2].plus.disabled, true); assert.equal(t.rows[2].minus.disabled, true);          // needed once: no room either way
  assert.equal(t.tag(0).textContent, '2 ticked'); assert.equal(t.tag(1).textContent, '1 ticked'); assert.equal(t.tag(1).hidden, false);
  assert.equal(t.named.sum.textContent, '3 parts · 5 pieces marked missing'); assert.equal(t.named.save.disabled, false);

  // Ticks live in the model: a row that is paged away or sits in a collapsed section keeps its tick and the section keeps its count.
  t.rows[1].hidden = true; t.sections[0].hidden = true;
  assert.equal(t.tag(0).textContent, '2 ticked');
  t.rows[0].box.fire('click'); assert.equal(t.tag(0).textContent, '1 ticked');                       // a tick on a visible row changes only its own count
  t.rows[1].hidden = false; t.sections[0].hidden = false;
  assert.equal(t.rows[1].box.getAttribute('aria-checked'), 'true'); assert.equal(t.rows[1].count.textContent, '1');
  t.rows[0].box.fire('click'); assert.equal(t.rows[0].count.textContent, '3');                       // back to its stored count

  // Cancel drops every tick without a request.
  t.named.cancel.fire('click');
  assert.equal(t.module.getAttribute('data-bc-pl-editing'), null); assert.equal(t.named.progress.hidden, false); assert.equal(t.named.bar.hidden, true);
  assert.equal(t.rows[1].box.getAttribute('aria-checked'), 'false'); assert.equal(t.rows[2].box.getAttribute('aria-checked'), 'false'); assert.equal(t.calls.length, 0);
  assert.equal(t.tag(1).hidden, true); assert.equal(t.named.edit.focused, true);
  t.rows[1].box.fire('click'); assert.equal(t.rows[1].box.getAttribute('aria-checked'), 'false');   // outside edit mode a click on a box does nothing

  // Save: one request with only what changed, the receipt kept for the page that follows, then a reload.
  t = build({response: ok});
  t.named.edit.fire('click'); t.rows[1].box.fire('click'); t.rows[1].plus.fire('click'); t.rows[0].box.fire('click');
  await t.named.save.fire('click');
  assert.equal(t.calls.length, 1); assert.equal(t.calls[0].url, '/collection/save/mark-missing');
  assert.deepEqual(t.calls[0].body, {copy_id: 'copy-1', rows: [{id: 11, missing: 0}, {id: 12, missing: 2}], csrf_token: 'token'});
  assert.deepEqual(JSON.parse(t.store['bw-collection-receipt']), {message: 'Saved · 2 parts marked missing', event_id: 41, screen: '/collection/item/7?copy=copy-1'});
  assert.equal(t.reloads.length, 1);
  await t.named.save.fire('click'); assert.equal(t.calls.length, 1);                                  // in flight: a second press sends nothing

  // A failed save keeps the ticks and offers Retry; the retry sends the same request.
  let fail = true;
  t = build({response: () => fail ? {ok: false, json: async () => ({message: 'Choose a count from 0 to 4'})} : {ok: true, json: async () => ({message: 'Saved', event_id: 5})}});
  t.named.edit.fire('click'); t.rows[2].box.fire('click');
  await t.named.save.fire('click');
  assert.equal(t.named.warn.hidden, false); assert.equal(t.named['warn-text'].textContent, 'Choose a count from 0 to 4. Your ticks are kept; press Retry.');
  assert.equal(t.named.save.textContent, 'Retry'); assert.equal(t.named.save.disabled, false); assert.equal(t.rows[2].box.getAttribute('aria-checked'), 'true'); assert.equal(t.reloads.length, 0);
  fail = false; await t.named.save.fire('click');
  assert.equal(t.calls.length, 2); assert.deepEqual(t.calls[1].body, t.calls[0].body); assert.equal(t.reloads.length, 1);
  t = build({response: new TypeError('Failed to fetch')});
  t.named.edit.fire('click'); t.rows[2].box.fire('click'); await t.named.save.fire('click');
  assert.equal(t.named['warn-text'].textContent, 'The connection dropped. Your ticks are kept; press Retry.'); assert.equal(t.reloads.length, 0);

  // The page's own receipt line (message and Undo) moves into the slot above the list: one receipt, where the list is.
  t = build();
  assert.deepEqual(t.named.receipt.kids, [t.globalMessage, t.globalUndo]); assert.deepEqual(plain(t.globalUndo.classList.added), ['bc-pl-link']);

  // Set is checked outside edit mode: saved at once with its own request and receipt, then the page reloads.
  t = build({response: {ok: true, json: async () => ({message: 'Set is checked · on', event_id: 9})}});
  await t.sw.fire('click');
  assert.equal(t.calls.length, 1); assert.equal(t.calls[0].url, '/collection/save/set-checked'); assert.deepEqual(plain(t.calls[0].body), {copy_id: 'copy-1', wanted: true, csrf_token: 'token'});
  assert.deepEqual(JSON.parse(t.store['bw-collection-receipt']), {message: 'Set is checked · on', event_id: 9, screen: '/collection/item/7?copy=copy-1'});
  assert.equal(t.reloads.length, 1); assert.equal(t.store['bw-part-edit-draft:copy-1'], undefined);
  t = build({checkedOn: true, response: {ok: true, json: async () => ({message: 'Set is checked · off', event_id: 10})}});
  await t.sw.fire('click'); assert.equal(t.calls[0].body.wanted, false);
  // In edit mode the unsaved ticks go into a draft for that reload; the switch itself never sends them.
  t = build({response: {ok: true, json: async () => ({message: 'Set is checked · on', event_id: 9})}});
  t.named.edit.fire('click'); t.rows[1].box.fire('click'); t.rows[1].plus.fire('click'); t.rows[0].box.fire('click');
  await t.sw.fire('click');
  assert.equal(t.calls.length, 1); assert.equal(t.calls[0].url, '/collection/save/set-checked'); assert.equal(t.reloads.length, 1);
  assert.deepEqual(JSON.parse(t.store['bw-part-edit-draft:copy-1']), {counts: {11: 0, 12: 2}});
  // After the reload the draft puts the ticks back in edit mode (and is used up); an impossible count is capped, an unknown line ignored.
  t = build({draft: {counts: {11: 0, 12: 2, 13: 7, 99: 1}}});
  assert.equal(t.module.getAttribute('data-bc-pl-editing'), ''); assert.equal(t.named.progress.hidden, true); assert.equal(t.named.bar.hidden, false);
  assert.equal(t.rows[0].box.getAttribute('aria-checked'), 'false'); assert.equal(t.rows[1].count.textContent, '2'); assert.equal(t.rows[2].count.textContent, '1');
  assert.equal(t.named.sum.textContent, '2 parts · 3 pieces marked missing'); assert.equal(t.named.save.disabled, false); assert.equal(t.store['bw-part-edit-draft:copy-1'], undefined);
  // A refused switch says why and stays as it was.
  t = build({response: {ok: false, json: async () => ({message: 'Nope'})}});
  await t.sw.fire('click'); assert.equal(t.named['switch-note'].textContent, 'Nope'); assert.equal(t.sw.getAttribute('aria-checked'), 'false'); assert.equal(t.sw.disabled, false); assert.equal(t.reloads.length, 0);
  // Rendering another inventory hides all editing chrome without dropping the draft.
  t = build(); t.named.edit.fire('click'); t.rows[1].box.fire('click');
  for (const inventory of ['figures', 'extras', 'parts']) {
    t.module.dataset.inventory = inventory; t.module.bcPartEditVisibility();
    assert.equal(t.named.progress.hidden, true);
    assert.equal(t.named['checked-row'].hidden, inventory !== 'parts');
    assert.equal(t.named['switch-note'].hidden, inventory !== 'parts');
    assert.equal(t.named.mode.hidden, inventory !== 'parts');
    assert.equal(t.named.bar.hidden, inventory !== 'parts');
    assert.equal(t.rows[1].box.getAttribute('aria-checked'), 'true');
  }
  t.named.edit.fire('click'); // a repeated Edit cannot reset ticks
  assert.equal(t.rows[1].box.getAttribute('aria-checked'), 'true');
  t.module.dataset.inventory = 'extras'; t.module.bcPartEditVisibility();
  t.named.cancel.fire('click'); assert.equal(t.named.progress.hidden, true);
  t.module.dataset.inventory = 'parts'; t.module.bcPartEditVisibility();
  assert.equal(t.named.progress.hidden, false); assert.equal(t.named.bar.hidden, true);

  // #507: on a set copy the progress, the editing bar and the checked row sit in the copy head, outside the tabbed module:
  // on another tab while editing, the bar with Cancel stays (it is the only way out of the mode there); the module's save bar hides.
  t = build(); const head = [t.named.progress, t.named.mode, t.named['checked-row']]; t.module.contains = n => !head.includes(n);
  t.named.edit.fire('click');
  t.module.dataset.inventory = 'figures'; t.module.bcPartEditVisibility();
  assert.equal(t.named.mode.hidden, false); assert.equal(t.named.progress.hidden, true); assert.equal(t.named['checked-row'].hidden, false); assert.equal(t.named.bar.hidden, true);
  t.named.cancel.fire('click');
  assert.equal(t.named.mode.hidden, true); assert.equal(t.named.progress.hidden, false);

  // A login redirect returning HTML with 200 must keep ticks and write no receipt.
  const html = {ok: true, json: async () => { throw new SyntaxError('HTML'); }};
  t = build({response: html}); t.named.edit.fire('click'); t.rows[1].box.fire('click');
  await t.named.save.fire('click');
  assert.equal(t.rows[1].box.getAttribute('aria-checked'), 'true');
  assert.equal(t.named.save.textContent, 'Retry'); assert.equal(t.named.warn.hidden, false);
  assert.equal(t.reloads.length, 0); assert.equal(t.store['bw-collection-receipt'], undefined);
  await t.sw.fire('click');
  assert.match(t.named['switch-note'].textContent, /unreadable/);
  assert.equal(t.sw.disabled, false); assert.equal(t.reloads.length, 0);
  assert.equal(t.store['bw-collection-receipt'], undefined);

  // The real template keeps the receipt outside the panel hidden on Extras.
  const template = fs.readFileSync(path.join(__dirname, '../templates/web/toni/brickwork/collection_modules.html'), 'utf8');
  assert(template.indexOf('data-bc-pl-receipt') < template.indexOf('<div data-bc-tab-inventory>'));
  const collection = fs.readFileSync(path.join(__dirname, '../static/web/toni/bw-collection.js'), 'utf8');
  assert(collection.includes('list.bcPartEditVisibility?.();'));
  // Figure actions use the same draft and restore path as the switch.
  const takeSource = fs.readFileSync(path.join(__dirname, '../static/web/toni/bw-take.js'), 'utf8');
  for (const action of ['found-one', 'found-all', 'take']) {
    t = build({response: ok});
    t.named.edit.fire('click'); t.rows[1].box.fire('click'); t.rows[1].plus.fire('click'); t.rows[0].box.fire('click');
    t.module.dataset.inventory = 'figures'; t.module.bcPartEditVisibility();
    const box = new Node({identity: JSON.stringify({copy_id: 'copy-1', token: 'f:1'}), max: '1'});
    const button = new Node(), note = new Node();
    if (action === 'take') {
      box.nodes['[data-bc-take-value]'] = new Node(); box.nodes['[data-bc-take-go]'] = button;
      t.root.groups['[data-bc-take]'] = [box];
    } else {
      button.dataset.identity = box.dataset.identity; button.parentElement = box;
      box.nodes['[data-bc-found-message]'] = note;
      box.groups['[data-bc-found-one], [data-bc-found-all]'] = [button];
      t.root.groups['[data-bc-' + action + ']'] = [button];
    }
    t.context.location.search = '?copy=copy%2D1';
    vm.runInNewContext(takeSource, t.context);
    await button.fire('click');
    assert.equal(t.reloads.length, 1);
    assert.equal(JSON.parse(t.store['bw-collection-receipt']).screen, '/collection/item/7?copy=copy-1');
    const draft = JSON.parse(t.store['bw-part-edit-draft:copy-1']);
    assert.deepEqual(draft, {counts: {11: 0, 12: 2}});
    const restored = build({draft});
    assert.equal(restored.rows[0].box.getAttribute('aria-checked'), 'false');
    assert.equal(restored.rows[1].count.textContent, '2');
    assert.equal(restored.named.mode.hidden, false);
  }
  console.log('part edit runtime ok');
})().catch(error => { console.error(error); process.exit(1); });
