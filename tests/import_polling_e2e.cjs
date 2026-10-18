/* Feed real polled /manage/add/jobs/<id> events to the shipped progress widget. Usage: node file.cjs events.json */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
 constructor() { this.style = {}; this.attrs = {}; this.events = {}; this.textContent = ''; this.hidden = false; }
 setAttribute(key, value) { this.attrs[key] = value; }
 addEventListener(key, callback) { this.events[key] = callback; }
 removeEventListener(key) { delete this.events[key]; }
}
const scenarios = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/web/toni/import-progress.js'), 'utf8'), context);
const out = {};
for (const [name, scenario] of Object.entries(scenarios)) {
 const nodes = Object.fromEntries(['bar', 'fill', 'message', 'retry'].map(n => [`[data-import-${n}]`, new Element()]));
 const root = {dataset: {importJob: String(scenario.job)}, querySelector: key => nodes[key]};
 const listeners = {};
 const channel = {connected: true, on(k, f) { listeners[k] = f; }, off() {}};
 const retried = [];
 const ui = new context.window.BrickImportProgress(root, channel, {jobId: scenario.job, retry: (job, step) => { retried.push([job, step]); return true; }});
 for (const poll of scenario.polls) poll.events.forEach(event => listeners.import_progress(event));
 out[name] = {width: parseFloat(nodes['[data-import-fill]'].style.width), message: nodes['[data-import-message]'].textContent,
              retryHidden: nodes['[data-import-retry]'].hidden};
 if (scenario.click) { nodes['[data-import-retry]'].events.click(); out[name].retried = retried; }
 ui.destroy();
}
console.log(JSON.stringify(out));
