/* Minimal DOM and fake official-socket seam. No browser or network needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
 constructor() { this.style = {}; this.attrs = {}; this.events = {}; this.textContent = ''; this.hidden = false; }
 setAttribute(key, value) { this.attrs[key] = value; }
 addEventListener(key, callback) { this.events[key] = callback; }
 removeEventListener(key, callback) { assert.equal(this.events[key], callback); delete this.events[key]; }
}
const nodes = Object.fromEntries(['bar','fill','message','retry'].map(name => [`[data-import-${name}]`, new Element()]));
const root = {dataset: {importJob: '42'}, querySelector: key => nodes[key]};
const listeners = {};
const sends = [];
const socket = {
 connected: true,
 on(key, callback) { listeners[key] = callback; },
 off(key, callback) { assert.equal(listeners[key], callback); delete listeners[key]; },
 emit(key, payload) { if (!this.connected) return false; sends.push([key,payload]); return true; }
};
const context = {window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/web/toni/import-progress.js'), 'utf8'), context);
const ui = new context.window.BrickImportProgress(root, socket);
const update = data => listeners.import_progress({job_id:42, step:'inventory', total_steps:6, completed_steps:1, total:112, count:38, ...data});
update({state:'progress', message:'Fetching parts from BrickLink · 38 of 112'});
assert.match(nodes['[data-import-message]'].textContent, /38 of 112/);
assert(Math.abs(parseFloat(nodes['[data-import-fill]'].style.width) - 22.32142857) < 0.01);
update({state:'waiting',step:'pictures',total_steps:1,completed_steps:0,total:100,count:38,message:'Downloading images · 38 of 100 · waiting for budget'});
assert.equal(nodes['[data-import-fill]'].style.width,'38%');
update({job_id:7, state:'failed', message:'Other tab'});
assert(!nodes['[data-import-message]'].textContent.includes('Other tab'));
update({state:'failed', message:'BrickLink failed · subsets unavailable'});
assert.equal(nodes['[data-import-retry]'].hidden, false);
update({step:'pictures', state:'done', completed_steps:2});
assert.equal(nodes['[data-import-retry]'].hidden, false); // Other successful steps do not erase failure.
socket.connected = false;
listeners.disconnect();
assert.equal(nodes['[data-import-retry]'].disabled, true);
ui.retry();
assert.equal(sends.length, 0);
socket.connected = true;
listeners.connect();
ui.retry();
ui.retry();
assert.equal(sends.length, 1);
assert.equal(sends[0][0], 'import_retry');
assert.equal(sends[0][1].job_id, 42);
assert.equal(sends[0][1].step, 'inventory');
update({state:'started', message:'Fetching parts from BrickLink'});
assert.equal(nodes['[data-import-retry]'].hidden, true);
update({state:'failed', message:'<img src=x onerror=alert(1)>'});
assert.equal(nodes['[data-import-message]'].textContent, '<img src=x onerror=alert(1)>');
update({state:'progress', total:0, count:'NaN', completed_steps:0});
assert.equal(nodes['[data-import-fill]'].style.width, '0%');
update({state:'done', step:null, completed_steps:6, message:'Import complete'});
assert.equal(nodes['[data-import-fill]'].style.width, '100%');
assert.equal(nodes['[data-import-retry]'].hidden, true);
ui.destroy();
assert.equal(Object.keys(listeners).length, 0);
console.log('Import progress runtime passed');
