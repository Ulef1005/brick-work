/* The copy page's Switch sheet runs against a minimal DOM and a mocked fetch: the "use for new copies" box is never sent ticked for a list
   that cannot be remembered, and a switch keeps its receipt for the page's Undo. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/web/toni/bw-part-list.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const node = (props = {}) => ({dataset: {}, listeners: {}, hidden: false, checked: false, disabled: false, textContent: '', addEventListener(e, fn) { (this.listeners[e] ||= []).push(fn); },
  async fire(e) { for (const fn of this.listeners[e] || []) await fn({preventDefault() {}}); await flush(); }, ...props});
(async () => {
 const sent = [], store = {}, reloads = [];
 const radios = [node({value: 'rebrickable:3', checked: true, dataset: {remember: '1'}}), node({value: 'rebrickable_api', dataset: {remember: '0'}})];
 const box = node({checked: true}), label = node(), go = node({tagName: 'BUTTON'}), status = node();
 const form = node({dataset: {copy: 'copy-1'},
  querySelectorAll: s => s === 'input[name=choice]' ? radios : s === 'button' ? [go] : [],
  querySelector: s => ({'[data-bc-preference]': label, '[name=preference]': box, 'button[type=submit]': go, '[data-bc-form-message]': status})[s] || null});
 const body = node({querySelector: s => s === 'form' ? form : null});
 const dialog = node({querySelector: s => s === '[data-bc-part-body]' ? body : null, showModal() { this.open = true; }, close() { this.open = false; }});
 const opener = node({dataset: {bcPartList: '/collection/copy/copy-1/part-list'}});
 const message = node();
 const root = node({dataset: {saveUrl: '/collection/save/ACTION', csrf: 'csrf'},
  querySelector: s => s === '[data-bc-message]' ? message : null,
  querySelectorAll: s => s === '[data-bc-part-list]' ? [opener] : []});
 const context = {document: {querySelector: s => s === '#bw-collection' ? root : null, getElementById: id => id === 'bc-part-list' ? dialog : null},
  sessionStorage: {getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; }, removeItem: k => { delete store[k]; }},
  location: {reload() { reloads.push(1); }},
  fetch: async (url, options = {}) => {
   if (options.body) { sent.push({url, body: JSON.parse(options.body)}); return {ok: true, json: async () => ({event_id: 7, message: 'Part list switched'})}; }
   return {ok: true, text: async () => '<form></form>'};
  }};
 vm.runInNewContext(source, context);
 await opener.fire('click');
 assert.equal(dialog.open, true);
 // The latest Rebrickable version can be remembered: the ticked box is sent.
 await form.fire('submit');
 assert.equal(sent.at(-1).body.choice, 'rebrickable:3');assert.equal(sent.at(-1).body.preference, true);assert.equal(store['bw-collection-receipt'], JSON.stringify({event_id: 7, message: 'Part list switched'}));
 // A fetched Rebrickable list cannot: the box is hidden, cleared, and never sent ticked.
 radios[0].checked = false;radios[1].checked = true;await radios[1].fire('change');
 assert.equal(label.hidden, true);assert.equal(box.checked, false);
 box.checked = true;                                                    // even if something ticked it again while hidden
 await form.fire('submit');
 assert.equal(sent.at(-1).body.choice, 'rebrickable_api');assert.equal(sent.at(-1).body.preference, false);
 // Back to a list that can be remembered: the box shows again.
 radios[1].checked = false;radios[0].checked = true;await radios[0].fire('change');
 assert.equal(label.hidden, false);
 console.log('Brick Work part list sheet: remember box, hidden and cleared for a fetched list, receipt kept for Undo passed');
})().catch(error => { console.error(error); process.exit(1); });
