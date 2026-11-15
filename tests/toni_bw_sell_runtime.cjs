// Sell this copy runtime (#53): the preview's copy (clipboard, selection fallback, failure), Edited and Reset to generated, and Missing parts opening at 1024.
// A minimal DOM, no browser. Run from the repository root: node tests/toni_bw_sell_runtime.cjs
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const sell = fs.readFileSync('static/web/toni/bw-sell.js', 'utf8'), tokens = fs.readFileSync('static/web/toni/bw-tokens.js', 'utf8');

class El {
  constructor(attrs = {}) { this.listeners = {}; this.textContent = ''; this.hidden = false; this.disabled = false; this.open = false; this.children = []; Object.assign(this, attrs); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async fire(type) { for (const fn of this.listeners[type] || []) await fn({type}); }
  contains(el) { return el === this || this.children.includes(el); }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  showModal() { this.open = true; }
}
const GENERATED = '1000-1 Syn Castle Keep · 1990\nAsking price: €51.90';

// A section like the template's: the card's copy button and status, the sheet with its field, Edited, Reset, status and copy button; one deduction row.
function page() {
  const field = new El({value: GENERATED, defaultValue: GENERATED});
  const cardButton = new El(), sheetButton = new El(), reset = new El(), edited = new El({hidden: true});
  const cardStatus = new El(), sheetStatus = new El(), dis = new El(), sheet = new El();
  sheet.children = [field, sheetButton, reset, edited, sheetStatus];
  const all = {
    '[data-bc-sell-text]': [field], '[data-bc-sell-sheet]': [sheet], '[data-bc-sell-edited]': [edited], '[data-bc-sell-reset]': [reset],
    '[data-bc-sell-status]': [cardStatus, sheetStatus], '[data-bc-sell-copy]': [cardButton, sheetButton], '[data-bc-sell-dis]': [dis]};
  const section = {querySelector: s => (all[s] || [])[0] || null, querySelectorAll: s => all[s] || []};
  return {section, field, cardButton, sheetButton, reset, edited, cardStatus, sheetStatus, dis, sheet};
}

function load({clipboard, execCommand, wide = false} = {}) {
  const body = {appended: [], appendChild(el) { this.appended.push(el); }};
  const document = {body, execCommand, createElement: () => Object.assign(new El(), {style: {}, setAttribute() {}, remove() { document.removed = true; }}), addEventListener() {}};
  const window = {document, navigator: {clipboard}, matchMedia: () => ({matches: wide}), addEventListener() {}};
  const context = {window, document, navigator: window.navigator, console, Promise, Set, Math, Array, Object, JSON, String, Number};
  vm.createContext(context); vm.runInContext(tokens, context); vm.runInContext(sell, context);
  const env = {document, clipboard, matchMedia: window.matchMedia, copyText: window.BrickTokenCopy};
  return {B: window.BrickSell, env, document};
}

(async () => {
  // The clipboard path: the text as it is in the field, Copied beside the button that was pressed.
  let written = null;
  let {B, env} = load({clipboard: {writeText: async t => { written = t; }}});
  let p = page(); B.wire(p.section, env);
  await p.cardButton.fire('click');
  assert.equal(written, GENERATED); assert.equal(p.cardStatus.textContent, 'Copied'); assert.equal(p.sheetStatus.textContent, '');
  await p.sheetButton.fire('click');
  assert.equal(p.sheetStatus.textContent, 'Copied'); assert.equal(p.cardStatus.textContent, '');

  // Editing shows Edited and clears Copied; the edited words are what is copied; Reset puts the generated text back and hides Edited.
  p.field.value = '1000-1 Syn Castle Keep'; await p.field.fire('input');
  assert.equal(p.edited.hidden, false); assert.equal(p.sheetStatus.textContent, '');
  await p.sheetButton.fire('click'); assert.equal(written, '1000-1 Syn Castle Keep');
  await p.reset.fire('click');
  assert.equal(p.field.value, GENERATED); assert.equal(p.edited.hidden, true); assert.equal(p.sheetStatus.textContent, '');
  p.field.value = GENERATED + '\n'; await p.field.fire('input'); p.field.value = GENERATED; await p.field.fire('input');
  assert.equal(p.edited.hidden, true, 'typing the generated text back is not an edit');

  // No clipboard: the selection copy, through a field holding the text.
  const commands = [];
  ({B, env} = load({clipboard: undefined, execCommand: c => { commands.push(c); return true; }}));
  p = page(); B.wire(p.section, env);
  await p.cardButton.fire('click');
  assert.deepEqual(commands, ['copy']); assert.equal(p.cardStatus.textContent, 'Copied'); assert.equal(env.document.body.appended[0].value, GENERATED); assert.ok(env.document.removed);

  // A clipboard that refuses falls through to the selection copy as well.
  ({B, env} = load({clipboard: {writeText: async () => { throw new Error('denied'); }}, execCommand: () => true}));
  p = page(); B.wire(p.section, env); await p.sheetButton.fire('click');
  assert.equal(p.sheetStatus.textContent, 'Copied');

  // Neither works: Copy failed in the preview, which opens with the text selected so it can be copied by hand.
  ({B, env} = load({clipboard: undefined, execCommand: () => false}));
  p = page(); B.wire(p.section, env);
  await p.cardButton.fire('click');
  assert.equal(p.sheet.open, true); assert.ok(p.field.focused && p.field.selected);
  assert.equal(p.sheetStatus.textContent, 'Copy failed · select and copy by hand'); assert.equal(p.cardStatus.textContent, '');
  ({B, env} = load({clipboard: undefined, execCommand: () => { throw new Error('no'); }}));
  p = page(); B.wire(p.section, env); await p.sheetButton.fire('click');
  assert.equal(p.sheetStatus.textContent, 'Copy failed · select and copy by hand');

  // A disabled button copies nothing.
  written = null;
  ({B, env} = load({clipboard: {writeText: async t => { written = t; }}}));
  p = page(); p.cardButton.disabled = true; B.wire(p.section, env); await p.cardButton.fire('click');
  assert.equal(written, null); assert.equal(p.cardStatus.textContent, '');

  // Missing parts is open at 1024 and wider, closed below.
  ({B, env} = load({clipboard: undefined, wide: true})); p = page(); B.wire(p.section, env); assert.equal(p.dis.open, true);
  ({B, env} = load({clipboard: undefined, wide: false})); p = page(); B.wire(p.section, env); assert.equal(p.dis.open, false);
  console.log('sell runtime ok');
})().catch(error => { console.error(error); process.exit(1); });
