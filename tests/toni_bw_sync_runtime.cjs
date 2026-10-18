/* 12n plan pages: tabs and search filter rows, the main button counts ticks, conflicts stay in their card. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{constructor(dataset={}){this.dataset=dataset;this.events={};this.attrs={};this.hidden=false;this.textContent='';this.checked=false;this.value='';this.disabled=false;}
 addEventListener(k,f){this.events[k]=f;}setAttribute(k,v){this.attrs[k]=String(v);}getAttribute(k){return this.attrs[k]??null;}}
const rows=[['add','10001-1 Galaxy'],['add','10002-1 Castle'],['differs','10003-1 Train'],['conflict','10004-1 Ship']].map(([s,n])=>new Node({state:s,name:n}));
const ticks=[new Node(),new Node(),new Node()];ticks[0].checked=true;ticks[1].checked=true;
const tabs=['all','add','differs'].map(v=>new Node({syTab:v}));
const search=new Node(),submit=new Node({syVerb:'Pull'}),total=new Node();
const form=new Node();
form.querySelectorAll=s=>s==='[data-sy-row]'?rows:s==='[data-sy-tab]'?tabs:s==='[data-sy-tick]:checked'?ticks.filter(t=>t.checked):[];
form.querySelector=s=>({'[data-sy-search]':search,'[data-sy-submit]':submit,'[data-sy-total]':total,'[data-sy-requests]':null})[s]||null;
const document={querySelectorAll:s=>s==='[data-sy-plan]'?[form]:[]};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-sync.js','utf8'),{document,setTimeout});
assert.equal(submit.textContent,'Pull 2 changes');assert.equal(submit.disabled,false);
ticks[0].checked=false;ticks[1].checked=false;form.events.change();
assert.equal(submit.textContent,'Pull');assert.equal(submit.disabled,true);
tabs[2].events.click();
assert.deepEqual(rows.map(r=>r.hidden),[true,true,false,false]);
assert.equal(tabs[2].getAttribute('aria-pressed'),'true');assert.equal(tabs[0].getAttribute('aria-pressed'),'false');
tabs[0].events.click();search.value='castle';search.events.input();
assert.deepEqual(rows.map(r=>r.hidden),[true,false,true,false]);
console.log('Sync plan: tabs, search, tick count and conflict card passed');
