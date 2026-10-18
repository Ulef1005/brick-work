const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const cases = require('./toni_name_tail_cases.json');
const shared = fs.readFileSync('static/web/toni/formatting.js', 'utf8');
const base = fs.readFileSync('templates/web/toni/base.html', 'utf8');
assert.ok(base.indexOf("web/toni/formatting.js") < base.indexOf('{% block page_assets %}'));
assert.ok(base.includes("web/toni/formatting.js') }}\" defer"));
assert.ok(!shared.includes('(?<'));
for (const bundle of ['collection', 'checker', 'inventory', 'ledger', 'workbench']) {
  const source = fs.readFileSync(`static/web/toni/bw-${bundle}.js`, 'utf8');
  assert.ok(!source.includes('(?<'), bundle);
  const binding = 'const nowrapTail = window.BrickFormatting.nowrapTail;';
  assert.ok(source.includes(binding), bundle);
  const context = {window: {}, document: {querySelector() { return null; }, addEventListener() {}}};
  vm.runInNewContext(shared, context);
  // Observe the bundle's actual local binding without adding a production test API.
  vm.runInNewContext(source.replace(binding, binding + ' window.bundleNowrapTail = nowrapTail;'), context);
  const helper = context.window.bundleNowrapTail;
  assert.equal(helper, context.window.BrickFormatting.nowrapTail);
  for (const [value, expected] of cases) assert.equal(helper(value), expected, `${bundle}: ${value}`);
  assert.equal(helper(undefined), '', bundle);
}
console.log('Shared name-tail formatting passed in all five bundles');

const displayContext = {window: {}};
vm.runInNewContext(shared, displayContext);
const {partName, nowrapTail} = displayContext.window.BrickFormatting;
assert.equal(nowrapTail(partName('Bracket 1 x 2 - 1 x 2 Inverted')), 'Bracket 1 x 2 · 1 x 2\u00a0Inverted');
assert.equal(partName('Plate - Modified'), 'Plate - Modified');
assert.equal(partName('600-2'), '600-2');
assert.equal(partName(null), '');
