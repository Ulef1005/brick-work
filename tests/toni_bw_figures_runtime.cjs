'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(require('path').join(__dirname, '../static/web/toni/bw-figures.js'), 'utf8');
for (const desktop of [true, false]) {
  const rule = {};
  vm.runInNewContext(source, {document:{querySelector:()=>rule}, window:{matchMedia:q=>{assert.equal(q,'(min-width: 701px)'); return {matches:desktop};}}});
  assert.equal(rule.open, desktop);
}
vm.runInNewContext(source, {document:{querySelector:()=>null}});
console.log('Figures disclosure runtime passed');
