const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
class Node {
  constructor(){this.events={};this.dataset={};this.nodes={};this.groups={};this.textContent='';this.disabled=false;}
  addEventListener(n,f){this.events[n]=f;}
  querySelector(s){return this.nodes[s]||null;}
  querySelectorAll(s){return this.groups[s]||[];}
  fire(n,extra={}){return this.events[n]?.({preventDefault(){this.prevented=true;},...extra});}
}
const source = fs.readFileSync(path.join(__dirname, '../static/web/toni/bw-take.js'), 'utf8');
function build(max, response) {
  const root = new Node(), box = new Node(), output = new Node(), go = new Node(), note = new Node(), stepper = new Node();
  const minus = new Node(), plus = new Node();
  minus.dataset.bcStep = '-1'; plus.dataset.bcStep = '1';
  box.dataset = {max: String(max), identity: JSON.stringify({copy_id: 'copy', item_type: 'P', item_no: 'bl-part', color_id: 11})};
  box.nodes = {'[data-bc-take-value]': output, '[data-bc-take-go]': go, '[data-bc-take-message]': note, '.bc-stepper': stepper};
  box.groups = {'[data-bc-step]': [minus, plus]};
  root.dataset = {saveUrl: '/collection/save/ACTION', csrf: 'token'};
  root.groups = {'[data-bc-take]': [box]};
  const calls = [], store = {}, reloads = [];
  const context = {window: {}, document: {querySelector: s => s === '#bw-collection' ? root : null},
    sessionStorage: {setItem: (k, v) => { store[k] = v; }, getItem: k => store[k]},
    location: {reload: () => reloads.push(1)},
    fetch: async (url, init) => { calls.push({url, body: JSON.parse(init.body)}); return response; }};
  vm.runInNewContext(source, context);
  return {context, output, go, note, minus, plus, stepper, calls, store, reloads};
}
const ok = {ok: true, json: async () => ({message: 'Took 3', event_id: 7})};
const refused = {ok: false, json: async () => ({message: 'Only 2 are left in loose stock'})};

// Bounds: starts at the maximum, never below 1, never above the maximum; no sign in the label.
let t = build(3, ok);
assert.equal(t.output.textContent, '3'); assert.equal(t.go.textContent, 'Take 3');
assert.equal(t.plus.disabled, true); assert.equal(t.minus.disabled, false);
t.minus.fire('click'); t.minus.fire('click');
assert.equal(t.output.textContent, '1'); assert.equal(t.go.textContent, 'Take 1'); assert.equal(t.minus.disabled, true);
t.minus.fire('click'); assert.equal(t.output.textContent, '1');
t.plus.fire('click'); assert.equal(t.output.textContent, '2'); assert.equal(t.go.textContent, 'Take 2');
for (const [key, expect] of [['ArrowUp', '3'], ['ArrowUp', '3'], ['ArrowDown', '2'], ['-', '1'], ['ArrowLeft', '1'], ['+', '2'], ['ArrowRight', '3']]) {
  const e = {key}; t.stepper.fire('keydown', e); assert.equal(t.output.textContent, expect, key);
}
const other = {key: 'x'}; t.stepper.fire('keydown', other); assert.equal(other.prevented, undefined);
assert.equal(t.context.window.BrickTake.clamp(0, 3), 1); assert.equal(t.context.window.BrickTake.clamp(9, 3), 3);
assert.equal(build(1, ok).output.textContent, '1');

(async () => {
  // Post: identity plus the chosen count, csrf, then receipt stored and page reloaded.
  t = build(3, ok); t.minus.fire('click');
  await t.go.fire('click');
  assert.equal(t.calls.length, 1); assert.equal(t.calls[0].url, '/collection/save/take');
  assert.deepEqual(t.calls[0].body, {copy_id: 'copy', item_type: 'P', item_no: 'bl-part', color_id: 11, quantity: 2, csrf_token: 'token'});
  assert.deepEqual(JSON.parse(t.store['bw-collection-receipt']), {message: 'Took 3', event_id: 7});
  assert.equal(t.reloads.length, 1);
  // In flight: keys and clicks change nothing until the answer arrives.
  let release; const slow = {ok: true, json: () => new Promise(r => { release = () => r({message: 'Took 3', event_id: 9}); })};
  t = build(3, slow); t.minus.fire('click');
  const pending = t.go.fire('click');
  t.stepper.fire('keydown', {key: 'ArrowUp'}); t.plus.fire('click');
  assert.equal(t.output.textContent, '2'); assert.equal(t.go.textContent, 'Take 2'); assert.equal(t.plus.disabled, true);
  await t.go.fire('click'); assert.equal(t.calls.length, 1);
  release(); await pending; assert.equal(t.reloads.length, 1);
  // Refused: the server's message is shown, nothing reloads, the button works again.
  t = build(3, refused);
  await t.go.fire('click');
  assert.equal(t.note.textContent, 'Only 2 are left in loose stock'); assert.equal(t.reloads.length, 0);
  assert.equal(t.go.disabled, false); assert.equal(t.store['bw-collection-receipt'], undefined);
  console.log('ok');
})().catch(e => { console.error(e); process.exit(1); });
