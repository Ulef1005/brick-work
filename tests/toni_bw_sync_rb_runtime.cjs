/* Rebrickable preview (#519): the conflict tab shows the conflicts card, To Rebrickable includes the Lost Parts send rows, a card whose rows are
   all hidden goes with them, and a renamed or dropped list counts as a chosen change. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{constructor(dataset={}){this.dataset=dataset;this.events={};this.attrs={};this.hidden=false;this.textContent='';this.checked=false;this.value='';this.disabled=false;}
 addEventListener(k,f){this.events[k]=f;}setAttribute(k,v){this.attrs[k]=String(v);}getAttribute(k){return this.attrs[k]??null;}}
const row=(state,name,also)=>new Node({state,name,also:also||''});
const conflict=row('conflict','10004-1 Ship'),into=row('into','10001-1 Galaxy'),to=row('to','10002-1 Castle'),lost=row('lost','Lost 3001','into'),sendLost=row('lost','Lost send 3001','to'),parts=row('parts','3001 red','into');
const rows=[conflict,into,to,lost,sendLost,parts];
const cards=[Object.assign(new Node(),{querySelectorAll:()=>[conflict]}),Object.assign(new Node(),{querySelectorAll:()=>[lost]}),Object.assign(new Node(),{querySelectorAll:()=>[sendLost]})];
const tabs=['all','into','to','conflict','lost','parts'].map(v=>new Node({syTab:v}));
const ticks=[new Node()];ticks[0].checked=true;
const listpick=new Node();listpick.value='keep';
const search=new Node(),submit=new Node({syVerb:'Run'}),total=new Node({syOf:'4'});
const form=new Node();form.dataset.syDirection='run';
form.querySelectorAll=s=>({'[data-sy-row]':rows,'[data-sy-tab]':tabs,'[data-sy-tick]:checked':ticks.filter(t=>t.checked),'[data-sy-card]':cards,'[data-sy-listpick]':[listpick],'[data-sy-send]:checked':[]})[s]||[];
form.querySelector=s=>({'[data-sy-search]':search,'[data-sy-submit]':submit,'[data-sy-total]':total,'[data-sy-requests]':null})[s]||null;
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-sync.js','utf8'),{document:{querySelectorAll:s=>s==='[data-sy-plan]'?[form]:[]},setTimeout});
const hidden=()=>rows.map(r=>r.hidden);
assert.equal(submit.textContent,'Run 1 change');assert.equal(total.textContent,'1 of 4 chosen');
tabs[3].events.click();                                   // Changed in both places: the conflicts card's rows, nothing else
assert.deepEqual(hidden(),[false,true,true,true,true,true]);assert.deepEqual(cards.map(c=>c.hidden),[false,true,true]);
tabs[2].events.click();                                   // To Rebrickable: the send rows and the Lost Parts send rows
assert.deepEqual(hidden(),[true,true,false,true,false,true]);assert.deepEqual(cards.map(c=>c.hidden),[true,true,false]);
tabs[1].events.click();                                   // Into Brick Work: sets, Lost Parts coming in, loose stock
assert.deepEqual(hidden(),[true,false,true,false,true,false]);
tabs[0].events.click();assert.deepEqual(hidden(),[false,false,false,false,false,false]);assert.deepEqual(cards.map(c=>c.hidden),[false,false,false]);
ticks[0].checked=false;form.events.change();              // nothing ticked, no list changed: nothing to run
assert.equal(submit.textContent,'Run');assert.equal(submit.disabled,true);
listpick.value='rename';form.events.change();             // a renamed list is a chosen change
assert.equal(submit.textContent,'Run 1 change');assert.equal(submit.disabled,false);
listpick.value='drop';form.events.change();assert.equal(submit.disabled,false);
listpick.value='skip';form.events.change();assert.equal(submit.disabled,true);
console.log('Rebrickable preview: tabs, cards and list choices passed');
